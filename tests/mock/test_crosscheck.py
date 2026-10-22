"""Mock layer: vision cross-check (deterministic numbers + fake DeepSeek judge), conflict rendering,
Zotero metadata precedence, INFERENCE number flags, table glossing / empty cells."""
import json

from litreader.analysis.crosscheck import deterministic, judge
from litreader.analysis.validator_v2 import validate_v2
from litreader.llm.config import parse_config
from litreader.parse.blocks import Block
from litreader.render.l2_note_v2 import gloss, render
from litreader.zotero.metadata import from_item


def B(o, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o, **kw)


TABLE = "<table><tr><td>Knee peak extension angle</td><td>-0.59 (4.54)</td><td></td><td>-6.50 (4.58)</td><td>8.77 (<0.0001)</td></tr></table>"
BLOCKS = [B(0, "title", 1, "某研究"), B(1, "title", 5, "结果"),
          B(2, "text", 5, "三组间右膝峰值伸展角（F=8.77，p<0.0001）差异显著，MCI 组膝着地角最小。"),
          B(3, "table", 7, "", caption="表 2 | 运动学", table_html=TABLE),
          B(4, "figure", 8, "", caption="图 2 | 右膝运动学。", img_path="images/f2.jpg")]
FIG = {"id": "Fig2", "kind": "figure", "number": "2", "caption": "图 2 | 右膝运动学。", "flags": [],
       "parts": [{"img_path": "images/f2.jpg", "physical_page": 8, "order": 4}]}
OBS = {"Fig2": {"finding": "峰值伸展角三组间无显著差异；MCI 着地角最小；误差棒约 3 度", "numbers": [], "unreadable": "", "model": "vm"}}
CFG = parse_config({"providers": {"j": {"protocol": "openai_compatible", "base_url": "https://j.example", "model": "jm",
                                        "key_env": "JK", "json_mode": True}}, "stations": {"judge": ["j"]}})


def fake_judge(claims):
    seen = []

    def t(url, h, body, timeout):
        seen.append(json.loads(body))
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps({"claims": claims})}}],
                                "usage": {"prompt_tokens": 50, "completion_tokens": 20}}).encode()
    return t, seen


GOOD_CLAIMS = [
    {"claim": "峰值伸展角三组间无显著差异", "verdict": "CONTRADICTED", "block_id": "b2",
     "quote": "三组间右膝峰值伸展角（F=8.77，p<0.0001）差异显著", "reason": "原文报告显著"},
    {"claim": "MCI 着地角最小", "verdict": "CONSISTENT", "block_id": "b2", "quote": "MCI 组膝着地角最小", "reason": ""},
    {"claim": "误差棒约 3 度", "verdict": "UNVERIFIABLE", "block_id": None, "quote": None, "reason": "原文无"}]


def test_judge_catches_contradiction_and_gates_quotes():
    t, seen = fake_judge(GOOD_CLAIMS + [
        {"claim": "伪造", "verdict": "CONSISTENT", "block_id": "b2", "quote": "原文没有这句话", "reason": ""},
        {"claim": "差异 9.99", "verdict": "CONSISTENT", "block_id": "b2", "quote": "差异显著", "reason": ""}])
    out, info = judge(FIG, OBS["Fig2"], BLOCKS, CFG.chain("judge"), t, {"JK": "k"})
    v = {x["claim"]: x["verdict"] for x in out}
    assert v["峰值伸展角三组间无显著差异"] == "CONTRADICTED" and v["MCI 着地角最小"] == "CONSISTENT"
    assert v["伪造"] == "UNVERIFIABLE" and v["差异 9.99"] == "UNVERIFIABLE"       # quote gate / number gate
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "[b3|p7|table]" in seen[0]["messages"][1]["content"]                        # tables are given to the judge
    assert info["usage"]["prompt_tokens"] == 50


def test_judge_failure_means_unchecked():
    out, info = judge(FIG, OBS["Fig2"], BLOCKS, CFG.chain("judge"), lambda *a: (500, b""), {"JK": "k"})
    assert len(out) == 1 and out[0]["verdict"] == "UNVERIFIABLE" and info["status"].startswith("JUDGE_FAILED")
    t, _ = fake_judge([])
    out, info = judge(FIG, OBS["Fig2"], BLOCKS, CFG.chain("judge"), t, {"JK": "k"})
    assert out[0]["verdict"] == "UNVERIFIABLE"


def test_deterministic_numbers():
    d = deterministic("F=8.77，n=181", BLOCKS)
    assert d["found"] == ["8.77"] and d["not_found"] == ["181"]


def S(text, label="PAPER", ids=("b2",)):
    return {"text": text, "label": label, "basis_block_ids": list(ids), "link_label": "结果"}


def analysis():
    return {"meta": {"title_zh": {"value": "某研究", "block_id": "b0", "physical_page": 1, "label": "PAPER"}},
            "three_minute": {"what": S("研究"), "how": S("方法"), "key_result": S("F=8.77"),
                             "value": S("样本约占 44%", "INFERENCE"), "caution": S("小样本", "INFERENCE")},
            "sections": {"s4": {"tables": [{"title": "运动学", "label": "PAPER", "columns": ["参数", "MCI", "SCD"],
                                            "rows": [["MCI 峰值伸展角", "-0.59 (4.54)", "—"]], "basis_block_ids": ["b3"]}]}},
            "figures": [{"id": "Fig2", "section": "s4", "title": "右膝"}],
            "abbreviations": [{"abbr": "MCI", "zh": "轻度认知障碍"}]}


def _render(cc, zm=None):
    v = validate_v2(analysis(), BLOCKS, [FIG])
    return v, render(v, blocks=BLOCKS, manifest=[FIG], vision_obs=OBS, figure_paths={"Fig2": ["_图表/K/Fig2-1.jpg"]},
                     attachment_key="ATT", parent_key=None, e_level="E3", translation_notice="译本", link_mechanism_verified=False,
                     read_date="2026-10-17", evidence_link="ev", model_info={"text": "m", "vision": "vm"},
                     crosscheck=cc, zotero_meta=zm)


def test_conflict_block_never_paper():
    t, _ = fake_judge(GOOD_CLAIMS)
    out, _ = judge(FIG, OBS["Fig2"], BLOCKS, CFG.chain("judge"), t, {"JK": "k"})
    v_, md = _render({"Fig2": out})
    assert "> [!warning] 读图与原文不一致 1 处（vm 读图" in md and "不作为 PAPER 事实" in md
    assert "「三组间右膝峰值伸展角（F=8.77，p<0.0001）差异显著」 [原文p5](zotero://open-pdf/library/items/ATT?page=5)" in md
    assert "[原图p8](zotero://open-pdf/library/items/ATT?page=8)" in md
    paper_line = next(l for l in md.splitlines() if "已与正文/表格交叉核对" in l)
    paper_part = paper_line.split("**未核对")[0]
    assert "无显著差异" not in paper_part and "着地角最小" in paper_part
    assert "**未核对（vm 读图，正文/表格无法确认）：** 误差棒约 3 度" in md
    assert v_.note_meta["figure_check"] == "MINERU_CROPS_VISION_CROSSCHECKED_TEXT" and "figure_check" not in md


def test_inference_numbers_flagged_and_table_cells():
    v, md = _render({})
    assert v.stats["inference_numbers_flagged"] == 1 and "`未核对数字：44`" in md
    assert "UNKNOWN（此格无数据）" in md
    assert "MCI（轻度认知障碍） 峰值伸展角" in md.split("| 参数")[1].split("\n\n")[0] or md.count("（轻度认知障碍）") == 1


def test_gloss_in_table_rows_not_separator():
    out = gloss("| a | b |\n|---|---|\n| MCI | 1 |", [{"abbr": "MCI", "zh": "轻度认知障碍"}])
    assert "| MCI（轻度认知障碍） | 1 |" in out and "|---|---|" in out


def test_zotero_metadata_precedence():
    item = {"key": "PK123", "data": {"title": "Gait Kinematic and Kinetic Characteristics", "date": "2021-08-03",
            "publicationTitle": "Frontiers in Aging Neuroscience", "DOI": "10.3389/x",
            "creators": [{"creatorType": "author", "firstName": "Qian", "lastName": "Zhong"},
                         {"creatorType": "author", "firstName": "N", "lastName": "Ali"}, {"creatorType": "editor", "name": "E"}]}}
    zm = from_item(item)
    assert zm["authors"] == "Qian Zhong 等" and zm["title_en"].startswith("Gait") and zm["parent_key"] == "PK123"
    assert from_item({"data": {"title": "轻度认知障碍研究"}}).get("title_en") is None
    assert from_item(None) == {}
    v_, md = _render({}, zm)
    assert "# 某研究\n\n*Gait Kinematic and Kinetic Characteristics*\n" in md
    assert "Qian Zhong 等（Zotero）" in md and '  parent_item_key: "PK123"' in md \
        and v_.note_meta["metadata_source"]["journal"] == "ZOTERO" and "metadata_source" not in md
    assert "元数据 authors" not in md.split("重点待确认问题（UNKNOWN）")[-1]
    _, md0 = _render({})
    assert "英文原题 UNKNOWN" in md0 and "parent_item_key" not in md0   # G10-7: absent ids are omitted from litreader:
