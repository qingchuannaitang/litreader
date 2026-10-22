"""Readable Markdown views of the project library in the vault (design §2.1, §3.4; decision 1 = A: under
<vault>/<output_dir>/科研项目库/ only (default litreader/)). The canonical record lives in the registry; these files are generated.

Write rules (R8 + design §7): 历史版本/ and 导入草稿/ files are exclusive-create, never rewritten. The five generated
files are replaced atomically ONLY if their current hash equals the hash this program last wrote (views.json);
a file the user edited is never overwritten — it is reported for the manual-edit flow instead.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..errors import AlreadyExists
from ..hashing import sha256_bytes, sha256_file
from ..permissions import Sandbox
from ..vault.writer import VaultWriter
from . import model

LIB = "科研项目库"
ARCHIVE = "课题档案.md"
GENERATED = (ARCHIVE, "当前项目摘要.md", "来源记录.md", "待确认建议.md")
ITEM_RE = re.compile(r"^- \*\*(?P<zh>[^*]+)\*\*〔(?P<st>已确认|待确认|未定|研究建议)〕：(?P<v>.*?)(?:　〔来源：(?P<src>[^〕]*)〕)?\s*$")
ZH2STATE = {v: k for k, v in model.STATE_ZH.items()}
BLOCK_RE = re.compile(r"```litreader-project\n(?P<j>\{.*?\})\n```\nsha256: (?P<h>[0-9a-f]{64})", re.S)


def _src(v: dict) -> str:
    s = v["source"]
    bits = [s["kind"], s["role"]]
    if s.get("file"):
        bits.append(s["file"].get("name", ""))
    if s.get("locator"):
        bits.append(s["locator"])
    return "·".join(b for b in bits if b)


def archive_md(obj: dict, *, default: bool) -> str:
    c = model.counts(obj)
    L = [f"# {model.title_of(obj)}", "",
         f"> [!info] 课题档案（{obj['project_id']}，v{obj['version']}{'，默认课题' if default else ''}{'，已归档' if obj['status'] == 'ARCHIVED' else ''}）",
         f"> 已确认 {c['CONFIRMED']} · 待确认 {c['PENDING']} · 未定 {c['UNDECIDED']}。只有“已确认”的内容会进入精读时使用的“当前项目摘要”。",
         "> 可以直接修改下面每一行冒号后的内容或〔状态〕；下次运行 litreader 时会列出差异请你确认。", ""]
    for mid, mname, items in model.MODULES:
        L += [f"## {mid} {mname}", ""]
        for k, zh in items:
            vals = [v for v in obj["items"].get(k) or [] if v["state"] != "SUGGESTION"]
            if not vals:
                L.append(f"- **{zh}**〔未定〕：")
            for v in vals:
                L.append(f"- **{zh}**〔{model.STATE_ZH[v['state']]}〕：{v['value']}　〔来源：{_src(v)}〕"
                         + (f" ⚠ {v['conflict']}" if v.get("conflict") else ""))
        L.append("")
    return "\n".join(L)


def summary_md(obj: dict) -> str:
    return "\n".join(["# 当前项目摘要", "", "> [!note] 精读时发给模型的就是下面这段文字（所见即所发），只含已确认内容。", "",
                      "```text", model.summary(obj), "```", ""])


def sources_md(obj: dict, history: list[dict]) -> str:
    L = ["# 来源记录", "", "| 版本 | 时间 | 操作 | 说明 |", "|---|---|---|---|"]
    for r in history:
        L.append(f"| v{r['version']} | {r['created']} | {r.get('op', '')} | {str(r.get('summary', '')).replace('|', '｜')} |")
    files = {}
    for vals in obj["items"].values():
        for v in vals:
            f = v["source"].get("file")
            if f:
                files[f["sha256"]] = f
    if files:
        L += ["", "## 导入过的文件", "", "| 文件名 | SHA-256 | 规模 |", "|---|---|---|"]
        L += [f"| {f.get('name')} | `{h[:16]}…` | {f.get('extent', '')} |" for h, f in files.items()]
    return "\n".join(L + [""])


def pending_md(obj: dict) -> str:
    L = ["# 待确认建议", "", "> [!question] 下列条目尚未确认，不会进入精读摘要。用 `litreader project review` 逐条处理。", ""]
    n = 0
    for k, (mid, mname, zh) in model.KEYS.items():
        for v in obj["items"].get(k) or []:
            if v["state"] in ("PENDING", "SUGGESTION"):
                n += 1
                q = f"　原文：「{v['source']['quote']}」" if v["source"].get("quote") else ""
                L.append(f"- [{model.STATE_ZH[v['state']]}] {mid} {zh}：{v['value']}（{_src(v)}）{q}"
                         + (f" ⚠ {v['conflict']}" if v.get("conflict") else ""))
    if not n:
        L.append("（无）")
    return "\n".join(L + [""])


def version_md(obj: dict) -> str:
    b = model.canonical(obj)
    return (archive_md(obj, default=False).replace("# ", f"# v{obj['version']}｜", 1)
            + f"\n## 本版本数据（程序用于校验与重建，请勿修改）\n\n```litreader-project\n{b.decode()}\n```\nsha256: {sha256_bytes(b)}\n")


def index_md(reg, snap) -> str:
    d = snap["prefs"].get("default_project")
    L = ["# 00-当前科研项目", "", "| 课题 | ID | 版本 | 状态 | 默认 |", "|---|---|---|---|---|"]
    for r in reg.projects(snap):
        L.append(f"| [[{r['folder']}/课题档案\\|{r['title']}]] | {r['id']} | v{r['version']} | "
                 f"{'已归档' if r['status'] == 'ARCHIVED' else '进行中'} | {'✅' if r['id'] == d else ''} |")
    if not snap["records"]:
        L.append("| （还没有课题） | | | | |")
    L += ["", "> 默认课题最多一个。精读时说“本次精读不关联任何课题”或“用〈课题〉角度精读…”只影响那一次。", ""]
    return "\n".join(L)


class Views:
    def __init__(self, dry_root: Path, state_file: Path):
        self.dry_root = Path(dry_root)
        self.state_file = Path(state_file)

    @property
    def root(self) -> Path:
        return self.dry_root / LIB

    def _state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, st: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.state_file)

    def writer(self, extra_replace=()) -> VaultWriter:
        self.dry_root.mkdir(parents=True, exist_ok=True)
        return VaultWriter(Sandbox(self.dry_root), replace_allowlist=set(extra_replace))

    def edited(self, rel: str) -> bool:
        p = self.dry_root / rel
        h = self._state().get(rel)
        return p.is_file() and h is not None and sha256_file(p) != h

    def manual_edits(self, reg, snap) -> list[str]:
        return [f"{LIB}/{r['folder']}/{ARCHIVE}" for r in reg.projects(snap) if self.edited(f"{LIB}/{r['folder']}/{ARCHIVE}")]

    def _put(self, rel: str, text: str, st: dict) -> str | None:
        """Create, or replace only if untouched since our last write. Returns a note when skipped."""
        data = text.encode()
        p = self.dry_root / rel
        if not p.exists():
            self.writer().create_exclusive(rel, data)
            st[rel] = sha256_bytes(data)
            return None
        cur = sha256_file(p)
        if cur == sha256_bytes(data):
            st[rel] = cur
            return None
        if st.get(rel) != cur:
            return f"{rel} 已被手动修改，未覆盖"
        self.writer({rel}).replace_atomic(rel, data, cur)
        st[rel] = sha256_bytes(data)
        return None

    def sync(self, reg, snap) -> list[str]:
        """(Re)generate all views; write each missing 历史版本 file. Never overwrites a user-edited file."""
        st, notes = self._state(), []
        dflt = snap["prefs"].get("default_project")
        for r in reg.projects(snap):
            base = f"{LIB}/{r['folder']}"
            hist = sorted([x for x in snap["records"] if x["id"] == r["id"]], key=lambda x: x["version"])
            for h in hist:
                rel = f"{base}/历史版本/v{h['version']:03d}.md"
                if not (self.dry_root / rel).exists():
                    self.writer().create_exclusive(rel, version_md(reg.load(h)).encode())
            obj = reg.load(r)
            for name, text in ((ARCHIVE, archive_md(obj, default=r["id"] == dflt)), ("当前项目摘要.md", summary_md(obj)),
                               ("来源记录.md", sources_md(obj, hist)), ("待确认建议.md", pending_md(obj))):
                n = self._put(f"{base}/{name}", text, st)
                if n:
                    notes.append(n)
        n = self._put(f"{LIB}/00-当前科研项目.md", index_md(reg, snap), st)
        if n:
            notes.append(n)
        self._save(st)
        return notes

    def save_edited_copy(self, rel: str, ts: str) -> str:
        """Before regenerating a user-edited archive, keep the user's bytes in 历史版本/ (exclusive create)."""
        p = self.dry_root / rel
        dst = str(Path(rel).parent / "历史版本" / f"手动编辑-{ts}.md")
        try:
            self.writer().create_exclusive(dst, p.read_bytes())
        except AlreadyExists:
            pass
        st = self._state()
        st[rel] = sha256_file(p)   # accept current bytes as "ours" so the next sync may regenerate
        self._save(st)
        return dst

    def draft(self, folder: str, text: str) -> str:
        base = f"{LIB}/{folder}/导入草稿"
        i = 1
        while (self.dry_root / f"{base}/d{i:03d}.md").exists():
            i += 1
        rel = f"{base}/d{i:03d}.md"
        self.writer().create_exclusive(rel, text.encode())
        return rel


def parse_archive(text: str) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """Read the user's edits back: {key: [(value, STATE)]} from recognised item lines + list of unrecognised lines."""
    items: dict[str, list[tuple[str, str]]] = {}
    unknown = []
    for ln in text.splitlines():
        s = ln.rstrip()
        if not s or s.startswith(("#", ">")):
            continue
        m = ITEM_RE.match(s)
        if m and m.group("zh") in model.ZH2KEY:
            v = re.sub(r"\s*⚠.*$", "", m.group("v")).strip()
            k = model.ZH2KEY[m.group("zh")]
            items.setdefault(k, [])
            if v:
                items[k].append((v, ZH2STATE[m.group("st")]))
            continue
        unknown.append(s)
    return items, unknown


def edits_vs(obj: dict, parsed: dict) -> list[dict]:
    """Item-level differences between the canonical object and the parsed user file (only recognised keys)."""
    out = []
    for k in model.KEYS:
        cur = [(v["value"], v["state"]) for v in obj["items"].get(k) or [] if v["state"] != "SUGGESTION"]
        new = parsed.get(k, [])
        if k not in parsed:
            continue   # line deleted entirely: treated as unrecognised, not as a deletion
        if cur != new:
            out.append({"key": k, "old": cur, "new": new})
    return out


def blocks_in(text: str) -> list[tuple[dict, str]]:
    return [(json.loads(m.group("j")), m.group("h")) for m in BLOCK_RE.finditer(text)]
