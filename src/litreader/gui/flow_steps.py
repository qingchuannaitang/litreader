"""精读流程 9 步 ↔ event-bus stages / decision kinds (G6). Qt-free so the mapping is unit-tested.

The pipeline only moves forward; a step is todo → active → done, or skipped (e.g. no project, no author conflict).
「上一步」in the GUI only re-shows an earlier step's details; it never rewinds the run."""
from __future__ import annotations

STEPS = [("select", "选择论文"), ("project", "关联课题"), ("estimate", "费用估算"), ("parse", "解析 E0–E3"),
         ("template", "类型与模板"), ("reading", "精读进度"), ("author", "作者冲突"), ("topic", "主题文件夹"),
         ("done", "完成")]
KEYS = [k for k, _ in STEPS]
STAGE_STEP = {"zotero": "select", "project": "project", "estimate": "estimate", "parse": "parse", "template": "template",
              "vision": "reading", "writer": "reading", "judge": "reading", "lens": "reading", "author": "author",
              "topic": "topic", "write": "done"}
KIND_STEP = {"candidate": "select", "pdf": "select", "consent": "select", "project": "project", "cost": "estimate",
             "template": "template", "modules": "template", "author": "author", "topic_folder": "topic"}
# steps that may legitimately not happen in a run
OPTIONAL = {"project", "author"}


def step_of(stage: str | None = None, kind: str | None = None) -> str | None:
    return KIND_STEP.get(kind) if kind else STAGE_STEP.get(stage)


class Tracker:
    """Feed it events (type + payload dict); read .state[key] ∈ todo/active/done/skip, .current, .data[key]."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.state = {k: "todo" for k in KEYS}
        self.data: dict[str, dict] = {k: {} for k in KEYS}
        self.current = None

    def _activate(self, key: str):
        i = KEYS.index(key)
        for k in KEYS[:i]:           # everything before the active step is finished or did not apply
            if self.state[k] in ("todo", "active"):
                self.state[k] = "skip" if (k in OPTIONAL and self.state[k] == "todo") else "done"
        if self.state[key] != "done":
            self.state[key] = "active"
        self.current = key

    def feed(self, type_: str, ev: dict) -> str | None:
        """Returns the step key the event belongs to (or None)."""
        if type_ == "stage":
            name = ev.get("stage")
            key = step_of(stage=name)
            if not key:
                return None
            st = ev.get("status", "start")
            payload = {k: v for k, v in ev.items() if k not in ("stage", "status")}
            if payload:
                self.data[key].setdefault(name, {}).update(payload)
            if st == "skip":
                if self.state[key] != "done":
                    self.state[key] = "skip"
                return key
            self._activate(key)
            if st == "done" and key not in ("reading",):
                self.state[key] = "done"
            elif st == "done" and name == "lens":
                self.state[key] = "done"
            return key
        if type_ == "decision_request":
            key = step_of(kind=ev.get("kind"))
            if key:
                self._activate(key)
                self.data[key]["decision"] = {"kind": ev.get("kind"), "data": ev.get("data") or {}}
            return key
        if type_ == "progress":
            key = step_of(stage=ev.get("stage"))
            if key:
                self.data[key].setdefault("progress", {})[ev.get("stage")] = dict(ev)
            return key
        if type_ == "done":
            for k in KEYS:
                if self.state[k] in ("todo", "active"):
                    self.state[k] = "skip" if (k in OPTIONAL and self.state[k] == "todo") else "done"
            self.state["done"] = "done"
            self.current = "done"
            return "done"
        return None

    def index(self) -> int:
        return KEYS.index(self.current) if self.current else 0
