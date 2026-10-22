"""G8-9/10: red dot + notice bar, skip/later, about card, popover, QQ copy, 更多设置… jump."""
import json
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

LATEST = {"version": "9.9.0", "notes": "新功能", "download_url": "https://example.com/l.zip", "qq_group": "7654321"}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


WINS = []


@pytest.fixture(autouse=True)
def _cleanup(app):
    yield
    while WINS:
        w = WINS.pop()
        if w.popover:
            w.popover.deleteLater()
        w.close()
        w.deleteLater()
    from PySide6.QtCore import QEvent
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def make(tmp_path, getter):
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    w = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata", update_getter=getter, check_updates=False)
    WINS.append(w)
    return w


def test_newer_version_shows_dot_bar_and_qq_override(app, tmp_path, kr):
    win = make(tmp_path, lambda u, t: json.dumps(LATEST).encode())
    win.updates.prefs.set("update_urls", ["https://test.example/latest.json"])
    assert win.update_dot.isHidden() and win.update_bar.isHidden()
    assert win.settings.about.qq.text() == "1126184965"
    assert win.updates.auto_check(sync=True)
    app.processEvents()
    assert not win.update_dot.isHidden() and not win.update_bar.isHidden()
    assert "9.9.0" in win.update_bar.text.text() and win.settings.about.qq.text() == "7654321"
    assert not win.updates.auto_check(sync=True)          # once per day
    win.updates.skip()
    assert win.update_bar.isHidden() and win.updates.prefs.get("skipped_version") == "9.9.0"
    win.settings.about.copy_btn.click()
    assert QApplication.clipboard().text() == "7654321"
    win.show_feedback()
    assert win.popover.isVisible() and win.popover.view_btn.isVisibleTo(win.popover)
    win.popover.more_btn.click()
    assert win.stack.currentWidget() is win.settings and not win.popover.isVisible()


def test_network_failure_is_silent(app, tmp_path, kr):
    def boom(u, t):
        raise OSError("offline")
    win = make(tmp_path, boom)
    win.updates.prefs.set("update_urls", ["https://test.example/latest.json"])
    win.updates.auto_check(sync=True)
    app.processEvents()
    assert win.update_bar.isHidden() and win.update_dot.isHidden() and win.updates.status == "idle"
    win.updates.check(manual=True, sync=True)
    app.processEvents()
    assert win.updates.status == "failed" and "网络" in win.settings.about.state.text()


def test_later_snoozes(app, tmp_path, kr):
    win = make(tmp_path, lambda u, t: json.dumps(LATEST).encode())
    win.updates.prefs.set("update_urls", ["https://test.example/latest.json"])
    win.updates.check(manual=True, sync=True)
    app.processEvents()
    win.updates.later()
    assert win.update_bar.isHidden() and win.updates.prefs.get("remind_after")
    assert not win.update_dot.isHidden()   # dot stays: a newer version exists
