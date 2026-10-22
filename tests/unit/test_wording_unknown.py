"""Unit layer: wording gate, UNKNOWN impact ranking, top-N display."""
from litreader.analysis.unknown_rank import rank
from litreader.analysis.validator_v2 import validate_v2
from litreader.analysis.wording import gate
from litreader.parse.blocks import Block
from litreader.render.l2_note_v2 import render, render_evidence


def test_gate_rewrite_reject_keep():
    assert gate("连续减7模型在推导样本中表现最好", "AUC 0.906")[0] is None      # review 4: metric not in the sentence
    assert gate("连续减7模型表现最好，AUC 0.906", "AUC 0.906")[0] == "连续减7模型数值最高，AUC 0.906"   # next clause gives the value
    assert gate("模型2优于模型1", "AUC 0.906 vs 0.893")[0] is None              # review 4: metric only in the cited text
    assert gate("模型2的 AUC 优于模型1", "AUC 0.906 vs 0.893")[0] == "模型2的 AUC 数值高于模型1"
    assert gate("该方法更高效", "耗时 2 分钟")[0] is None                 # time: lower is better -> never "数值更高"
    assert gate("该方法更高效", "共 2 组")[0] is None                      # no metric, word not in cited text -> reject
    assert gate("该方法更高效", "该方法更高效地利用视角")[0] == "该方法更高效（作者表述，无对应检验）"
    assert gate("该方法更高效", "共 2 组", "INFERENCE")[0] == "该方法更高效（整理者推断，无对应检验）"
    new, rule = gate("连续减7表现更差", "步速 0.61")
    assert new is None and rule.startswith("reject")
    assert gate("MCI 组步速更差", "两组比较 p<0.001") == ("MCI 组步速更差", None)          # test present -> kept
    assert gate("MCI 组更好", "F=8.77") == ("MCI 组更好", None)
    assert gate("无比较词", None) == ("无比较词", None)
    assert gate("核心结果：表现最佳", None)[0] is None                                   # headings: no metric -> rejected
    assert gate("核心结果：AUC 表现最佳", None)[0] == "核心结果：AUC 数值最高"


def test_rank_unknowns():
    u = [{"item": "元数据 authors", "why": "x"}, {"item": "英文原版一致性", "why": "版本"},
         {"item": "外部验证分母不一致", "why": "影响结论"}, {"item": "临床推广人群", "why": "外推"}]
    r = rank(u)
    assert [x["item"] for x in r] == ["外部验证分母不一致", "临床推广人群", "英文原版一致性", "元数据 authors"]
    assert r[0]["impact"] >= 3 and r[-1]["impact"] == 0


B = [Block("title", 1, None, "研究", order=0), Block("text", 2, None, "三个模型 AUC 分别为 0.906、0.893。", order=1),
     Block("text", 3, None, "两组比较 p<0.001，MCI 步速更低。", order=2)]


def S(t, ids=("b1",), label="PAPER"):
    return {"text": t, "label": label, "basis_block_ids": list(ids), "link_label": "结果"}


def test_validator_applies_wording_and_logs():
    a = {"meta": {"title_zh": {"value": "研究", "block_id": "b0", "physical_page": 1, "label": "PAPER"}},
         "three_minute": {"key_result": S("连续减7模型表现最好，AUC 0.906"), "caution": S("连续减7表现更差"),
                          "what": S("MCI 步速更差", ("b2",))},
         "sections": {"s4": {"heading_suffix": "连续减7表现更差，但指标并非全部显著"},
                      "s5": {"heading": "连续减7模型在推导样本中表现最好"}},
         "unknowns": [{"item": f"问题{i}", "why": "复现"} for i in range(8)] + [{"item": "结论冲突", "why": "统计"}]}
    v = validate_v2(a, B, [])
    tm = v.data["three_minute"]
    assert tm["key_result"]["text"] == "连续减7模型数值最高，AUC 0.906"
    assert tm["caution"] is None and tm["what"]["text"] == "MCI 步速更差"
    assert v.data["sections"]["s4"]["heading_suffix"] == "" and v.data["sections"]["s5"]["heading_suffix"] == ""
    assert len(v.wording) == 4 and v.stats["wording_changes"] == 4
    assert v.unknowns[0]["item"] == "结论冲突"
    md = render(v, blocks=B, manifest=[], vision_obs=None, figure_paths={}, attachment_key="A", parent_key="P", e_level="E2",
                translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev", model_info={"text": "m"})
    sec = md.split("## 重点待确认问题（UNKNOWN）")[1].split("##")[0]
    assert sec.count("\n1. ") + sec.count("\n2. ") + sec.count("\n3. ") + sec.count("\n4. ") + sec.count("\n5. ") == 5
    assert "\n6. " not in sec and "另 " in sec and "结论冲突" in sec
    assert "表现最好" not in md and "表现更差" not in md
    ev = render_evidence(v, raw={}, blocks=B, manifest=[], attachment_key="A", title="t", runs=[], vision_runs=[], e_report={})
    assert "## 措辞闸门记录" in ev and "（已拒绝）" in ev and ev.count("impact=") == len(v.unknowns)


def test_extended_lexicon():
    assert gate("膝角更敏感", "均值 5.2")[0] is None
    assert gate("步速效应最强", "F=12.91")[0] == "步速效应最强"
