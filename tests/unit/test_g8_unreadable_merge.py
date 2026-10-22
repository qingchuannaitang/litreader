from litreader.render.l2_note_v2 import unreadable_symbols, MATH_NOTICE, UNREADABLE


def test_several_markers_become_one_notice_with_page_link():
    md = "[原图p5](zotero://open-pdf/library/items/X?page=5)\n> 图注：角度 \ufffd 与 \ufffd 的关系，\ufffd 为增益"
    out, n = unreadable_symbols(md)
    last = out.split("\n")[1]
    assert n == 3 and UNREADABLE not in last and last.count(MATH_NOTICE) == 1 and "page=5" in last


def test_single_marker_is_kept():
    out, _ = unreadable_symbols("角度 \ufffd 变化")
    assert out == f"角度 {UNREADABLE} 变化"
