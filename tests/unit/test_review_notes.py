"""DeepGaitLab review fixes 8, 11–19: note rendering (offline, synthetic + DeepGaitLab verbatim excerpts)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_note_v2 as T  # noqa: E402

from litreader.analysis import terms  # noqa: E402
from litreader.analysis.latex import clean  # noqa: E402
from litreader.analysis.validator_v2 import validate_v2  # noqa: E402
from litreader.render.l2_note_v2 import questionize, render, render_evidence, tidy  # noqa: E402
from litreader.zotero.identity import detect_source_version  # noqa: E402

S = T.S
BLOCKS = T.BLOCKS + [T.B(5, "text", 14, "在 MCI 组中，双相机配置的 RMSD 为 4.32 ± 1.27%，显著低于对照（p < 0.001）。")]


def _r(v, **kw):
    base = dict(blocks=BLOCKS, manifest=T.MAN, vision_obs=None, figure_paths={"Fig1": ["_图表/K/Fig1-1.jpg"]},
                attachment_key="7M6C5QRN", parent_key="K", e_level="E3", translation_notice=None,
                link_mechanism_verified=True, read_date="2026-10-17", evidence_link="ev", model_info={"text": "m"})
    base.update(kw)
    return render(v, **base)


def _doc():
    d = T.good()
    d["facts"].append({"field": "mci_rmsd", "value": "4.32 ± 1.27%", "context": "双相机配置的 RMSD 为 4.32 ± 1.27%",
                       "block_id": "b5", "physical_page": 14, "label": "PAPER"})
    d["sections"]["s1"]["paragraphs"] = [S("本研究在社区共纳入 79 名老年受试者并完成步态分析")]
    d["sections"]["s4"] = {"heading_suffix": "核心结果", "paragraphs": [S("本研究共纳入 79 名老年受试者并完成步态分析")]}  # dup
    return d


def test_fix8_verified_clinical_result_reaches_body_verbatim():
    md = _r(validate_v2(_doc(), BLOCKS, T.MAN))
    line = next(l for l in md.splitlines() if l.startswith("**其他已逐字核对的结果"))
    assert "「双相机配置的 RMSD 为 4.32 ± 1.27%」" in line and "page=14" in line
    assert md.index("\n## 四、") < md.index(line) < md.index("\n## 五、")


def test_fix11_headings_and_figure_titles_are_questions():
    md = _r(validate_v2(_doc(), BLOCKS, T.MAN))
    assert "## 四、核心结果：核心结果——结果说明了什么？" in md
    for h in re.findall(r"^#{2,3} .*$", md, re.M):
        if "：" in h or "｜" in h:
            assert h.endswith("？"), h
    assert questionize("连续减7模型最好") == "连续减7模型最好——说明了什么？" and questionize("为何？") == "为何？"
    d = _doc(); d["figures"][0]["title"] = ""
    md2 = _r(validate_v2(d, BLOCKS, T.MAN))
    assert "### 图1｜招募流程图——说明了什么？" in md2


def test_fix12_no_placeholder_text_in_body():
    d = _doc()
    d["three_minute"]["key_result"] = S("膝伸展角增加 7.77°")   # rejected (number not in block)
    d["one_liner"] = None
    d["sections"]["s8"]["items"][0]["help"] = None
    d["sections"]["s6"]["evaluation"] = None
    d["figures"][0]["interpretation"] = d["figures"][0]["limitation"] = None
    md = _r(validate_v2(d, BLOCKS, T.MAN))
    for bad in ("本项未通过校验", "未生成", "**可借鉴之处：**", "整理者评价", "最值得长期记住"):
        assert bad not in md, bad
    assert "> **最重要的结果（PAPER）：** 原文摘录：「" in md     # verbatim verified result, not a placeholder


def test_fix13_unknown_counts_consistent_and_zotero_resolved_excluded():
    d = _doc()
    d["unknowns"] = [{"item": "英文原题缺失", "why": "译本无"}, {"item": "随访时间", "why": "未报告"}]
    v = validate_v2(d, BLOCKS, T.MAN)
    md = _r(v, zotero_meta={"title_en": "DeepGaitLab", "authors": "Li 等", "journal": "J", "year": "2025"})
    n = v.stats["unknowns_in_note"]
    assert f"完整证据与{n}项UNKNOWN" in md and f"查看完整 {n} 项 UNKNOWN" in md
    top = md[md.index("## 重点待确认问题"):]
    assert "英文原题" not in top and "元数据 title_en" not in top and "随访时间" in top
    ev = render_evidence(v, raw={}, blocks=BLOCKS, manifest=T.MAN, attachment_key="A", title="t", runs=[], vision_runs=[], e_report={})
    assert "已解决（ZOTERO）" in ev and f"主笔记计 {n} 项" in ev


def test_fix14_info_bar_study_type_matches_frontmatter():
    v = validate_v2(_doc(), BLOCKS, T.MAN)
    md = _r(v, provenance={"study_type": "methods_technical"})
    assert v.note_meta["study_type"] == "methods_technical" and "**研究类型：** 方法学/技术/AI 研究（methods_technical）" in md


def test_fix15_duplicate_paragraph_dropped_negative_results_kept():
    d = _doc()
    d["sections"]["s4"]["negative_results"] = [S("纳入 79 名")]
    md = _r(validate_v2(d, BLOCKS, T.MAN))
    body = md[md.index("## 一、"):]
    s4 = body[body.index("## 四、"):body.index("## 五、")]
    assert "\n本研究共纳入 79 名" not in s4 and "**不能遗漏的阴性结果：** 纳入 79 名" in s4
    assert "本研究在社区共纳入 79 名" in body


def test_fix16_citation_superscripts_never_obsidian_footnotes():
    assert clean("见 DeepLabCut<sup>[47]</sup> 与 x<sup>[12, 13]</sup>") == "见 DeepLabCut[47] 与 x[12, 13]"
    assert "^[" not in clean("模型 ^[3] 与 ^ [4]")


def test_fix17_doubled_punctuation_and_caption_tail():
    assert tidy("图注。；PDF") == "图注；PDF" and tidy("a。。b；；c") == "a。b；c"
    md = _r(validate_v2(_doc(), BLOCKS, T.MAN))
    assert "。；" not in md and "招募流程图；PDF" in md


def test_fix18_translation_notice_chinese_no_debug_ratio():
    sv = detect_source_version("论文_中文版.pdf", 0.62)
    assert all(re.search(r"[\u4e00-\u9fff]", r) for r in sv.reasons)
    assert "CJK" not in " ".join(sv.reasons) and "62%" in " ".join(sv.reasons) and ">=" not in " ".join(sv.reasons)
    from litreader.analysis import vision
    assert "（Overground walking）" in vision.PROMPT


def test_fix19_terms_dense_and_aclr():
    ab = [{"abbr": "ACLR", "zh": "前交叉韧带重建"}]
    assert terms.normalize("使用密度 26 个体表标志点", ab) == "使用密集 26 个体表标志点"
    assert terms.normalize("ACL 患者与 ACL 组", ab) == "ACLR 患者与 ACLR 组"
    assert terms.normalize("ACL 损伤", ab) == "ACL 损伤"                       # not a person noun: untouched
    assert terms.normalize("ACL 患者", ab + [{"abbr": "ACL", "zh": "前交叉韧带"}]) == "ACL 患者"
    assert terms.normalize("骨密度 26 个月", []) == "骨密度 26 个月"


def test_table_and_prompts_carry_review_rules():
    from litreader.analysis.schema_v2 import DOC
    assert "问句" in DOC and "验证人群" in DOC and "分成不同的表" in DOC and "中文（English）" in DOC
