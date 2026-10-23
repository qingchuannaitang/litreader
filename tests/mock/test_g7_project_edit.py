"""G7-8/G7-6: project fields edit inline (→ 已确认, new version); 批量填写 splits pasted text into 待确认 suggestions
via the (fake) model, which the user confirms one by one. Detail panes use the new typography helpers."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_projects import make_tx  # noqa: E402
from test_realrun import MemKeyring  # noqa: E402

from litreader import secrets  # noqa: E402
from litreader.gui import library as L  # noqa: E402

TEXT = "我的课题关注老年人。\n本研究的核心问题是步速能否预测跌倒。\n研究对象为 65 岁以上社区老年人。"
IMP = {"items": [
    {"key": "core_question", "value": "步速能否预测跌倒", "quote": "本研究的核心问题是步速能否预测跌倒。", "seg": "S2",
     "kind": "explicit", "role": "作者提出"},
    {"key": "population", "value": "65 岁以上社区老年人", "quote": "研究对象为 65 岁以上社区老年人。", "seg": "S3",
     "kind": "explicit", "role": "作者提出"}], "notes": []}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


def _item(cfg, pid, key):
    d = L.project_detail(cfg, pid)
    return [it for m in d["modules"] for it in m["items"] if it["key"] == key]


def test_soft_wrap_breaks_long_ids():
    from litreader.gui.library_page import soft_wrap
    s = soft_wrap("tpl_user_20261021_abcdefabcdefabcdefabcdefabcdef/x.md")
    assert "\u200b" in s and s.replace("\u200b", "") == "tpl_user_20261021_abcdefabcdefabcdefabcdefabcdef/x.md"


def test_inline_edit_and_bulk_fill_confirm(app, tmp_path, kr, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    from litreader.gui.library_page import BulkFillDialog, FieldRow, LibraryPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    gui_fakes.sample_project(cfg)
    page = LibraryPage(cfg)
    pt = page.projects
    pid = pt.rows[0]["id"]
    v0 = L.project_detail(cfg, pid)["version"]
    rows = pt.findChildren(FieldRow)
    assert rows
    r = next(r for r in rows if r.it["key"] == "population")
    r.start_edit()
    assert r.stack.currentIndex() == 1
    r.edit.setText("社区老年人（手动）")
    r.save()
    it = _item(cfg, pid, "population")
    assert any(x["value"] == "社区老年人（手动）" and x["state"] == "CONFIRMED" for x in it)
    assert L.project_detail(cfg, pid)["version"] == v0 + 1 and pt.status.text().startswith("✅ 已保存")

    seen = []
    pt.llm = lambda: (cfg.llm.chain("extract"), make_tx(seen, imp=IMP), None)
    dlg = BulkFillDialog(pt)
    assert not dlg.ok.isEnabled()
    dlg.text.setPlainText(TEXT)
    assert dlg.ok.isEnabled()
    dlg.run()
    assert dlg.result["added"] >= 1 and seen                           # the fake model was asked
    cq = [x for x in _item(cfg, pid, "core_question") if x["value"] == "步速能否预测跌倒"]
    assert cq and cq[0]["state"] == "PENDING"                          # suggestion only, never auto-confirmed
    row = next(r for r in pt.findChildren(FieldRow) if r.it["key"] == "core_question" and r.it["state"] == "PENDING")
    pt.decide(row.it, True)
    cq = [x for x in _item(cfg, pid, "core_question") if x["value"] == "步速能否预测跌倒"]
    assert cq[0]["state"] == "CONFIRMED"
    assert L.project_detail(cfg, pid)["version"] >= v0 + 3


def test_bulk_fill_empty_text_rejected(tmp_path, kr):
    cfg, _, _ = gui_fakes.environment(tmp_path)
    gui_fakes.sample_project(cfg)
    pid = gui_fakes.sample_project(cfg) if False else None
    from litreader.gui.library_page import LibraryPage  # noqa: F401
    pid = L.project_rows(cfg)["rows"][0]["id"] if isinstance(L.project_rows(cfg), dict) else L.project_rows(cfg)[0]["id"]
    with pytest.raises(ValueError):
        L.bulk_fill(cfg, pid, "   ", chain=[], transport=None, env=None)
