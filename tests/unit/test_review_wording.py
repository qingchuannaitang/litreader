"""Review fixes 1–2 + wording stats: lower-is-better never rewritten 'higher'; LaTeX/garble-normalised quote matching;
deterministic rescue of comparatives that carry their own test; gate name on every wording record; stats = records."""
import json

from litreader.analysis import wording, wording_judge
from litreader.analysis.crosscheck import judge
from litreader.analysis.validator import qnorm, quote_in
from litreader.analysis.validator_v2 import validate_v2
from litreader.llm.config import parse_config
from litreader.render.l2_note_v2 import render, render_evidence
from tests.fixtures.deepgaitlab import BLOCKS, FIG5_CAPTION

CFG = parse_config({"providers": {"j": {"protocol": "openai_compatible", "base_url": "https://j.example", "model": "jm",
                                        "key_env": "JK", "json_mode": True}}, "stations": {"judge": ["j"]}})
ENV = {"JK": "k"}


def fake(payload):
    def t(url, h, body, timeout):
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}],
                                "usage": {"prompt_tokens": 5, "completion_tokens": 2}}).encode()
    return t


def S(t, ids, label="PAPER"):
    return {"text": t, "label": label, "basis_block_ids": list(ids), "link_label": "结果"}


def test_lower_is_better_metrics_never_become_higher():
    # the exact rewrites from the DeepGaitLab archive (Fig5 / Fig6 writer findings)
    new, rule = wording.gate("图 5 显示双相机下 DeepGaitLab 的关节力矩 rRMSD 优于 OpenCap，尤其在单腿深蹲与非矢状面自由度", "图注无检验")
    assert new is None and "lower-is-better" in rule
    new, rule = wording.gate("图 6 显示自动标定的 DeepGaitLab 优于手动标定的 OpenCap", "运动学 RMSD 箱线图")
    assert new is None                    # review 4: metric only from the comparative's clause -> no metric -> reject
    assert wording.gate("DeepGaitLab 的 ICC 优于 OpenCap", "ICC 箱线图")[0] == "DeepGaitLab 的 ICC 数值高于 OpenCap"
    assert wording.gate("误差优于而 ICC 更好", "x")[0] is None                                     # both directions -> reject
    assert wording_judge._rewrite("双相机 DeepGaitLab 的 rRMSD 优于 OpenCap")[0] is None
    for txt in ("RMSD", "rRMSD", "均方根差", "误差", "偏差", "耗时"):
        assert wording.direction(f"{txt} 优于") == "lower", txt


def test_quote_matching_normalises_latex_and_garble_on_both_sides():
    b89, b104, b174 = (next(b for b in BLOCKS if b.order == o) for o in (89, 104, 174))
    src = b89.text
    assert quote_in("ACLR 参与者在髋屈/伸 (OpenCap 13.4±7.9° vs. 7.3±4.3°, p=0.0001", src)        # '~' LaTeX space
    assert quote_in("Theia3D 9.8±3.9° vs. 7.2±2.6°, p=0.0217", src)
    assert quote_in("在双相机 (p=0.1208)", src)
    assert quote_in("RMSD（4.32 ± 1.27% vs. 6.83 ± 1.57%，p<0.0001）", b104.text)                   # U+FFFD italic p
    assert quote_in("SAMURAI [47] 从 RGB 图像中提取分割掩码", b174.caption)                          # <sup>[47]</sup>
    assert not quote_in("OpenCap 13.5±7.9°", src)                                                    # still verbatim
    assert qnorm("4.2 VS. 5.9") == qnorm("4.2 vs 5.9")


def test_crosscheck_keeps_verbatim_quotes_after_latex_cleanup():
    fig = {"id": "Fig3", "kind": "figure", "number": "3", "caption": "图 3. ACL 重建术后患者的逆运动学性能。", "flags": [],
           "parts": [{"img_path": "x.jpg", "physical_page": 15, "order": 96}]}
    t = fake({"claims": [{"claim": "图3A中Theia3D在ACLR患者髋屈/伸RMSD显著升高(标*)", "verdict": "CONSISTENT", "block_id": "b89",
                          "quote": "Theia3D 9.8±3.9° vs. 7.2±2.6°, p=0.0217", "reason": "p<0.05"},
                         {"claim": "图3B中OpenCap在髋屈/伸不对称上未显著偏离零", "verdict": "CONTRADICTED", "block_id": "b92",
                          "quote": "OpenCap 成功检测到该不对称 (10.0±14.9°, p=0.0003)", "reason": "原文显著"}]})
    out, _ = judge(fig, {"finding": "x"}, BLOCKS, CFG.chain("judge"), t, ENV)
    assert out[0]["verdict"] == "CONSISTENT"                      # was 'quote not verbatim in cited block'
    assert out[1]["verdict"] == "CONTRADICTED"                    # the real contradiction now reaches the conflict box


def _v2():
    a = {"meta": {}, "three_minute": {}, "sections": {"s3": {"paragraphs": [
        S("在双相机设置下，DeepGaitLab 的 RMSD 为 4.2 ± 0.6°，显著低于 OpenCap 的 5.9 ± 1.3°（p < 0.0001）。", ["b78"]),
        S("在逆动力学中，双相机 DeepGaitLab 的 rRMSD 为 0.27 ± 0.07，低于 OpenCap 的 0.42 ± 0.17（p < 0.0001）。", ["b111"]),
        S("DeepGaitLab 的整体表现更好。", ["b75"], "INFERENCE")]}}}
    return validate_v2(a, BLOCKS, [])


def test_judge_unsupported_but_test_in_basis_is_rescued_and_logged():
    v = _v2()
    cands = wording_judge.candidates(v.data, {})
    t = fake({"items": [{"id": c["id"], "verdict": "UNSUPPORTED", "reason": "依据块给出比较及p值"} for c in cands]})
    info = wording_judge.apply(v, BLOCKS, {}, CFG.chain("judge"), t, ENV)
    p = v.data["sections"]["s3"]["paragraphs"]
    assert [x["text"][:8] for x in p][:2] == ["在双相机设置下，", "在逆动力学中，双"]          # both kept (were rejected)
    assert len(info.get("rescued") or []) == 2
    assert all(w.get("gate") for w in v.wording)
    assert v.stats["wording_changes"] == len(v.wording)


def test_wording_stats_equal_records_after_render_and_gate_column():
    v = _v2()
    t = fake({"items": []})
    wording_judge.apply(v, BLOCKS, {}, CFG.chain("judge"), t, ENV)
    render(v, blocks=BLOCKS, manifest=[], vision_obs=None, figure_paths={}, attachment_key="A", parent_key="P", e_level="E3",
           translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev", model_info={"text": "m"})
    ev = render_evidence(v, raw={}, blocks=BLOCKS, manifest=[], attachment_key="A", title="t", runs=[], vision_runs=[], e_report={})
    stats = json.loads(ev.split("```json\n")[1].split("```")[0])["stats"]
    assert stats["wording_changes"] == len(v.wording) == ev.split("## 措辞闸门记录")[1].count("\n| wording") + ev.split("## 措辞闸门记录")[1].count("\n| s") + ev.split("## 措辞闸门记录")[1].count("\n| figure")
    assert "| 位置 | 原文 | 处理后 | 闸门 | 规则 |" in ev
    assert all(w.get("gate") for w in v.wording)


# ---- second Mac run (aa00d72): qualitative comparatives without a metric were rewritten to “数值高于” ----
def test_r2_qualitative_comparative_never_becomes_numeric():
    from litreader.analysis.wording import ANNOT_INFER, ANNOT_PAPER
    abstract = "DeepGaitLab 的性能优于商业和开源替代方案，且精度随相机数量增加而单调提升。"
    new, rule = wording.gate("摘要明确指出 DeepGaitLab 的性能优于商业和开源替代方案，且精度随相机数量增加而提升。", abstract, "PAPER")
    assert "数值高于" not in new and new.endswith(ANNOT_PAPER) and rule.startswith("annotate")
    concl = "我们表明 DeepGaitLab 在健康成人、ACL 重建术后、MCI 与卒中人群中优于现有工具。"
    new, _ = wording.gate("作者认为 DeepGaitLab 在健康成人、ACLR 术后、MCI 与卒中恢复期患者中优于现有工具。", concl, "PAPER")
    assert "数值高于" not in new and new.endswith(ANNOT_PAPER)
    new, _ = wording.gate("该结果支持密集标志点表示能更有效利用额外视角。", "随着相机数量增加，DeepGaitLab 的性能提升", "INFERENCE")
    assert "数值更高" not in new and new.endswith(ANNOT_INFER)
    assert wording.gate("DeepGaitLab 远远优于所有方法", "无比较词的依据", "PAPER")[0] is None     # word not in source -> reject
    assert wording.gate("DeepGaitLab 的 ICC 优于 OpenCap", "ICC 箱线图")[0] == "DeepGaitLab 的 ICC 数值高于 OpenCap"


def test_r2_judge_limitation_phrase_and_verbatim_comparative():
    from litreader.analysis import wording_judge as WJ
    assert not WJ.COMPARATIVE.search(WJ.NEUTRAL.sub("", "其他病理动作与更严重功能障碍人群的适用性仍待验证"))
    cap = "彩色标记表示用于分析的具体子样本：红色表示最小双相机配置，蓝色表示六相机配置。"
    assert WJ.verbatim_comparative("图9A中红色标记表示最小双相机配置", cap)
    assert not WJ.verbatim_comparative("OpenCap（手动校准）RMSD最高", "采用自动校准的 DeepGaitLab 优于采用棋盘格校准的 OpenCap")
