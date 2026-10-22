"""G7-14: no 试运行 / PREVIEW_ONLY / 独立候选样稿 markers anywhere in the GUI or in the written note — while the write
location (the _litreader_试运行 folder) and the production-write guard are unchanged."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_gui import TEXT, answer_like_user, kr, spin  # noqa: E402,F401

MARKERS = ("试运行", "PREVIEW_ONLY", "独立候选样稿", "候选样稿", "测试文件夹", "正式写入已锁定")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _texts(w):
    out = [x.text() for x in w.findChildren(QLabel)] + [x.text() for x in w.findChildren(QAbstractButton)]
    out += [x.toolTip() for x in w.findChildren(QLabel)] + [w.windowTitle()]
    return [t.replace("_litreader_试运行", "") for t in out if t]     # the folder NAME itself may appear in paths


def test_no_trial_markers_in_gui_or_note(app, tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.show()
    for t in _texts(win):
        assert not any(m in t for m in MARKERS), t
    win.home.input.setText(TEXT)
    win.home._submit()
    kinds = []
    spin(app, lambda: (answer_like_user(win, kinds), not win.running and win.last_result is not None)[1], 30)
    rc = win.last_result
    assert cfg.dry_run_root in Path(rc["note"]).parents                     # write location unchanged
    for t in _texts(win) + [win.flow.log.toPlainText().replace("_litreader_试运行", "")]:
        assert not any(m in t for m in MARKERS), t[:200]
    md = Path(rc["note"]).read_text("utf-8")
    assert not any(m in md for m in ("PREVIEW_ONLY", "独立候选样稿", "阅读版候选", "publication_status"))
    win.close()
