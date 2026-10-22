"""Template registry (design §6; spec §5.2/§5.6): content-addressed objects, immutable numbered snapshots, CURRENT
pointer, append-only audit journal, single-writer lock, per-version state machine, audited recovery.

Layout (under <app data>/templates/):
  objects/<sha256>.md    immutable copies of template bytes (exclusive create, verified on every read)
  snapshots/<N>.json     every committed registry state (records + user prefs); never rewritten
  CURRENT                number of the current snapshot (atomic os.replace)
  journal.log            one JSON line per event
  .lock                  {pid, host, started, op}
  quarantine/<ts>/       residue moved aside by recovery (never deleted)

The template library folder (<vault>/模板库) is only ever READ. Every mutation (refresh, approve, pin, …) commits a
new snapshot, so history is replayable and a crash leaves CURRENT on the last complete state.
"""
from __future__ import annotations

import copy
import os
import stat
from pathlib import Path

from ..errors import Stop
from ..store.core import STALE_S, Corrupt, Locked, Store, sha  # noqa: F401  (re-exported)
from . import builtin, vocab
from .format import MAX_BYTES, Section, Template, parse_template

MAX_FILES = 200
MAX_DEPTH = 2
LIVE = ("ACTIVE", "NEEDS_REVIEW", "DISABLED", "CONFLICT")
STATUS_ZH = {"ACTIVE": "启用", "NEEDS_REVIEW": "待审", "REJECTED": "拒绝", "SUPERSEDED": "已被新版替代",
             "DISABLED": "已停用", "REMOVED": "文件已移除", "CONFLICT": "ID 冲突"}


_sha = sha


def _empty() -> dict:
    return {"n": 0, "created": None, "records": [], "prefs": {"pins": {}, "default_main": None, "prefer_for": {},
                                                            "prefer_for_project": {}}}


def record_from(t: Template, *, source: str, version: int, status: str, now: str) -> dict:
    return {"id": t.id, "registry_version": version, "sha256": t.sha256, "size_bytes": t.size, "path": t.path,
            "source": source, "role": t.role, "title": t.title, "declared_version": t.declared_version,
            "language": t.language,
            "applies_to": {"study_types": t.study_types, "reading_levels": t.reading_levels, "topics": t.topics},
            "priority": t.priority, "compatible_with": t.compatible_with, "features": t.features,
            "required_fields": t.required_fields, "status": status, "errors": t.errors, "review_reasons": t.review,
            "warnings": t.warnings, "classification_note": ("front matter 声明" if not t.missing_front_matter else "缺少 front matter"),
            "tags_source": "front_matter" if not t.missing_front_matter else None, "overrides": [], "ai_suggested": None,
            "first_seen": now, "last_seen": now, "superseded_by": None}


class Registry(Store):
    LABEL = "模板登记"
    CMD = "litreader templates recover"
    EXT = ".md"

    def __init__(self, root: Path, library: Path | None, **kw):
        super().__init__(root, **kw)
        self.library = Path(library) if library else None

    def _empty(self) -> dict:
        return _empty()


    def load_bytes(self, rec: dict) -> bytes:
        return self.object_bytes(rec["sha256"], f"模板 {rec['id']}@{rec['registry_version']}")

    def load_template(self, rec: dict) -> Template:
        t = parse_template(self.load_bytes(rec), rec["path"])
        # user overrides recorded at approve time (spec §5.2 人工覆盖记录); template file itself is never changed
        ov = rec.get("applied") or {}
        if ov.get("role"):
            t.role = ov["role"]
        if ov.get("study_types"):
            t.study_types = list(ov["study_types"])
        if ov.get("sections"):
            t.sections = [Section(**s) for s in ov["sections"]]
        if not t.id:
            t.id = rec["id"]
        return t

    # ------------------------------------------------------------------ discovery
    def scan(self) -> tuple[list[tuple[str, bytes | None, str | None]], list[str]]:
        """Read-only walk of the library: (relative path, bytes or None, rejection reason or None)."""
        out, notes = [], []
        lib = self.library
        if not lib or not lib.exists():
            return out, notes
        if lib.is_symlink() or not lib.is_dir():
            raise Stop(f"模板库路径不是普通文件夹（或是符号链接）：{lib}")

        def walk(d: Path, rel: str, depth: int):
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError as e:
                notes.append(f"无法读取 {rel or '.'}：{e.__class__.__name__}")
                return
            for e in entries:
                if len(out) >= MAX_FILES:
                    notes.append(f"模板库文件超过 {MAX_FILES} 个，其余未读取")
                    return
                if e.name.startswith((".", "_")):
                    continue
                r = f"{rel}{e.name}"
                if e.is_symlink():
                    if e.name.endswith(".md"):
                        out.append((r, None, "符号链接（不跟随）"))
                    else:
                        notes.append(f"跳过符号链接 {r}")
                    continue
                if e.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH:
                        walk(Path(e.path), r + "/", depth + 1)
                    else:
                        notes.append(f"跳过过深的子文件夹 {r}")
                    continue
                if not e.name.endswith(".md"):
                    continue
                st = e.stat(follow_symlinks=False)
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_nlink > 1:
                    out.append((r, None, "硬链接（拒绝）"))
                    continue
                if st.st_size > MAX_BYTES:
                    out.append((r, None, f"文件过大（{st.st_size} 字节）"))
                    continue
                fd = os.open(e.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "rb") as f:
                    out.append((r, f.read(MAX_BYTES + 1), None))
        walk(lib, "", 0)
        return out, notes

    def refresh(self, tagger=None) -> tuple[dict, list[dict], list[str]]:
        """Incremental registration. Returns (snapshot, events, notes). No change -> no new snapshot."""
        with self.lock("refresh"):
            prev = self.snapshot(verify=True)
            now = self.ts()
            recs = [copy.deepcopy(r) for r in prev["records"]]
            by_key = {(r["id"], r["sha256"]): r for r in recs}
            events: list[dict] = []
            blobs: list[bytes] = []
            found: list[tuple[str, Template, bytes | None, str]] = []
            for tid in builtin.all_ids():
                b = builtin.raw(tid)
                found.append(("builtin", parse_template(b, f"builtin:{builtin.FILES[tid]}"), b, "builtin"))
            files, notes = self.scan()
            for rel, b, why in files:
                if b is None:
                    t = Template(path=rel, sha256=_sha(rel.encode()), size=0, errors=[why])
                    t.id = f"file:{rel}"
                    found.append(("library", t, None, rel))
                    continue
                t = parse_template(b, rel)
                if not t.id:
                    t.id = "user." + _sha(rel.encode())[:8]
                found.append(("library", t, b, rel))
            # conflicts: one id, several different contents present at the same time
            ids: dict[str, set] = {}
            for src, t, b, rel in found:
                if not t.errors:
                    ids.setdefault(t.id, set()).add(t.sha256)
            seen = set()
            for src, t, b, rel in found:
                key = (t.id, t.sha256)
                seen.add(key)
                if b is not None:
                    blobs.append(b)
                conflict = len(ids.get(t.id, ())) > 1
                r = by_key.get(key)
                if r:
                    if r["path"] != t.path:
                        events.append({"op": "MOVED", "id": t.id, "version": r["registry_version"], "sha": t.sha256,
                                       "from_path": r["path"], "to_path": t.path})
                        r["path"] = t.path
                    if r["status"] == "REMOVED":
                        back = r.pop("status_before_removed", None) or t.status_hint()
                        events.append(_ev("RESTORED", r, "REMOVED", back, "文件重新出现且内容相同"))
                        r["status"] = back
                    if r["status"] == "SUPERSEDED" and not conflict and r["source"] != "builtin" and not any(
                            x is not r and x["id"] == t.id and x["status"] in ("ACTIVE", "NEEDS_REVIEW") for x in recs):
                        events.append(_ev("RESTORED", r, "SUPERSEDED", "ACTIVE", "旧版本内容重新出现（文件被改回），且没有更新的版本在用"))
                        r["status"], r["superseded_by"] = "ACTIVE", None
                    if r["status"] == "CONFLICT" and not conflict:
                        back = r.pop("status_before_conflict", None) or t.status_hint()
                        events.append(_ev("STATUS", r, "CONFLICT", back, "ID 冲突已解除"))
                        r["status"] = back
                        if back == "ACTIVE":
                            events += self._supersede(recs, r)
                    elif conflict and r["status"] in ("NEEDS_REVIEW",):
                        r["status_before_conflict"] = r["status"]
                        events.append(_ev("STATUS", r, r["status"], "CONFLICT", "同一 ID 有多个不同内容的文件"))
                        r["status"] = "CONFLICT"
                    r["last_seen"] = now if events and events[-1].get("id") == t.id else r["last_seen"]
                    continue
                ver = max([x["registry_version"] for x in recs if x["id"] == t.id] or [0]) + 1
                status = t.status_hint()
                if conflict and status != "REJECTED":
                    status = "CONFLICT"
                r = record_from(t, source=src, version=ver, status=status, now=now)
                if b is None:
                    r["object"] = False
                if status in ("NEEDS_REVIEW",) and tagger and (t.missing_front_matter or not t.role or not t.study_types):
                    r["ai_suggested"] = _safe_tag(tagger, t, b)
                    r["tags_source"] = "ai_suggested" if r["ai_suggested"] else r["tags_source"]
                recs.append(r)
                by_key[key] = r
                events.append(_ev("NEW" if ver == 1 else "NEW_VERSION", r, None, status,
                                  "; ".join((t.errors + t.review)[:3]) or "front matter 完整"))
                if status == "ACTIVE":
                    events += self._supersede(recs, r)
            for r in recs:   # library files that disappeared
                if r["source"] == "library" and (r["id"], r["sha256"]) not in seen and r["status"] in LIVE:
                    events.append(_ev("STATUS", r, r["status"], "REMOVED", "模板库中已找不到该文件"))
                    r["status_before_removed"] = r["status"]
                    r["status"] = "REMOVED"
            if not events and prev["n"]:
                return prev, [], notes
            events.insert(0, {"op": "REFRESH", "files": len(files), "notes": notes[:5]})
            snap = self._commit({"records": recs, "prefs": prev["prefs"]}, events, blobs)
            return snap, events, notes

    def _supersede(self, recs, new) -> list[dict]:
        ev = []
        for x in recs:
            if x is not new and x["id"] == new["id"] and x["status"] == "ACTIVE":
                ev.append(_ev("STATUS", x, "ACTIVE", "SUPERSEDED", f"被 v{new['registry_version']} 替代"))
                x["status"], x["superseded_by"] = "SUPERSEDED", new["registry_version"]
        return ev

    # ------------------------------------------------------------------ user operations
    def find(self, snap: dict, tid: str, version: int | None = None) -> dict:
        cands = [r for r in snap["records"] if r["id"] == tid]
        if not cands:
            raise Stop(f"没有登记过模板「{tid}」（先运行 litreader templates refresh，或用 templates list 查看 ID）")
        if version is None:
            act = [r for r in cands if r["status"] in ("ACTIVE", "NEEDS_REVIEW", "DISABLED", "CONFLICT")]
            return max(act or cands, key=lambda r: r["registry_version"])
        for r in cands:
            if r["registry_version"] == version:
                return r
        raise Stop(f"模板「{tid}」没有版本 v{version}")

    def _mutate(self, op: str, fn):
        with self.lock(op):
            snap = copy.deepcopy(self.snapshot(verify=True))
            if not snap["n"]:
                raise Stop("模板登记为空：先运行 litreader templates refresh")
            events = fn(snap)
            return self._commit({"records": snap["records"], "prefs": snap["prefs"]}, events)

    def approve(self, tid: str, version: int, *, role: str | None = None, study_types: list[str] | None = None,
                use_ai: bool = True) -> dict:
        def fn(snap):
            r = self.find(snap, tid, version)
            if r["status"] != "NEEDS_REVIEW":
                raise Stop(f"{tid}@{version} 当前状态是「{STATUS_ZH[r['status']]}」，只有待审版本可以批准")
            applied = {}
            sug = r.get("ai_suggested") or {}
            rr = role or (sug.get("role") if use_ai else None)
            if rr:
                rr = vocab.ROLES.get(rr, rr)
                if rr not in vocab.ROLES.values():
                    raise Stop(f"角色 {rr} 不在 main/module/overview/evidence 中")
                applied["role"] = rr
            st = study_types or (sug.get("study_types") if use_ai else None)
            if st:
                bad = [s for s in st if s != vocab.ANY and s not in vocab.STUDY_TYPES]
                if bad:
                    raise Stop(f"论文类型不在受控词表中：{bad}")
                applied["study_types"] = list(st)
            if use_ai and sug.get("sections"):
                applied["sections"] = sug["sections"]
            if not (r.get("role") or applied.get("role")):
                raise Stop("该模板没有角色：用 --role main|module|overview 指定后再批准")
            if (applied.get("role") or r.get("role")) in ("MAIN_NOTE", "MODULE") and not (
                    r["applies_to"]["study_types"] or applied.get("study_types")):
                raise Stop("该模板没有适用论文类型：用 --types any 或 --types rct,cohort 指定后再批准")
            r["applied"] = applied
            if applied.get("role"):
                r["role"] = applied["role"]
            if applied.get("study_types"):
                r["applies_to"]["study_types"] = applied["study_types"]
            r["overrides"].append({"t": self.ts(), "action": "approve", "applied": applied})
            r["tags_source"] = "user" if (role or study_types) else (r.get("tags_source") or "front_matter")
            r["status"] = "ACTIVE"
            ev = [_ev("APPROVE", r, "NEEDS_REVIEW", "ACTIVE", "用户批准" + (f"，覆盖 {applied}" if applied else ""))]
            return ev + self._supersede(snap["records"], r)
        return self._mutate("approve", fn)

    def set_status(self, tid: str, version: int | None, to: str, op: str) -> dict:
        allowed = {"reject": ("NEEDS_REVIEW", "CONFLICT"), "disable": ("ACTIVE",), "enable": ("DISABLED",)}[op]

        def fn(snap):
            r = self.find(snap, tid, version)
            if r["source"] == "builtin" and r["id"] == builtin.FALLBACK and op != "enable":
                raise Stop(f"{builtin.FALLBACK} 是回退模板，不能停用或拒绝")
            if r["status"] not in allowed:
                raise Stop(f"{tid}@{r['registry_version']} 当前是「{STATUS_ZH[r['status']]}」，不能执行 {op}")
            old = r["status"]
            r["status"] = to
            r["overrides"].append({"t": self.ts(), "action": op})
            for k in ("default_main",):
                if op in ("disable", "reject") and snap["prefs"].get(k) == tid:
                    snap["prefs"][k] = None
            return [_ev(op.upper(), r, old, to, "用户操作")]
        return self._mutate(op, fn)

    def pin(self, tid: str, version: int) -> dict:
        def fn(snap):
            r = self.find(snap, tid, version)
            if r["status"] in ("REJECTED", "NEEDS_REVIEW", "CONFLICT"):
                raise Stop(f"{tid}@{version} 状态「{STATUS_ZH[r['status']]}」，不能固定使用")
            old = snap["prefs"]["pins"].get(tid)
            snap["prefs"]["pins"][tid] = version
            return [{"op": "PIN", "id": tid, "version": version, "from": old, "sha": r["sha256"]}]
        return self._mutate("pin", fn)

    def unpin(self, tid: str) -> dict:
        def fn(snap):
            old = snap["prefs"]["pins"].pop(tid, None)
            if old is None:
                raise Stop(f"{tid} 没有固定版本")
            return [{"op": "UNPIN", "id": tid, "from": old}]
        return self._mutate("unpin", fn)

    def effective(self, snap: dict, tid: str) -> dict | None:
        pv = snap["prefs"]["pins"].get(tid)
        if pv is not None:
            return next((r for r in snap["records"] if r["id"] == tid and r["registry_version"] == pv), None)
        act = [r for r in snap["records"] if r["id"] == tid and r["status"] == "ACTIVE"]
        return max(act, key=lambda r: r["registry_version"]) if act else None

    def rollback(self, tid: str) -> dict:
        def fn(snap):
            cur = self.effective(snap, tid)
            if not cur:
                raise Stop(f"{tid} 当前没有可用版本，无法回滚")
            older = [r for r in snap["records"] if r["id"] == tid and r["registry_version"] < cur["registry_version"]
                     and r["status"] in ("SUPERSEDED", "ACTIVE", "REMOVED", "DISABLED")]
            if not older:
                raise Stop(f"{tid} 没有更早的可用版本（v{cur['registry_version']} 已是最早）")
            tgt = max(older, key=lambda r: r["registry_version"])
            snap["prefs"]["pins"][tid] = tgt["registry_version"]
            return [{"op": "ROLLBACK", "id": tid, "from": cur["registry_version"], "version": tgt["registry_version"],
                     "sha": tgt["sha256"]}]
        return self._mutate("rollback", fn)

    def prefer(self, tid: str | None, study_type: str | None = None, project: str | None = None) -> dict:
        def fn(snap):
            if project:   # tier 3 (spec §5.4): explicit association template <-> project_id, never text similarity
                if tid is not None:
                    r = self.effective(snap, tid)
                    if not r or r["role"] != "MAIN_NOTE":
                        raise Stop(f"{tid} 不是可用的主模板")
                pp = snap["prefs"].setdefault("prefer_for_project", {})
                old = pp.get(project)
                if tid is None:
                    pp.pop(project, None)
                else:
                    pp[project] = tid
                return [{"op": "PREFER", "id": tid, "project": project, "from": old}]
            if study_type and study_type not in vocab.STUDY_TYPES:
                raise Stop(f"论文类型 {study_type} 不在受控词表中：{', '.join(vocab.STUDY_TYPES)}")
            if tid is not None:
                r = self.effective(snap, tid)
                if not r or r["role"] != "MAIN_NOTE":
                    raise Stop(f"{tid} 不是可用的主模板（总览/模块/待审模板不能设为首选）")
            if study_type:
                old = snap["prefs"]["prefer_for"].get(study_type)
                if tid is None:
                    snap["prefs"]["prefer_for"].pop(study_type, None)
                else:
                    snap["prefs"]["prefer_for"][study_type] = tid
            else:
                old = snap["prefs"].get("default_main")
                snap["prefs"]["default_main"] = tid
            return [{"op": "PREFER", "id": tid, "study_type": study_type, "from": old}]
        return self._mutate("prefer", fn)

    def add_draft(self, raw: bytes, note: str) -> dict:
        """AI-drafted template (design decision 1C): stored only in the registry, always NEEDS_REVIEW."""
        t = parse_template(raw, "ai_draft")
        if not t.id:
            raise Stop("草稿缺少 id")

        def fn(snap):
            ver = max([x["registry_version"] for x in snap["records"] if x["id"] == t.id] or [0]) + 1
            t.path = f"ai_draft:{t.id}@{ver}"
            st = "REJECTED" if t.errors else "NEEDS_REVIEW"
            r = record_from(t, source="ai_draft", version=ver, status=st, now=self.ts())
            r["classification_note"] = note
            r["tags_source"] = "ai_suggested"
            snap["records"].append(r)
            return [_ev("DRAFT", r, None, st, note)]
        with self.lock("draft"):
            self._put_object(raw)
        return self._mutate("draft", fn)

    def add_user(self, raw: bytes, note: str) -> tuple[dict, dict]:
        """Template created in the GUI (stage G6): stored ONLY in the registry (source "user"); the library folder is
        never written. Same status rule as a library file (complete front matter -> ACTIVE, otherwise NEEDS_REVIEW,
        errors -> REJECTED). The id must be new, so an existing template is never superseded. Returns (snap, rec)."""
        t = parse_template(raw, "user")
        if not t.id:
            raise Stop("新模板缺少 id")
        if t.errors:
            raise Stop("新模板不合格：" + "；".join(t.errors[:3]))
        def fn(snap):
            if any(x["id"] == t.id for x in snap["records"]):
                raise Stop(f"模板 id {t.id} 已存在")
            t.path = f"user:{t.id}@1"
            r = record_from(t, source="user", version=1, status=t.status_hint(), now=self.ts())
            r["classification_note"] = note
            r["tags_source"] = "user"
            snap["records"].append(r)
            return [_ev("NEW", r, None, r["status"], note)]
        with self.lock("create"):
            self._put_object(raw)
        snap = self._mutate("create", fn)
        return snap, self.find(snap, t.id, 1)


def _ev(op, r, frm, to, reason) -> dict:
    return {"op": op, "id": r["id"], "version": r["registry_version"], "sha": r["sha256"], "from": frm, "to": to,
            "reason": reason}


def _safe_tag(tagger, t: Template, b: bytes | None) -> dict | None:
    """AI suggestion for a template lacking front matter. Only controlled-vocabulary values survive."""
    from .sanitize import clean_title
    heads = []
    if b:
        import re
        heads = [clean_title(m.group(1)) for m in re.finditer(r"^#{1,3}\s+(.+)$", b.decode("utf-8", "replace"), re.M)][:40]
    try:
        s = tagger({"title": t.title, "headings": heads})
    except Exception:   # model failure -> stays NEEDS_REVIEW without a suggestion (never guess)
        return None
    if not isinstance(s, dict):
        return None
    role = s.get("role") if s.get("role") in vocab.ROLES else None
    st = [x for x in (s.get("study_types") or []) if x == vocab.ANY or x in vocab.STUDY_TYPES]
    try:
        conf = max(0.0, min(1.0, float(s.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    return {"role": role, "study_types": st, "confidence": conf, "reason": clean_title(str(s.get("reason") or ""), 60)}
