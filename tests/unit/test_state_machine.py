import pytest

from litreader.errors import InvalidTransition
from litreader.publish.state_machine import ALLOWED, State, check

ORDER = [State.NEW, State.CORE_PASS, State.NOTE_CREATED, State.ASSETS_VERIFIED, State.INDEX_UPDATED, State.COMPLETE]


def test_happy_path():
    for a, b in zip(ORDER, ORDER[1:]):
        check(a, b)


def test_pending_recovery_path():
    check(State.ASSETS_VERIFIED, State.INDEX_PENDING)
    check(State.INDEX_PENDING, State.INDEX_UPDATED)


@pytest.mark.parametrize("a,b", [(State.NEW, State.COMPLETE), (State.CORE_PASS, State.INDEX_UPDATED),
                                 (State.NOTE_CREATED, State.COMPLETE), (State.COMPLETE, State.CORE_PASS),
                                 (State.INDEX_PENDING, State.COMPLETE), (State.INDEX_PENDING, State.CORE_PASS)])
def test_illegal(a, b):
    with pytest.raises(InvalidTransition):
        check(a, b)


def test_complete_is_terminal():
    assert ALLOWED[State.COMPLETE] == set()
