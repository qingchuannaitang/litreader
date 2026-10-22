"""Unit layer: cross-platform filename sanitising and collision candidates."""
import pytest

from litreader.errors import Stop
from litreader.vault.naming import MAX_BYTES, candidates, choose, sanitize


@pytest.mark.parametrize("raw,want", [
    ("轻度认知障碍：一项横断面研究", "轻度认知障碍——一项横断面研究"),
    ("A: B", "A——B"),
    ('a<b>c"d/e\\f|g?h*i', "a〈b〉c“d／e＼f｜g？h＊i"),
    ("标题。. . ", "标题。"),
    ("  多  空格\t标题 ", "多 空格 标题"),
    ("CON", "CON_"), ("lpt3", "lpt3_"), ("nul.txt", "nul.txt_"),
    ("ab\x00c\x1fd", "abcd"),
])
def test_sanitize(raw, want):
    assert sanitize(raw).stem == want


def test_unknown_and_empty():
    assert sanitize("") is None and sanitize("UNKNOWN") is None and sanitize(" . ") is None


def test_length_limit_at_char_boundary():
    s = sanitize("很长的标题" * 40)
    assert s.truncated and len(s.stem.encode()) <= MAX_BYTES and s.stem.startswith("很长的标题")


def test_candidates_and_choose():
    assert candidates("标题", "Zhong", "2021", "K1") == ["标题", "标题——Zhong2021", "标题——Zhong2021K1"]
    assert candidates("标题", None, None, "K1") == ["标题", "标题——K1"]
    assert candidates("UNKNOWN", "Zhong", "2021", "K1") == ["K1"]
    taken = {"标题", "标题——Zhong2021"}
    assert choose("标题", "Zhong", "2021", "K1", taken.__contains__) == "标题——Zhong2021K1"
    with pytest.raises(Stop):
        choose("标题", "Zhong", "2021", "K1", lambda c: True)


def test_collision_suffix_is_family_name_plus_year():
    from litreader.vault.naming import family_name
    assert candidates("标题", "Soyong Shin", "2026", "K1") == ["标题", "标题——Shin2026", "标题——Shin2026K1"]
    assert candidates("标题", "Hanz Cuevas Velasquez", "2026", "K1", family="Cuevas Velasquez")[1] == "标题——Cuevas Velasquez2026"
    assert candidates("标题", "王鸿涛", "2026", "K1")[1:] == ["标题——王鸿涛2026", "标题——王鸿涛2026K1"]   # CJK: full name
    assert candidates("标题", "王 鸿涛", "2026", "K1", family="王")[1] == "标题——王鸿涛2026"
    assert candidates("标题", None, "2026", "K1") == ["标题", "标题——2026", "标题——2026K1"]
    assert candidates("标题", "Soyong Shin", None, "K1")[1] == "标题——Shin"
    assert family_name("Shin, Soyong") == "Shin" and family_name("Martin Luther King Jr.") == "King"
    taken = {"标题", "标题——Shin2026"}
    assert choose("标题", "Soyong Shin", "2026", "K1", taken.__contains__) == "标题——Shin2026K1"


def test_zotero_cjk_creator_is_family_name_first_and_used_whole():
    from litreader.realrun import family_of
    from litreader.zotero.metadata import from_item
    zm = from_item({"key": "P", "data": {"creators": [
        {"creatorType": "author", "firstName": "鸿涛", "lastName": "王"},
        {"creatorType": "author", "firstName": "Soyong", "lastName": "Shin"}]}})
    assert zm["authors_full"] == ["王鸿涛", "Soyong Shin"]
    assert candidates("题", zm["authors_full"][0], "2026", "K", family_of(zm, zm["authors_full"][0]))[1] == "题——王鸿涛2026"
    assert candidates("题", "Soyong Shin", "2026", "K", family_of(zm, "Soyong Shin"))[1] == "题——Shin2026"
