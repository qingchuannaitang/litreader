"""G12-4: a full fake run with NO 看图 station, on a paper whose figure 2 has no caption (presumed figure): the note is
written, every figure finding is labelled NO_VISION, the presumed figure gets a 「看原页」 style title, the flow shows
看图 as skipped. Zotero / MinerU / LLM are fakes; no network, no keys."""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))
import test_realrun as R  # noqa: E402

from litreader import events, realrun  # noqa: E402
from litreader.render.l2_note_v2 import NO_VISION, NO_VISION_TITLE  # noqa: E402
from litreader.zotero.client import ZoteroClient  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"0" * 64 + b"\xff\xd9"


def mineru_zip_with_figures():
    cl = [{"type": "text", "text": "Gait study title", "text_level": 1, "page_idx": 0, "bbox": [0, 0, 100, 10]},
          {"type": "text", "text": "共纳入 89 名老年人。", "page_idx": 0},
          {"type": "image", "img_path": "images/f1.jpg", "image_caption": ["图 1 | 研究流程。"], "bbox": [0, 100, 500, 400],
           "page_idx": 0},
          {"type": "text", "text": "结果显示步速下降。", "page_idx": 1},
          {"type": "image", "img_path": "images/u.jpg", "image_caption": [], "bbox": [0, 100, 500, 400], "page_idx": 1},
          {"type": "image", "img_path": "images/f3.jpg", "image_caption": ["图 3 | 步速对比。"], "bbox": [0, 100, 500, 400],
           "page_idx": 2}]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x_content_list.json", json.dumps(cl, ensure_ascii=False))
        z.writestr("layout.json", json.dumps({"pdf_info": [{}, {}, {}]}))
        for n in ("f1", "u", "f3"):
            z.writestr(f"images/{n}.jpg", JPG)
    return b.getvalue()


class FigMinerU(R.FakeMinerU):
    def req(self, method, url, token=None, json_body=None, timeout=120):
        st, body = super().req(method, url, token, json_body, timeout)
        return (st, mineru_zip_with_figures()) if url.endswith("r.zip") else (st, body)


class EventUI(R.ScriptUI):
    def __init__(self, answers):
        super().__init__(answers)
        self.events = []

    def emit(self, type, **data):
        self.events.append((type, data))


def test_full_run_without_vision(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    vault, pdf, cfg = R.setup_run(tmp_path, vision=False)
    assert "vision" not in cfg.llm.stations
    calls = []

    def tx(url, headers, body, timeout):
        calls.append(json.loads(body))
        return R.topic_llm("existing", "认知与步态")(url, headers, body, timeout)
    zt, _ = R.zot_fake(tmp_path / "Zotero" / "storage")
    ui, f = EventUI(["y", ""]), FigMinerU()
    r = realrun.run(cfg, "精读zotero中的Gait study title，并将精读笔记存入obsidian中", ui, zotero=ZoteroClient(zt),
                    llm_tx=tx, mineru_kwargs={"req": f.req, "put": f.put, "sleep": lambda s: None},
                    pages_fn=lambda p: 3, stats_fn=lambda p: {"pages": 3, "chars": 3000, "figures": 3, "source": ["fake"]})
    assert r["status"] == "DRY_RUN_COMPLETE", (r, ui.text)
    # no request ever carried an image
    assert not any(isinstance(m.get("content"), list) for c in calls for m in c["messages"])
    assert ("stage", {"stage": "vision", "status": "skip"}) in ui.events
    assert not any(t == "progress" and d.get("stage") == "vision" for t, d in ui.events)
    note = Path(r["note"]).read_text("utf-8")
    ev = next((vault / "litreader" / "论文库" / "_证据档案" / "AAAA1111").glob("*.md")).read_text("utf-8")
    assert "MINERU_CROPS_TEXT_ONLY_NO_VISION" in ev and "未经视觉模型看图" in note
    assert "视觉模型读图" not in note and "读图与原文不一致" not in note
    head = next(l for l in note.splitlines() if l.startswith("### 图2"))
    assert "推定" in head and head.endswith(NO_VISION_TITLE) and "看原页" in head and "这张图显示了什么" not in head, head
    if "**主要发现（PAPER" in note:
        assert NO_VISION in note
    # the GUI stepper fed the same events shows 看图 skipped
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from litreader.gui.flow import FlowPage, VISION_SKIPPED
    from test_g12_vision_optional_ui import _texts
    fp = FlowPage()
    fp.start("精读zotero中的Gait study title")
    for t, d in ui.events:
        if t in ("stage", "progress"):
            fp.on_event(events.Event(t, d))
    assert fp.nodes.state["vision"] == "skip"
    fp.view_step("reading")
    assert VISION_SKIPPED in " ".join(_texts(fp.detail))


kr = R.kr
