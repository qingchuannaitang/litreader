"""Page coverage rules for the extraction level (full-page figures, tables, equations, captions, references, title
pages, back matter, header-only/blank pages), the stop/continue thresholds, UNKNOWN pages in the evidence file,
MinerU cache reuse after a stop, and `litreader inspect-parse` (counts only, no content)."""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from litreader import cli, realrun  # noqa: E402
from litreader.errors import Stop  # noqa: E402
from litreader.parse import mineru  # noqa: E402
from litreader.parse.extraction_level import assess, page_kinds  # noqa: E402
from litreader.zotero.client import ZoteroClient  # noqa: E402
from test_realrun import FakeMinerU, STATS, ScriptUI, setup_run, topic_llm, zot_fake, kr  # noqa: E402,F401

SECRET = "共纳入 89 名老年人"   # body text that must never be printed by inspect-parse


def T(p, text, level=None):
    d = {"type": "text", "text": text, "page_idx": p - 1}
    if level:
        d["text_level"] = level
    return d


def paper(blank_page=12, core_blank=None):
    """12 pages, one of each kind."""
    cl = [T(1, "Gait study title", 1), T(1, "Introduction text."),
          T(2, "Methods", 1), T(2, SECRET + "。"),
          T(3, "Participants walked 10 m."),
          T(4, "Results", 1), T(4, "结果显示步速下降。"),
          {"type": "image", "img_path": "images/f1.jpg", "image_caption": ["Figure 1. Full-page figure"], "page_idx": 4},
          {"type": "table", "table_body": "<table><tr><td>1</td></tr></table>", "table_caption": ["Table 1"], "page_idx": 5},
          {"type": "equation", "text": "", "page_idx": 6},
          T(8, "Discussion", 1), T(8, "Discussion text."),
          T(9, "References", 1), {"type": "ref_text", "text": "[1] A ref.", "page_idx": 8},
          {"type": "ref_text", "text": "[2] B ref.", "page_idx": 9},
          {"type": "aside_text", "text": "Supplementary note", "page_idx": 10},
          {"type": "header", "text": "Journal header", "page_idx": 11}]
    if core_blank:
        cl = [b for b in cl if b["page_idx"] != core_blank - 1] + [{"type": "page_number", "text": "3", "page_idx": core_blank - 1}]
    if blank_page is None:
        cl = [b for b in cl if b["page_idx"] != 11] + [T(12, "Appendix text.")]
    return cl


def test_each_page_kind_is_recognised():
    r = mineru.parse_content_list(paper())
    k = page_kinds(r, 13)
    assert k == {1: "text", 2: "text", 3: "text", 4: "text", 5: "figure", 6: "table", 7: "equation", 8: "text",
                 9: "text", 10: "reference", 11: "back_matter", 12: "chrome_only", 13: "empty"}
    # a caption-only block and a title-only page
    r2 = mineru.parse_content_list([T(1, "Body."), {"type": "other", "image_caption": ["Figure 2"], "page_idx": 1},
                                    T(3, "Chapter 2", 1)])
    assert page_kinds(r2, 3) == {1: "text", 2: "caption", 3: "text"}   # a heading is body text: covered
    # MinerU list / code blocks now contribute their text (were silently empty before)
    r3 = mineru.parse_content_list([{"type": "list", "list_items": ["a", "b"], "page_idx": 0},
                                    {"type": "code", "code_body": "x = 1", "page_idx": 1}])
    assert page_kinds(r3, 2) == {1: "text", 2: "text"}


def test_full_page_figures_no_longer_stop_and_blank_page_outside_core_is_unknown():
    r = mineru.parse_content_list(paper())
    rep = assess(r, 12)
    assert rep.level == "E2" and rep.metrics["missing_pages"] == [12]
    assert rep.metrics["unknown_pages"] == [{"page": 12, "kind": "chrome_only", "why": "只有页眉页脚/页码"}]
    assert "第 12 页：只有页眉页脚/页码" in rep.reasons[0] and "UNKNOWN" in rep.reasons[0]
    assert rep.metrics["page_kinds"]["5"] == "figure"
    assert assess(mineru.parse_content_list(paper(blank_page=None)), 12).level == "E2"   # no visuals file check -> E2 cap


def test_blank_page_inside_methods_results_stops_with_plain_message():
    rep = assess(mineru.parse_content_list(paper(core_blank=3)), 12)
    assert rep.level == "E1"
    assert "方法/结果部分有页面没有解析出任何内容：第 3 页：只有页眉页脚/页码（在方法/结果部分）" in rep.reasons[0]


def test_too_many_blank_pages_stops():
    cl = [T(1, "Intro", 1), T(1, "Body."), T(2, "Body.")] + [{"type": "header", "text": "h", "page_idx": i} for i in range(2, 5)]
    rep = assess(mineru.parse_content_list(cl), 10)       # pages 3-10 have nothing: 80 %
    assert rep.level == "E1" and "超过 20%" in rep.reasons[-1] and "第 3 页：只有页眉页脚/页码" in rep.reasons[-1]
    assert "第 10 页：空白（没有任何内容）" in rep.reasons[-1]


class PagesMinerU(FakeMinerU):
    def __init__(self, cl):
        super().__init__()
        self.cl = cl

    def req(self, method, url, token=None, json_body=None, timeout=120):
        if url.endswith("r.zip"):
            self.calls.append((method, url, bool(token)))
            b = io.BytesIO()
            with zipfile.ZipFile(b, "w") as z:
                z.writestr("x_content_list.json", json.dumps(self.cl, ensure_ascii=False))
                z.writestr("layout.json", json.dumps({"pdf_info": [{}] * 12}))
            return 200, b.getvalue()
        return super().req(method, url, token, json_body, timeout)


def run12(cfg, tmp_path, f, answers):
    zt, _ = zot_fake(tmp_path / "Zotero" / "storage")
    ui = ScriptUI(answers)
    r = None
    err = None
    try:
        r = realrun.run(cfg, "精读zotero中的Gait study title，并将精读笔记存入obsidian中", ui, zotero=ZoteroClient(zt),
                        llm_tx=topic_llm("existing", "认知与步态"),
                        mineru_kwargs={"req": f.req, "put": f.put, "sleep": lambda s: None}, pages_fn=lambda p: 12,
                        stats_fn=STATS)
    except Stop as e:
        err = e
    return r, ui, err


def test_run_continues_lists_unknown_page_in_evidence(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    r, ui, err = run12(cfg, tmp_path, PagesMinerU(paper()), ["y", "1", ""])
    assert err is None, err
    t = ui.text
    assert "抽取完整度 E2" in t and "第 5 页 整页图（无正文）" in t and "第 6 页 表格（无正文）" in t
    assert "⚠ 以下页面没有解析出内容，记为 UNKNOWN 页面：第 12 页：只有页眉页脚/页码" in t
    ev = Path(r["evidence"]).read_text("utf-8")
    assert "**UNKNOWN 页面**" in ev and "- 第 12 页：只有页眉页脚/页码 · [打开原页](zotero://open-pdf/library/items/PDF00001?page=12)" in ev


def test_stop_names_pages_and_rerun_reuses_mineru_cache(tmp_path, kr, monkeypatch, capsys):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    f = PagesMinerU(paper(core_blank=3))
    r, ui, err = run12(cfg, tmp_path, f, ["y", ""])
    assert r is None and "抽取完整度 E1" in str(err) and "第 3 页：只有页眉页脚/页码（在方法/结果部分）" in str(err)
    assert "inspect-parse AAAA1111" in str(err) and "不会重复上传" in str(err)
    uploads = [c for c in f.calls if c[1].endswith("/file-urls/batch")]
    assert len(uploads) == 1
    # rerun after the stop: cache hit, nothing uploaded
    f2 = PagesMinerU(paper(core_blank=3))
    r, ui2, err2 = run12(cfg, tmp_path, f2, ["y", ""])
    assert f2.calls == [] and "MinerU：已有解析缓存，不上传" in ui2.text and "抽取完整度 E1" in str(err2)
    # inspect-parse on the cached job: counts only, never content
    capsys.readouterr()
    assert cli.main(["--config", str(cfg.path), "inspect-parse", "AAAA1111"]) == 0
    out = capsys.readouterr().out
    assert "任务：users_0__AAAA1111__" in out and "3 | · | · |" in out and "只有页眉页脚/页码（方法/结果）" in out
    assert "5 | · | · | · | · | 1 |" in out and "抽取完整度：E1" in out
    assert SECRET not in out and "Participants" not in out and "Methods" not in out
    # review 3: --page lists the image blocks of a physical page (type, bbox, file, figure) without body text
    assert cli.main(["--config", str(cfg.path), "inspect-parse", "AAAA1111", "--page", "4-5"]) == 0
    out = capsys.readouterr().out
    assert "—— 物理第 5 页（MinerU page_idx=4；Zotero 链接 ?page=5 打开的就是这一页）" in out
    assert "image：无 bbox" in out and "图注：Figure 1. Full-page figure；归入：Fig1（有图注）" in out
    assert "images/f1.jpg" in out and "未写任何文件" in out
    assert SECRET not in out and "结果显示步速下降" not in out and "加 --text" in out
    assert cli.main(["--config", str(cfg.path), "inspect-parse", "AAAA1111", "--page", "2", "--text"]) == 0
    assert SECRET in capsys.readouterr().out          # only with the explicit --text
    assert cli.main(["--config", str(cfg.path), "inspect-parse", "AAAA1111", "--page", "x"]) == 1


def test_partial_extraction_is_not_treated_as_cache(tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    vault, pdf, cfg = setup_run(tmp_path)
    f = PagesMinerU(paper())
    run12(cfg, tmp_path, f, ["y", "1", ""])
    job = next(d for d in (cfg.data_dir / "jobs").iterdir() if (d / "mineru").is_dir())
    for p in (job / "mineru" / "extracted").glob("*_content_list.json"):
        p.unlink()                                   # simulate an interrupted unzip
    f2 = PagesMinerU(paper())
    r, ui, err = run12(cfg, tmp_path, f2, ["y", "1", ""])
    assert any(c[1].endswith("/file-urls/batch") for c in f2.calls) and "将上传 PDF 副本" in ui.text, (err, ui.text[-600:], f2.calls)
    assert not (job / "mineru" / "extracted.partial").exists()
