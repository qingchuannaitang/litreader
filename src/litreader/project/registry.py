"""Project registry (design §2.1): canonical project versions in <app data>/projects/, same commit/lock/recovery
core as the template registry. Snapshot = {"records": [one per project VERSION], "prefs": {default_project,
first_question, prefer...}}. Every change = new immutable version object + new snapshot; nothing is overwritten."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ..errors import Stop
from ..store.core import Corrupt, Locked, Store, sha  # noqa: F401
from ..vault import naming
from . import model


class Ambiguous(Stop):
    def __init__(self, msg, matches):
        super().__init__(msg)
        self.matches = matches


class ProjectRegistry(Store):
    LABEL = "课题登记"
    CMD = "litreader project recover"
    EXT = ".json"

    def _empty(self) -> dict:
        return {"n": 0, "created": None, "records": [], "prefs": {"default_project": None, "first_question": None}}

    # ---------------------------------------------------------------- read
    def latest(self, snap: dict, pid: str) -> dict | None:
        recs = [r for r in snap["records"] if r["id"] == pid]
        return max(recs, key=lambda r: r["version"]) if recs else None

    def version_rec(self, snap: dict, pid: str, version: int) -> dict:
        r = next((r for r in snap["records"] if r["id"] == pid and r["version"] == version), None)
        if not r:
            raise Stop(f"课题 {pid} 没有版本 v{version}")
        return r

    def load(self, rec: dict) -> dict:
        obj = json.loads(self.object_bytes(rec["sha256"], f"课题 {rec['id']} v{rec['version']}"))
        if obj.get("project_id") != rec["id"] or obj.get("version") != rec["version"]:
            raise Corrupt(f"课题对象与登记不符（{rec['id']} v{rec['version']}），停止")
        return obj

    def projects(self, snap: dict, *, include_archived: bool = True) -> list[dict]:
        ids = list(dict.fromkeys(r["id"] for r in snap["records"]))   # creation order
        out = [self.latest(snap, i) for i in ids]
        return [r for r in out if include_archived or r["status"] == "ACTIVE"]

    def find(self, snap: dict, text: str, *, include_archived: bool = False) -> dict:
        text = (text or "").strip().strip("《》「」“”\"")
        pool = self.projects(snap, include_archived=include_archived)
        exact = [r for r in pool if text in (r["id"], r["folder"], r["title"])]
        sub = exact or [r for r in pool if text and (r["title"].startswith(text) or r["folder"].startswith(text)
                                                     or r["id"].startswith(text) or text in r["title"])]
        if len(sub) == 1:
            return sub[0]
        if not sub:
            raise Stop(f"没有找到课题「{text}」（litreader project list 查看全部）")
        raise Ambiguous(f"「{text}」对应多个课题", sub)

    # ---------------------------------------------------------------- write
    def _folder(self, snap: dict, title: str) -> str:
        s = naming.sanitize(title, max_bytes=60)
        base = (s.stem if s else "课题")[:20].rstrip(" —-.") or "课题"
        if base.startswith(("_", ".")):
            base = "课题" + base.lstrip("_.")
        taken = {r["folder"] for r in snap["records"]}
        name, i = base, 2
        while name in taken:
            name, i = f"{base}——{i}", i + 1
        return name

    def commit(self, obj: dict, op: str, summary: str, *, set_default: bool | None = None,
               prefs: dict | None = None) -> tuple[dict, dict]:
        """Commit a new version of obj (version/parent filled here). Returns (snapshot, record)."""
        model.check(obj)
        with self.lock(op):
            snap = self.snapshot()
            prev = self.latest(snap, obj["project_id"])
            new = copy.deepcopy(obj)
            new["version"] = (prev["version"] if prev else 0) + 1
            new["parent_sha"] = prev["sha256"] if prev else None
            new["created"] = model.now_iso()
            new["change"] = {"op": op, "summary": summary}
            b = model.canonical(new)
            rec = {"id": new["project_id"], "version": new["version"], "sha256": sha(b), "folder": new["folder"],
                   "title": model.title_of(new), "status": new["status"], "created": new["created"],
                   "op": op, "summary": summary}
            nsnap = {"records": snap["records"] + [rec], "prefs": {**snap["prefs"], **(prefs or {})}}
            if set_default:
                nsnap["prefs"]["default_project"] = new["project_id"]
            elif set_default is False and nsnap["prefs"].get("default_project") == new["project_id"]:
                nsnap["prefs"]["default_project"] = None
            snap2 = self._commit(nsnap, [{"op": op, "id": rec["id"], "version": rec["version"], "sha": rec["sha256"],
                                          "summary": summary}], [b])
        return snap2, rec

    def set_prefs(self, op: str, **prefs) -> dict:
        with self.lock(op):
            snap = self.snapshot()
            if prefs.get("default_project"):
                r = self.latest(snap, prefs["default_project"])
                if not r or r["status"] != "ACTIVE":
                    raise Stop("只能把未归档的课题设为默认")
            nsnap = {"records": snap["records"], "prefs": {**snap["prefs"], **prefs}}
            return self._commit(nsnap, [{"op": op, **{k: v for k, v in prefs.items()}}])

    def create(self, title: str, *, kind: str = "用户输入", make_default: bool | None = None) -> tuple[dict, dict]:
        snap = self.snapshot()
        pid = model.new_id()
        while self.latest(snap, pid):
            pid = model.new_id()
        obj = model.blank(pid, self._folder(snap, title))
        obj["items"]["working_title"] = [model.value(title, "CONFIRMED", kind, "用户确认")]
        if make_default is None:   # the only (active) project becomes the default
            make_default = not snap["prefs"].get("default_project")
        return self.commit(obj, "CREATE", f"新建课题（{kind}）：{title}", set_default=make_default,
                           prefs={"first_question": "answered"})

    def current_obj(self, snap: dict, pid: str) -> tuple[dict, dict]:
        rec = self.latest(snap, pid)
        if not rec:
            raise Stop(f"没有课题 {pid}")
        return rec, self.load(rec)


def rebuild(reg: "ProjectRegistry", versions: list[tuple[dict, str]]) -> dict:
    """`project recover --from-vault`: rebuild an EMPTY registry from 历史版本/ data blocks. Each block must hash to
    its recorded sha256 and the parent chain must be complete; any mismatch stops (never guesses)."""
    with reg.lock("REBUILD"):
        snap = reg.snapshot()
        if snap["records"]:
            raise Stop("课题登记不是空的；--from-vault 只用于登记丢失后的重建")
        by = {}
        for obj, h in versions:
            b = model.canonical(obj)
            if sha(b) != h:
                raise Stop(f"历史版本数据与记录的 SHA 不符（{obj.get('project_id')} v{obj.get('version')}），停止")
            model.check(obj)
            by.setdefault(obj["project_id"], {})[obj["version"]] = (obj, h, b)
        recs, blobs = [], []
        for pid, vs in by.items():
            prev = None
            for v in range(1, max(vs) + 1):
                if v not in vs:
                    raise Stop(f"课题 {pid} 缺少历史版本 v{v}，无法完整重建")
                obj, h, b = vs[v]
                if obj["parent_sha"] != prev:
                    raise Stop(f"课题 {pid} v{v} 的版本链不连续，停止")
                prev = h
                recs.append({"id": pid, "version": v, "sha256": h, "folder": obj["folder"], "title": model.title_of(obj),
                             "status": obj["status"], "created": obj["created"], "op": (obj.get("change") or {}).get("op"),
                             "summary": (obj.get("change") or {}).get("summary")})
                blobs.append(b)
        return reg._commit({"records": recs, "prefs": {**snap["prefs"], "first_question": "answered"}},
                           [{"op": "REBUILT_FROM_VAULT", "projects": sorted(by)}], blobs)


def registry_for(cfg) -> ProjectRegistry:
    return ProjectRegistry(Path(cfg.data_dir) / "projects")
