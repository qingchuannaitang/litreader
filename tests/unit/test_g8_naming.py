"""G8-3: all three filename candidates taken -> （YYYY-MM-DD）, then （YYYY-MM-DD）（2）…; Chinese error at the end."""
import pytest

from litreader.errors import Stop
from litreader.vault import naming


def test_dated_then_numbered_suffix():
    taken = {"题名", "题名——Shin2026", "题名——Shin2026K1"}
    c = naming.choose("题名", "Soyong Shin", "2026", "K1", taken=taken.__contains__, today="2026-10-21")
    assert c == "题名——Shin2026K1（2026-10-21）"
    taken.add(c)
    assert naming.choose("题名", "Soyong Shin", "2026", "K1", taken=taken.__contains__, today="2026-10-21") \
        == "题名——Shin2026K1（2026-10-21）（2）"
    taken.add("题名——Shin2026K1（2026-10-21）（2）")
    assert naming.choose("题名", "Soyong Shin", "2026", "K1", taken=taken.__contains__,
                         today="2026-10-21").endswith("（3）")


def test_all_taken_chinese_error():
    with pytest.raises(Stop) as e:
        naming.choose("题名", None, None, "K1", taken=lambda c: True, today="2026-10-21")
    assert "同名文件太多" in str(e.value) and "未覆盖" in str(e.value)
