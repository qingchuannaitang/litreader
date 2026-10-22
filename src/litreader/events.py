"""Event bus shared by the CLI and the GUI (design: docs/design/UI_PROTOTYPE.md §5).

The pipeline talks to a front end only through events:

  stage              {stage, status: start/done/skip, ...optional details for the GUI step cards}
  progress           {stage, done, total, tokens_in?, tokens_out?}
  log                {level: info/warn/error, text}
  decision_request   {id, kind, prompt, options: [{key, label, detail}], default, allow_custom, data?}
  decision_response  {id, choice}
  done               {note_path, evidence_path, receipt_path, usage}
  error              {stage, message, recoverable}

A decision's answer is always the exact text the CLI user would have typed (an option key such as "2", "a", "y",
"" for Enter, or a custom name), so every validation loop in the pipeline stays the single source of truth and the CLI
adapter reproduces the old terminal behaviour byte for byte: it prints `log` text and calls input() with the prompt.

`BusUI` keeps the old `say` / `ask` interface, so older callers (and test doubles that only have say/ask) still work;
the module-level helpers `stage` / `progress` / `decide` / `emit` degrade to plain say/ask on such objects.
"""
from __future__ import annotations

import itertools
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

EVENT_TYPES = ("stage", "progress", "log", "decision_request", "decision_response", "done", "error")
STAGES = ("zotero", "project", "estimate", "parse", "template", "vision", "writer", "judge", "lens", "author", "topic",
          "write")
KINDS = ("candidate", "pdf", "consent", "cost", "template", "modules", "author", "topic_folder", "confirm",
         "project", "text")


@dataclass
class Event:
    type: str
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)


class EventBus:
    """Synchronous fan-out. Exactly one responder answers decision requests (the CLI's input(), or the GUI's Future)."""

    def __init__(self):
        self._subs: list[Callable[[Event], None]] = []
        self._responder: Callable[[Event], str] | None = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn) if fn in self._subs else None

    def set_responder(self, fn: Callable[[Event], str] | None) -> None:
        self._responder = fn

    def emit(self, type: str, **data) -> Event:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        ev = Event(type, data)
        for fn in list(self._subs):
            fn(ev)
        return ev

    def request(self, kind: str, prompt: str, options: list[dict] | None = None, default: str | None = None,
                allow_custom: bool = False, data: dict | None = None) -> str:
        if self._responder is None:
            raise RuntimeError("no responder attached to the event bus")
        with self._lock:
            rid = f"d{next(self._ids)}"
        ev = self.emit("decision_request", id=rid, kind=kind, prompt=prompt, options=list(options or []),
                       default=default, allow_custom=allow_custom, data=data or {})
        choice = self._responder(ev)
        choice = "" if choice is None else str(choice)
        self.emit("decision_response", id=rid, choice=choice)
        return choice


def level_of(text: str) -> str:
    t = text.lstrip()
    if t.startswith(("⛔", "❌")):
        return "error"
    if t.startswith(("⚠", "⏹")):
        return "warn"
    return "info"


YN_RE = re.compile(r"\(y/n\)\s*[:：]?\s*$")


def infer_options(prompt: str) -> list[dict]:
    """Buttons for a free-form prompt the pipeline did not describe (project import dialogs etc.)."""
    if YN_RE.search(prompt):
        return [opt("y", "是"), opt("n", "否")]
    return []


def opt(key: str, label: str, detail: str = "") -> dict:
    return {"key": key, "label": label, "detail": detail}


class Cancelled(Exception):
    """Raised inside the worker when the front end asked to stop (converted to realrun.Cancelled by callers)."""


class BusUI:
    """The pipeline-facing object. `say` -> log event, `ask` -> generic decision; plus structured helpers."""

    def __init__(self, bus: EventBus | None = None):
        self.bus = bus or EventBus()
        self.cancel_requested = threading.Event()

    # --- old interface ---
    def say(self, msg: str) -> None:
        self.bus.emit("log", level=level_of(str(msg)), text=str(msg))

    def ask(self, prompt: str) -> str:
        return self.bus.request("text", prompt, infer_options(prompt), allow_custom=True)

    # --- structured ---
    def decide(self, kind: str, prompt: str, options: list[dict] | None = None, default: str | None = None,
               allow_custom: bool = False, data: dict | None = None) -> str:
        if type(self).ask is not BusUI.ask or getattr(self, "bus", None) is None:
            return self.ask(prompt)   # a subclass that answers through its own ask() keeps doing so
        return self.bus.request(kind, prompt, options, default, allow_custom, data)

    def emit(self, type: str, **data) -> None:
        bus = getattr(self, "bus", None)
        if bus is not None:
            bus.emit(type, **data)


# ---------------------------------------------------------------- helpers usable with ANY ui (say/ask only is fine)
def emit(ui, type: str, **data) -> None:
    f = getattr(ui, "emit", None)
    if callable(f):
        f(type, **data)


def stage(ui, name: str, status: str = "start", **data) -> None:
    """Stage marker. Also the cooperative cancel point: a GUI 'cancel' takes effect at the next stage start (always
    before the write stage begins, so a cancelled run never leaves a half-written note)."""
    if status == "start":
        ev = getattr(ui, "cancel_requested", None)
        if ev is not None and ev.is_set():
            from .realrun import Cancelled as RunCancelled
            raise RunCancelled("已取消（你在界面上点了取消）：未写入任何笔记；已解析的结果保留在缓存")
    emit(ui, "stage", stage=name, status=status, **data)


def progress(ui, name: str, done: int, total: int, **extra) -> None:
    emit(ui, "progress", stage=name, done=done, total=total, **extra)


def decide(ui, kind: str, prompt: str, options: list[dict] | None = None, default: str | None = None,
           allow_custom: bool = False, data: dict | None = None) -> str:
    f = getattr(ui, "decide", None)
    if callable(f):
        return f(kind, prompt, options, default, allow_custom, data)
    return ui.ask(prompt)


# ---------------------------------------------------------------- CLI adapter
class CliAdapter:
    """Terminal front end: prints `log` text, answers decisions with input(prompt). Nothing else is printed, so the
    terminal looks exactly as before the event bus existed (stage/progress/done are silent; done is printed by
    run_command, errors by main())."""

    def __init__(self, out: Callable[[str], Any] | None = None, inp: Callable[[str], str] | None = None):
        self.out = out or (lambda m: print(m, flush=True))
        self.inp = inp or input

    def attach(self, bus: EventBus) -> "CliAdapter":
        bus.subscribe(self.on_event)
        bus.set_responder(self.respond)
        return self

    def on_event(self, ev: Event) -> None:
        if ev.type == "log":
            self.out(ev["text"])

    def respond(self, ev: Event) -> str:
        try:
            return self.inp(ev["prompt"])
        except EOFError:
            return "q"
