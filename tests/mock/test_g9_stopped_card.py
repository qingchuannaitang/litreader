"""G9-2: after a failure/cancel, the step that was running must not keep saying 「正在进行…」."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _detail(f):
    out = []
    for i in range(f.detail.count()):
        w = f.detail.itemAt(i).widget()
        if isinstance(w, QLabel):
            out.append(w.text())
    return " ".join(out)


def test_running_card_before_failure(app):
    from litreader.gui.flow import FlowPage
    f = FlowPage()
    f.start("精读zotero中的 abc")
    f.tracker._activate("select")
    f._render_detail()
    assert "正在进行" in _detail(f)


@pytest.mark.parametrize("status,word", [("error", "已停止"), ("cancelled", "已取消")])
def test_select_card_after_stop(app, status, word):
    from litreader.gui.flow import FlowPage
    f = FlowPage()
    f.start("精读zotero中的 abc")
    f.tracker._activate("select")
    f.finished({"status": status, "message": "x"})
    f.view_step("select")
    assert "正在进行" not in _detail(f) and word in _detail(f)
    assert word in f.detail_title.text()


def test_last_card_after_late_failure(app):
    from litreader.gui.flow import FlowPage
    f = FlowPage()
    f.start("精读zotero中的 abc")
    f.tracker._activate("done")
    f.finished({"status": "error", "message": "KeyError: 'field'"})
    f.view_step("done")
    assert "正在进行" not in _detail(f) and "已停止" in f.detail_title.text()
