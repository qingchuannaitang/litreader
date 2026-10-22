import pytest

from litreader.errors import ProtectedZoneError
from litreader.render.protected_zone import BEGIN, END, carry_over, empty_zone, extract, machine_sha


def test_carry_over_byte_identical():
    old = f"A\n{BEGIN}\n我的手写批注 ✍️\n  缩进保留\n{END}\nB"
    new = f"NEW\n{empty_zone()}\nNEW2"
    assert extract(carry_over(old, new)) == extract(old)


@pytest.mark.parametrize("bad", ["no markers", f"{BEGIN}{BEGIN}{END}", f"{END}x{BEGIN}", f"{BEGIN} only"])
def test_malformed_stops(bad):
    with pytest.raises(ProtectedZoneError):
        extract(bad)


def test_machine_sha_ignores_zone_body():
    a = f"X\n{BEGIN}\n\n{END}\nY"
    b = f"X\n{BEGIN}\n用户写了东西\n{END}\nY"
    assert machine_sha(a) == machine_sha(b)
    assert machine_sha(a) != machine_sha(a.replace("X", "Z"))
