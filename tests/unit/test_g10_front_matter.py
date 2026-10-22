"""G10-7: slim Chinese front matter + one nested litreader: block; old flat-English notes still read by 最近精读."""
from litreader.gui.runner import _front_matter, paper_row
from litreader.render.l2_note_v2 import _yaml, front_matter

MACHINE = {"note_type": "科研精读笔记", "schema": "portable-literature-note-v2", "parent_item_key": "K1",
           "attachment_key": "A1", "doi": "10.1/x", "title_zh": "中文题", "title_en": "Eng", "title": "中文题（Eng）",
           "authors": "Li 等", "year": "2025", "journal": "J", "topic": "步态", "read_date": "2026-10-22",
           "reading_level": "L2", "extraction_level": "E3", "source_version": "PDF 疑似中文译本……", "status": "待审阅",
           "figure_check": "X", "metadata_source": {"doi": "ZOTERO"}, "link_check": "UNVERIFIED", "project_id": None,
           "project_version": None, "project_relation": "高", "tags": ["文献精读", "步态"], "template_id": "main.general",
           "template_sha256": "abc", "template_modules": ["m@r1"], "study_type": "rct"}


def test_slim_front_matter():
    fm = front_matter(MACHINE)
    assert list(fm)[:10] == ["中文标题", "英文标题", "作者", "年份", "期刊", "DOI", "主题", "阅读日期", "状态", "课题相关度"]
    assert fm["tags"] == ["文献精读", "步态"] and fm["litreader"] == {
        "parent_item_key": "K1", "attachment_key": "A1", "schema": "portable-literature-note-v2", "template_id": "main.general"}
    y = _yaml(fm)
    for gone in ("title:", "source_version", "template_sha256", "metadata_source", "figure_check", "link_check",
                 "project_id", "reading_level", "extraction_level", "study_type", "note_type"):
        assert gone not in y
    assert "litreader:\n  parent_item_key: \"K1\"\n" in y
    assert front_matter(MACHINE, conflict=True)["作者"].startswith("UNKNOWN（作者顺序待核对")
    assert front_matter({**MACHINE, "project_relation": "LENS_FAILED"})["课题相关度"] == "未能评估"


def test_recent_list_reads_new_and_old_notes(tmp_path):
    new = tmp_path / "new.md"
    new.write_text(_yaml(front_matter(MACHINE)) + "# 中文题\n", "utf-8")
    old = tmp_path / "old.md"
    old.write_text('---\nnote_type: "科研精读笔记"\nparent_item_key: "K0"\ntitle_zh: "旧题"\ntitle_en: "Old"\n'
                   'authors: "Wang"\nyear: "2020"\njournal: "OJ"\n---\n# 旧题\n', "utf-8")
    n = _front_matter(str(new))
    assert n == {"title_zh": "中文题", "title_en": "Eng", "authors": "Li 等", "year": "2025", "journal": "J",
                 "parent_item_key": "K1"}
    o = _front_matter(str(old))
    assert o["title_zh"] == "旧题" and o["parent_item_key"] == "K0" and o["journal"] == "OJ"
    for p in (new, old):
        row = paper_row({"note": str(p), "status": "DRY_RUN_COMPLETE"})
        assert row  # renders without error for both formats
