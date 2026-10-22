"""G8-2: a failure while choosing the paper (nothing reusable yet) offers 「修改指令」 -> home with the text prefilled."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_gui import kr  # noqa: E402,F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_flow_edit_mode(app):
    from litreader.gui.flow import FlowPage
    f = FlowPage()
    f.start("精读zotero中的 《不存在》")
    edits, reruns = [], []
    f.edit_requested.connect(edits.append)
    f.rerun_requested.connect(reruns.append)
    f.finished({"status": "error", "message": "Zotero 中没有找到…"})
    assert f.next_btn.text() == "修改指令" and f.next_btn.isEnabled()
    f._continue()
    assert edits == ["精读zotero中的 《不存在》"] and reruns == []


def test_window_edit_goes_home_prefilled(app, tmp_path, kr):
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.flow.start("精读zotero中的 abc")
    win.flow.finished({"status": "error", "message": "没有找到"})
    win.flow._continue()
    assert win.stack.currentWidget() is win.home and win.home.input.text() == "精读zotero中的 abc"
    win.close()
