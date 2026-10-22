"""Publication state machine (R10)."""
from __future__ import annotations

from enum import Enum

from ..errors import InvalidTransition


class State(str, Enum):
    NEW = "NEW"
    CORE_PASS = "CORE_PASS"
    NOTE_CREATED = "NOTE_CREATED"
    ASSETS_VERIFIED = "ASSETS_VERIFIED"
    INDEX_UPDATED = "INDEX_UPDATED"
    INDEX_PENDING = "INDEX_PENDING"
    COMPLETE = "COMPLETE"


ALLOWED: dict[State, set[State]] = {
    State.NEW: {State.CORE_PASS},
    State.CORE_PASS: {State.NOTE_CREATED},
    State.NOTE_CREATED: {State.ASSETS_VERIFIED},
    State.ASSETS_VERIFIED: {State.INDEX_UPDATED, State.INDEX_PENDING},
    State.INDEX_PENDING: {State.INDEX_UPDATED, State.INDEX_PENDING},
    State.INDEX_UPDATED: {State.COMPLETE},
    State.COMPLETE: set(),
}


def check(cur: State, nxt: State) -> None:
    if nxt not in ALLOWED[cur]:
        raise InvalidTransition(f"{cur.value} -> {nxt.value} not allowed")
