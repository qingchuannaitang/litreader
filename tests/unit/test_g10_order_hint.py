from litreader.render.l2_note_v2 import order_hints


def test_methods_figures_before_results_get_hint():
    seq = [(False, 1, "F1"), (False, 8, "F8"), (False, 9, "F9"), (False, 2, "F2"), (False, 3, "F3"), (False, 7, "F7")]
    h = order_hints(seq)
    assert h == {"F8": "（先于图2出现）", "F9": "（先于图2出现）"}


def test_in_order_and_tables_separate():
    assert order_hints([(False, 1, "a"), (False, 2, "b"), (True, 1, "t1")]) == {}
    assert order_hints([(True, 3, "t3"), (False, 1, "f1"), (True, 1, "t1"), (False, 10 ** 6, "x")]) == {"t3": "（先于表1出现）"}
