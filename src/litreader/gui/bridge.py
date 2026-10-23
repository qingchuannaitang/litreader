"""QThread worker <-> GUI. The pipeline runs in the worker thread with a BusUI; every bus event is re-emitted as a
Qt signal (queued onto the GUI thread). A decision_request blocks the worker on a concurrent.futures.Future that the
GUI resolves with answer(id, text) — text is exactly what the terminal user would type. cancel() makes every pending
and future decision answer "q" and stops the run at the next stage boundary (always before any note is written)."""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import Future, TimeoutError as FutTimeout
from typing import Callable

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from ..errors import LitError
from ..events import BusUI, Event, EventBus


class RunWorker(QObject):
    event = Signal(object)        # events.Event
    finished = Signal(object)     # {"status": ok/cancelled/error, "result"?, "message"?}

    def __init__(self, runner: Callable[[BusUI], dict]):
        super().__init__()
        self.runner = runner
        self.ui = BusUI(EventBus())
        self._pending: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._stage = None
        self.ui.bus.subscribe(self._forward)
        self.ui.bus.set_responder(self._respond)

    # ---- worker thread ----
    def _forward(self, ev: Event) -> None:
        if ev.type == "stage" and ev.get("status") == "start":
            self._stage = ev.get("stage")
        if ev.type == "decision_request":   # register the Future BEFORE the GUI can see (and answer) the request
            with self._lock:
                self._pending[ev["id"]] = Future()
        self.event.emit(ev)

    def _respond(self, ev: Event) -> str:
        if self.ui.cancel_requested.is_set():
            return "q"
        with self._lock:
            fut = self._pending.setdefault(ev["id"], Future())
        try:
            while True:
                try:
                    return fut.result(timeout=0.2)
                except FutTimeout:
                    if self.ui.cancel_requested.is_set():
                        return "q"
        finally:
            with self._lock:
                self._pending.pop(ev["id"], None)

    @Slot()
    def run(self) -> None:
        from ..realrun import Cancelled
        try:
            res = self.runner(self.ui)
            self.finished.emit({"status": "ok", "result": res})
        except Cancelled as e:
            self.ui.bus.emit("error", stage=self._stage, message=str(e), recoverable=True, cancelled=True)
            self.finished.emit({"status": "cancelled", "message": str(e)})
        except LitError as e:
            self.ui.bus.emit("error", stage=self._stage, message=str(e), recoverable=False)
            self.finished.emit({"status": "error", "message": str(e)})
        except Exception as e:  # noqa: BLE001 — never let the worker thread die silently
            msg = f"程序内部错误：{type(e).__name__}: {e}"
            self.ui.bus.emit("error", stage=self._stage, message=msg, recoverable=False,
                             detail=traceback.format_exc(limit=6))
            self.finished.emit({"status": "error", "message": msg})

    # ---- GUI thread ----
    def answer(self, rid: str, choice: str) -> bool:
        with self._lock:
            fut = self._pending.get(rid)
        if fut is None or fut.done():
            return False
        fut.set_result(choice)
        return True

    def pending(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def cancel(self) -> None:
        self.ui.cancel_requested.set()
        with self._lock:
            futs = list(self._pending.values())
        for f in futs:
            if not f.done():
                f.set_result("q")


def start(worker: RunWorker, parent: QObject | None = None) -> QThread:
    th = QThread(parent)
    worker.moveToThread(th)
    th.started.connect(worker.run)
    worker.finished.connect(th.quit, Qt.DirectConnection)   # QThread.quit is thread-safe; no GUI-loop round trip
    th._worker = worker   # keep the worker alive as long as its thread
    _gc_guard_enter()
    th.finished.connect(_gc_receiver().leave, Qt.QueuedConnection)   # runs on the GUI thread
    th.start()
    return th


# W2: Python's automatic garbage collection runs in whichever thread happens to allocate. If it runs inside the worker
# while a dead Qt widget sits in a reference cycle, Qt objects get destroyed off the GUI thread -> crash (seen on CI
# macOS, py3.11). While any worker runs, automatic gc is off and the GUI thread collects on a timer instead.
_gc_state = {"n": 0, "timer": None, "was_enabled": True}


def _gc_guard_enter() -> None:
    import gc
    from PySide6.QtCore import QTimer
    gc.collect()
    if _gc_state["n"] == 0:
        _gc_state["was_enabled"] = gc.isenabled()
        gc.disable()
        t = _gc_state["timer"]
        if t is None:
            t = _gc_state["timer"] = QTimer()
            t.setInterval(500)
            t.timeout.connect(gc.collect)
        t.start()
    _gc_state["n"] += 1


class _GcReceiver(QObject):
    @Slot()
    def leave(self) -> None:
        _gc_guard_leave()


def _gc_receiver() -> "_GcReceiver":
    r = _gc_state.get("receiver")
    if r is None:
        r = _gc_state["receiver"] = _GcReceiver()
    return r


def _gc_guard_leave() -> None:
    import gc
    _gc_state["n"] = max(0, _gc_state["n"] - 1)
    if _gc_state["n"] == 0:
        if _gc_state["timer"] is not None:
            _gc_state["timer"].stop()
        if _gc_state["was_enabled"]:
            gc.enable()
