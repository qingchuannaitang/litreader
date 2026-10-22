"""Unit layer: LaTeX cleanup, validator v2 gates, v2 renderer, vision fallback (synthetic, no network)."""
import json
from pathlib import Path

from litreader.analysis.latex import clean
from litreader.analysis.validator_v2 import numbers, validate_v2
from litreader.analysis.vision import observe
from litreader.llm.config import parse_config
from litreader.parse.blocks import Block
from litreader.render import protected_zone
from litreader.render.l2_note_v2 import NO_VISION, gloss, render, render_evidence


def B(o, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o, **kw)


BLOCKS = [B(0, "title", 1, "某步态研究"), B(1, "header", 1, "doi: 10.1/abc"),
          B(2, "text", 2, "共纳入 79 名，MCI 22 例。膝伸展角增加 $5 . 9 1 ^ { \\circ }$"),
          B(3, "text", 9, "本研究为横断面设计，样本量有限。"),
          B(4, "figure", 4, "", caption="图 1 | 招募流程图。", img_path="images/f1.jpg")]
MAN = [{"id": "Fig1", "kind": "figure", "number": "1", "caption": "图 1 | 招募流程图。", "flags": [],
        "parts": [{"img_path": "images/f1.jpg", "physical_page": 4}]}]


def S(text, label="PAPER", ids=("b2",), ll="结果"):
    return {"text": text, "label": label, "basis_block_ids": list(ids), "link_label": ll}


def good():
    return {"meta": {"title_zh": {"value": "某步态研究", "block_id": "b0", "physical_page": 1, "label": "PAPER"},
                     "doi": {"value": "10.1/abc", "context": "doi: 10.1/abc", "block_id": "b1", "physical_page": 1, "label": "PAPER"},
                     "title_en": {"value": "Invented", "label": "PAPER", "block_id": "b0", "physical_page": 1}},
            "topic": "步态研究", "tags": ["MCI"],
            "facts": [{"field": "n", "value": "79", "context": "共纳入 79 名", "block_id": "b2", "physical_page": 2, "label": "PAPER"},
                      {"field": "n", "value": "22", "context": "MCI 22 例", "block_id": "b2", "physical_page": 2, "label": "PAPER"},
                      {"field": "knee", "value": "5.91°", "context": "膝伸展角增加 5.91°", "block_id": "b2", "physical_page": 2, "label": "PAPER"}],
            "three_minute": {"what": S("研究 MCI 步态"), "how": S("纳入 79 名"), "key_result": S("膝伸展角增加 5.91°"),
                             "value": S("可作基线", "INFERENCE"), "caution": S("样本 80 名", ids=("b3",))},
            "one_liner": S("值得比较", "INFERENCE"),
            "sections": {"s1": {"heading_suffix": "它回答了什么问题？", "paragraphs": [S("纳入 79 名")],
                                "supports": [S("组间差异", "INFERENCE")], "cannot_answer": [S("因果", "INFERENCE", ("b3",))]},
                         "s2": {"heading_suffix": "分母是多少？", "tables": [
                             {"title": "分母", "label": "PAPER", "columns": ["阶段", "人数"], "rows": [["分析", "79"], ["MCI", "22"]], "basis_block_ids": ["b2"]},
                             {"title": "坏表", "label": "PAPER", "columns": ["a", "b"], "rows": [["x", "99"]], "basis_block_ids": ["b2"]}]},
                         "s6": {"author_conclusion": S("MCI 膝角改变"), "evaluation": S("需纵向研究", "INFERENCE", ("b3",))},
                         "s8": {"items": [{"title": "设基线", "basis": S("纳入 79 名"), "help": S("可借鉴", "INFERENCE"), "limit": S("小样本", "INFERENCE", ("b3",))}],
                                "review_summary": S("概括", "INFERENCE")},
                         "s9": {"next_checks": ["核对英文原版"]}},
            "figures": [{"id": "Fig1", "section": "s2", "title": "人数如何流失？", "finding": S("流程图", ids=("b4",)),
                         "interpretation": S("分母需分清", "INFERENCE", ("b4",)), "limitation": S("未看图", "INFERENCE", ("b4",))},
                        {"id": "Fig9", "section": "s2"}],
            "abbreviations": [{"abbr": "MCI", "zh": "轻度认知障碍"}, {"abbr": "XYZ", "zh": "虚构"}],
            "unknowns": [{"item": "英文原题", "why": "译本无"}]}


def test_latex_clean():
    assert clean("增加 $5 . 9 1 ^ { \\circ }") == "增加 5.91°"
    assert clean("$71.23 \\pm 6.65$ 岁") == "71.23±6.65 岁"
    assert clean("<sup>1</sup> 南京") == "^1 南京"


def test_numbers_ignores_small_ints():
    assert numbers("3 组共 79 人，5.91°") == {"79", "5.91"}


def test_gates():
    v = validate_v2(good(), BLOCKS, MAN)
    reasons = {r["where"]: r["reason"] for r in v.rejected}
    assert "numbers not found" in reasons["3min.caution"]            # 80 not in b3
    assert "no table cell passed the number check" in reasons["s2.t1"]                         # 99 invented
    assert "meta.title_en" in reasons                                   # invented English title
    assert "figure.1" in reasons and "abbreviation" in reasons
    assert v.meta["title_en"]["label"] == "UNKNOWN" and v.meta["doi"]["label"] == "PAPER"
    assert [f["field"] for f in v.facts] == ["n", "knee"] and len(v.duplicates) == 1   # dedupe
    assert v.data["three_minute"]["key_result"] and len(v.data["sections"]["s2"]["tables"]) == 1


def test_label_slot_rules():
    a = good()
    a["three_minute"]["key_result"] = S("可能有效", "INFERENCE")
    a["three_minute"]["value"] = S("纳入 79 名", "PAPER")
    v = validate_v2(a, BLOCKS, MAN)
    assert v.data["three_minute"]["key_result"] is None and v.data["three_minute"]["value"] is None


def _render(v, vision_obs):
    return render(v, blocks=BLOCKS, manifest=MAN, vision_obs=vision_obs, figure_paths={"Fig1": ["_图表/K/Fig1-1.jpg"]},
                  attachment_key="7M6C5QRN", parent_key="K", e_level="E3", translation_notice="中文译本。",
                  link_mechanism_verified=True, read_date="2026-10-17", evidence_link="_证据档案/K/x——证据档案",
                  model_info={"text": "m", "vision": "vm"})


def test_render_v2_structure_caption_fallback():
    v = validate_v2(good(), BLOCKS, MAN)
    md = _render(v, None)
    assert md.startswith("---\n中文标题:") and v.note_meta["extraction_level"] == "E3" and "source_level" not in md
    assert "# 某步态研究\n\n*英文原题 UNKNOWN" in md and "<p " not in md and "cssclass" not in md
    for s in ("> [!info] 论文信息", "**按需阅读：**", "> [!abstract] 三分钟了解论文", "^three-minute",
              "**最值得长期记住的一句话", "> [!note] 阅读约定", "## 一、为什么读这篇：它回答了什么问题？",
              "## 二、研究设计与对象：分母是多少？", "**本文能支持的认识：**", "| 分析 | 79 |", "## 六、作者结论与独立科研评价",
              "## 八、本篇论文最值得借鉴的3件事", "## 重点待确认问题（UNKNOWN）", "通用科研价值"):
        assert s in md, s
    assert "[结果p2](zotero://open-pdf/library/items/7M6C5QRN?page=2)" in md
    assert "![[_图表/K/Fig1-1.jpg|760]]" in md and "物理p4" in md and NO_VISION in md
    assert "5.91°" in md and "\\circ" not in md
    assert "MCI（轻度认知障碍）" in md and md.count("（轻度认知障碍）") == 1
    assert "{{" not in md and "TODO" not in md
    assert "我最想带走的结论" in protected_zone.extract(md)
    assert "本项未通过校验" not in md and "未生成" not in md and "最需警惕" not in md   # rejected caution: line omitted (fix 12)


def test_render_with_vision():
    obs = {"Fig1": {"finding": "共 181 人筛查", "numbers": ["181"], "unreadable": "", "model": "vm"}}
    v = validate_v2(good(), BLOCKS, MAN)
    md = _render(v, obs)
    # without a cross-check, a vision finding is never PAPER
    assert "**未核对（vm 读图，正文/表格无法确认）：** 共 181 人筛查" in md and "无通过交叉核对的读图陈述" not in md
    assert NO_VISION not in md and v.note_meta["figure_check"] == "MINERU_CROPS_VISION_UNCHECKED"


def test_evidence_keeps_raw():
    v = validate_v2(good(), BLOCKS, MAN)
    ev = render_evidence(v, raw={}, blocks=BLOCKS, manifest=MAN, attachment_key="K", title="t", runs=[], vision_runs=[], e_report={})
    assert "## 被拒条目" in ev and "## UNKNOWN 登记" in ev and "## 重复字段" in ev


def test_gloss_skips_links_and_headings():
    out = gloss("## MCI 标题\n[MCIp2](zotero://x?MCI) 然后 MCI 出现", [{"abbr": "MCI", "zh": "轻度认知障碍"}])
    assert out.endswith("然后 MCI（轻度认知障碍） 出现") and "## MCI 标题" in out


VCFG = parse_config({"providers": {"v": {"protocol": "openai_compatible", "base_url": "https://v.example/v1", "model": "vm",
                                         "key_env": "VK", "supports_vision": True, "extra_body": {"thinking": {"type": "disabled"}}}},
                     "stations": {"vision": ["v"]}})


def test_vision_observe_ok_and_fail(tmp_path: Path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images/f1.jpg").write_bytes(b"\xff\xd8fakejpeg")
    seen = []

    def ok(url, h, body, t):
        seen.append(json.loads(body))
        return 200, json.dumps({"choices": [{"message": {"content": '```json\n{"finding":"共 181 人","numbers":["181"]}\n```'}}],
                                "usage": {"prompt_tokens": 7}}).encode()
    obs, info = observe(MAN[0], tmp_path, VCFG.chain("vision", need_vision=True), ok, {"VK": "k"})
    msg = seen[0]["messages"][0]["content"]
    assert obs["finding"] == "共 181 人" and info["usage"]["prompt_tokens"] == 7
    assert msg[1]["image_url"]["url"].startswith("data:image/jpeg;base64,") and seen[0]["thinking"] == {"type": "disabled"}
    obs, info = observe(MAN[0], tmp_path, VCFG.chain("vision", need_vision=True), lambda *a: (500, b"x"), {"VK": "k"})
    assert obs is None and info["status"] == "FAILED"
    obs, info = observe({**MAN[0], "parts": [{"img_path": "images/missing.jpg"}]}, tmp_path, VCFG.chain("vision"), ok, {"VK": "k"})
    assert obs is None and info["status"] == "SKIPPED"


def test_markdown_escape_and_latex_spacing():
    from litreader.analysis.validator import check_fact
    b = {"b0": B(0, "text", 1, "（1）年龄 55\\~85岁；"), "b1": B(1, "text", 1, "减小 $6 . 2 1 ^ { \\circ } \\ : \\left( p = \\right.$ 0.001")}
    assert check_fact({"value": "55~85岁", "context": "（1）年龄 55~85岁", "block_id": "b0", "physical_page": 1, "label": "PAPER"}, b) is None
    assert check_fact({"value": "-6.21", "context": "减小 6.21°", "block_id": "b1", "physical_page": 1, "label": "PAPER"}, b)  # sign invented
    assert "\\" not in clean("减小 $6 . 2 1 ^ { \\circ } \\ : \\left( p = \\right.$")


def test_gloss_not_doubled():
    out = gloss("比较轻度认知障碍（MCI）与 MCI 组", [{"abbr": "MCI", "zh": "轻度认知障碍"}])
    assert out == "比较轻度认知障碍（MCI）与 MCI 组"


def test_vision_only_numbers_flagged():
    obs = {"Fig1": {"finding": "共 181 人，79 人分析", "numbers": [], "unreadable": "", "model": "vm"}}
    md = _render(validate_v2(good(), BLOCKS, MAN), obs)
    assert "仅视觉读出、正文/图注未见的数字：181" in md
