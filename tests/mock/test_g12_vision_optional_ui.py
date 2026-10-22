"""G12-1: 看图 is optional — the models page says so and the flow card shows 「已跳过（未配置看图模型）」."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _texts(layout):
    out = []
    for i in range(layout.count()):
        it = layout.itemAt(i)
        if it.widget() is not None and isinstance(it.widget(), QLabel):
            out.append(it.widget().text())
        elif it.layout() is not None:
            out += _texts(it.layout())
    return out


def test_flow_reading_card_shows_vision_skipped(app):
    from litreader.gui.flow import VISION_SKIPPED, FlowPage
    assert VISION_SKIPPED == "已跳过（未配置看图模型）"
    f = FlowPage()
    f.start("精读zotero中的 abc")
    f.tracker._activate("reading")
    f.nodes.state["vision"] = "skip"
    f.view_step("reading")
    assert VISION_SKIPPED in " ".join(_texts(f.detail))


def test_models_page_vision_tab_says_optional(app, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import gui_fakes
    cfg, _, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.models_page import VISION_OPTIONAL, ModelsPage
    p = ModelsPage(cfg, transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    assert p.vision_optional.text() == VISION_OPTIONAL and VISION_OPTIONAL.startswith("可选：留空则跳过看图")
