"""G7-10/11: 篇数 dropdown (sequential queue of single runs, one confirm up front, summed actual cost at the end),
Zotero 只读 as a lock label with tooltip, no 只写试运行 chip; 最近精读 fills the height, rows/page follow it, n/m pager,
one row per paper."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_gui import TEXT, answer_like_user, kr, spin  # noqa: E402,F401

from litreader.gui import home as H  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_split_and_fit():
    assert H.split_batch("a\n\n b \nc\nd", 3) == ["a", "b", "c"]
    assert H.split_batch(" one ", 1) == ["one"]
    assert H.rows_fit(64 * 7 + 10) == 7 and H.rows_fit(5) == 1


def test_home_chips_and_lock(app):
    hp = H.HomePage()
    texts = [w.text() for w in hp.findChildren(QLabel)]
    assert "只写试运行文件夹" not in texts and "一次一篇" not in texts
    assert hp.lock.toolTip() == H.ZOTERO_RO_TIP and "Zotero 只读" in texts
    assert [hp.count.itemData(i) for i in range(hp.count.count())] == [1, 2, 3, 5, 10]
    got = []
    hp.batch.connect(got.append)
    hp.count.setCurrentIndex(1)
    hp.input.setText("精读 A\n精读 B\n精读 C")
    hp._submit()
    assert got == [["精读 A", "精读 B"]]
    assert not hp.findChildren(QScrollArea)                     # no vertical scroll on the home page


def _rows(n):
    return [{"note": f"/n/{i}.md", "paper": {"item_key": f"K{i}", "title_zh": f"中文{i}"}, "row": {"title": f"中文{i}"},
             "status_code": "DRY_RUN_COMPLETE"} for i in range(n)]


def test_recent_fills_height_and_pages(app):
    hp = H.HomePage()
    hp.resize(1100, 900)
    hp.show()
    app.processEvents()
    hp.set_recent(_rows(23))
    hp.fit_rows()
    big = hp.recent.per_page
    hp.resize(1100, 700)
    app.processEvents()
    hp.fit_rows()
    small = hp.recent.per_page
    assert big > small >= 1
    pg = hp.recent.pages()
    assert pg == -(-23 // small) and hp.recent._plabel.text() == f"1 / {pg}"
    hp.recent.page_by(1)
    assert hp.recent._plabel.text() == f"2 / {pg}"
    hp.close()


def test_one_row_per_paper(app, tmp_path):
    from litreader.gui import runner
    rows = _rows(3) + [dict(_rows(1)[0], note="/n/older.md")]
    assert len(runner.dedup_papers(rows)) == 3


def test_batch_queue_runs_sequentially(app, tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.show()
    starts = []
    real = win.start_run
    win.start_run = lambda t: (starts.append(t), real(t))
    assert win.start_batch([TEXT, TEXT], confirm=lambda: True)
    kinds = []
    spin(app, lambda: (answer_like_user(win, kinds), win.batch_info is None and not win.running)[1], 60)
    assert len(starts) == 2                                     # second started only after the first finished
    log = win.flow.log.toPlainText()
    assert "批量精读结束" in log and "合计实际费用" in log
    assert not win.start_batch([TEXT, TEXT], confirm=lambda: False) and win.batch_info is None
    win.close()
