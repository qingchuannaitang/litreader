"""G7-3: 结果页 — 刚刚精读 card, 最近精读的笔记 (dedup, excludes the just-read paper, 5/page, selection), right drawer."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

from litreader.gui import note_html, runner  # noqa: E402

NOTE = """---
title: x
---
# 中文题名

*English*

> [!info] 论文信息
> **作者：** A

[查看附件首页](zotero://open-pdf/library/items/ATT1?page=1)

> [!abstract] 三分钟了解论文
> **最重要的结果（PAPER）：** 结果 [p3](zotero://open-pdf/library/items/ATT1?page=3)

> [!note] 阅读约定
> 不应出现
"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_preview_head_keeps_first_two_callouts():
    h = note_html.preview_head(NOTE)
    assert "论文信息" in h and "三分钟了解论文" in h and "阅读约定" not in h and "# 中文题名" in h and "title: x" not in h


def _receipt(d, i, item, title, status="DRY_RUN_COMPLETE", note=None):
    job = d / "jobs" / f"j{item}"
    job.mkdir(parents=True, exist_ok=True)
    r = {"status": status, "note": note, "query": "q", "finished": f"2026-10-{10 + i:02d}T10:00:00",
         "paper": {"item_key": item, "title_zh": title, "title_en": "EN " + title, "year": "2026"}}
    (job / f"receipt-2026-10-{10 + i:02d}T10-00-00.json").write_text(json.dumps(r, ensure_ascii=False), "utf-8")
    return r


def test_dedup_and_exclude():
    rows = [{"paper": {"item_key": "A"}, "n": 3}, {"paper": {"item_key": "B"}}, {"paper": {"item_key": "A"}, "n": 1}]
    out = runner.dedup_papers(rows)
    assert [r["paper"]["item_key"] for r in out] == ["A", "B"] and out[0]["n"] == 3
    assert [r["paper"]["item_key"] for r in runner.dedup_papers(rows, exclude="item:A")] == ["B"]


def test_result_page_list_drawer_and_keys(app, tmp_path):
    from types import SimpleNamespace
    from litreader.gui.result import ResultPage
    note = tmp_path / "n.md"
    note.write_text(NOTE, "utf-8")
    for i in range(13):                          # 12 other papers (+ a duplicate run of P3) + the just-read one
        _receipt(tmp_path, i, f"P{i}", f"论文{i}", note=str(note))
    _receipt(tmp_path, 14, "P3", "论文3 新", note=str(note))
    just = _receipt(tmp_path, 20, "JUST", "刚读的", note=str(note))
    opened = []
    pg = ResultPage(opener=opened.append)
    pg.resize(1100, 760)
    pg.load(just, cfg=SimpleNamespace(data_dir=tmp_path, vault_root=tmp_path, dry_run_root=tmp_path))
    L = pg.list
    titles = [(r.get("row") or {}).get("title") for r in L.items]
    assert "刚读的" not in titles and len(L.items) == 13 and titles.count("论文3 新") == 1 and "论文3" not in titles
    assert L.pages() == 3 and len(L.page_items()) == 5
    assert not pg.list_bar.obs_btn.isEnabled() and not pg.list_bar.seg.buttons["note"].isEnabled()  # nothing selected
    assert pg.top_bar.obs_btn.isEnabled()
    pg.list.page_by(1)
    assert L.page == 1
    pg._key_move(1)                                  # ↓ selects the first row
    assert L.current() is not None and pg.list_bar.obs_btn.isEnabled()
    pg._enter()                                      # Enter -> drawer with 笔记预览
    assert pg.drawer_open() and pg.tabs.current() == "note" and "论文信息" in pg.preview.toPlainText()
    first = L.current()
    pg._key_move(1)                                  # drawer follows the selection
    assert pg.target["paper"]["item_key"] == L.current()["paper"]["item_key"] != first["paper"]["item_key"]
    pg.tabs.buttons["usage"].click()
    assert pg.stack.currentIndex() == 2
    pg.drawer.full_link.click()
    assert opened and opened[-1].toString().startswith("obsidian://")
    pg.close_drawer()
    assert not pg.drawer_open()
    pg.top_bar.seg.buttons["evidence"].click()
    assert pg.drawer_open() and pg.stack.currentIndex() == 1 and pg.target is pg.r or pg.target.get("paper", {}).get("item_key") == "JUST"
