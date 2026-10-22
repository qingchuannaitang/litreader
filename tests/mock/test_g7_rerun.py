"""G7-2: 继续 only with a pending decision; after an error it becomes 「从失败处重跑」; per-figure vision cache."""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from litreader import events  # noqa: E402
from litreader.analysis import vision  # noqa: E402
from litreader.llm.config import ProviderConfig  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_continue_disabled_until_decision_then_rerun_after_error(app):
    from litreader.gui.flow import FlowPage
    f = FlowPage()
    f.start("精读zotero中的 gait")
    assert not f.next_btn.isEnabled() and f.next_btn.text() == "继续"
    f.show_decision({"id": "d1", "kind": "cost", "prompt": "是否继续？",
                     "options": [events.opt("y", "继续精读"), events.opt("n", "取消")]})
    assert f.next_btn.isEnabled()
    got = []
    f.rerun_requested.connect(got.append)
    f.tracker.state["parse"] = "done"                           # reusable results exist (G8-2)
    f.finished({"status": "error", "message": "all providers failed: ['KEY_MISSING']"})
    assert f.next_btn.isEnabled() and f.next_btn.text() == "从失败处重跑"
    f._continue()
    assert got == ["精读zotero中的 gait"]
    f.start("x")
    assert f.next_btn.text() == "继续" and not f.next_btn.isEnabled()
    f.finished({"status": "cancelled", "message": ""})
    assert not f.next_btn.isEnabled()


def test_vision_cache_reuses_ok_figures(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG fake")
    fig = {"id": "Fig 1", "caption": "图 1. x", "parts": [{"img_path": "a.png"}]}
    chain = [ProviderConfig("vision1", "openai_compatible", "https://example.invalid", "vm", "K", True)]
    calls = []

    def tx(url, headers, body, timeout):
        calls.append(1)
        return 200, json.dumps({"choices": [{"message": {"content": '{"finding": "红色", "numbers": []}'}}]}).encode()
    env = {"K": "k"}
    o1, i1 = vision.cached_observe(fig, tmp_path, chain, tx, env, tmp_path / "vc", "AVU1")
    o2, i2 = vision.cached_observe(fig, tmp_path, chain, tx, env, tmp_path / "vc", "AVU1")
    assert o1 == o2 and o1["finding"] == "红色" and len(calls) == 1 and i2.get("cached")
    (tmp_path / "a.png").write_bytes(b"\x89PNG changed")      # different image -> new key -> real call
    vision.cached_observe(fig, tmp_path, chain, tx, env, tmp_path / "vc", "AVU1")
    assert len(calls) == 2


def test_vision_cache_does_not_store_failures(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG fake")
    fig = {"id": "Fig 1", "caption": "", "parts": [{"img_path": "a.png"}]}
    chain = [ProviderConfig("vision1", "openai_compatible", "https://example.invalid", "vm", "K", True)]
    o, i = vision.cached_observe(fig, tmp_path, chain, lambda *a: (500, b""), {"K": "k"}, tmp_path / "vc", "X")
    assert o is None and not (tmp_path / "vc").exists()
