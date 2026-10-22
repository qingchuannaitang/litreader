"""Mock layer: judge context (threshold + denominators), vague-claim gate, comparative wording judge, malformed UNKNOWN."""
import json

from litreader.analysis.crosscheck import judge, paper_context, vague_supported
from litreader.analysis.unknown_rank import malformed, rank
from litreader.analysis.validator_v2 import validate_v2
from litreader.analysis import wording_judge
from litreader.llm.config import parse_config
from litreader.parse.blocks import Block


def B(o, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o, **kw)


BLOCKS = [B(0, "title", 1, "研究"), B(1, "title", 3, "统计分析"),
          B(2, "text", 3, "MANCOVA 中 $p < 0 . 0 0 2$ 认为有统计学意义。共招募 82 名签署知情同意；3 名未能完成步态分析，最终 79 名进入分析。"),
          B(3, "title", 5, "结果"),
          B(4, "text", 5, "膝 ROM 组间 F=4.77，p=0.012。膝关节角度可能比时空参数更敏感。MCI 膝伸展角显著增加（p<0.0001）。"),
          B(5, "figure", 4, "", caption="图 1 | 招募流程图。", img_path="images/f1.jpg")]
FIG = {"id": "Fig1", "kind": "figure", "number": "1", "caption": "图 1 | 招募流程图。", "flags": [],
       "parts": [{"img_path": "images/f1.jpg", "physical_page": 4, "order": 5}]}
CFG = parse_config({"providers": {"j": {"protocol": "openai_compatible", "base_url": "https://j.example", "model": "jm",
                                        "key_env": "JK", "json_mode": True}}, "stations": {"judge": ["j"]}})
ENV = {"JK": "k"}


def fake(payload):
    seen = []

    def t(url, h, body, timeout):
        seen.append(json.loads(body))
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}],
                                "usage": {"prompt_tokens": 11, "completion_tokens": 3}}).encode()
    return t, seen


def test_paper_context_threshold_and_denominators():
    c = paper_context(BLOCKS)
    assert c["thresholds"][0]["is_rule"] and "0.002" in c["thresholds"][0]["text"]
    assert any("82 名" in d["text"] for d in c["denominators"]) and any("79 名" in d["text"] for d in c["denominators"])


def test_judge_prompt_carries_context_and_rules():
    t, seen = fake({"claims": [{"claim": "膝ROM三组间无显著差异", "verdict": "CONSISTENT", "block_id": "b4",
                                "quote": "膝 ROM 组间 F=4.77，p=0.012", "reason": "p>0.002"}]})
    out, info = judge(FIG, {"finding": "膝ROM三组间无显著差异"}, BLOCKS, CFG.chain("judge"), t, ENV)
    sys_msg, user = seen[0]["messages"][0]["content"], seen[0]["messages"][1]["content"]
    assert "本文自己的显著性阈值" in sys_msg and "分配 23/34/25、分析 22/33/24 不矛盾" in sys_msg and "各组各 1 人失败" in sys_msg
    assert "本文阈值原句" in user and "0.002" in user and "人数/分母原句" in user
    assert out[0]["verdict"] == "CONSISTENT"


def test_vague_claim_gate():
    assert vague_supported("图为招募流程图（CONSORT类）", "图 1 | 招募流程图。", "图 1 | 招募流程图。") == "term 'CONSORT' not in source"
    assert vague_supported("这是一个复杂的图", "招募流程图", "招募流程图") is not None
    assert vague_supported("图为招募流程图", "图 1 | 招募流程图。", "图 1 | 招募流程图。") is None
    t, _ = fake({"claims": [{"claim": "图为招募流程图（CONSORT类）", "verdict": "CONSISTENT", "block_id": "b5",
                             "quote": "图 1 | 招募流程图。", "reason": ""}]})
    out, info = judge(FIG, {"finding": "x"}, BLOCKS, CFG.chain("judge"), t, ENV)
    # G7-12: a claim that only restates the caption is not a finding at all (dropped, recorded)
    assert (out and out[0]["verdict"] == "UNVERIFIABLE" and "CONSORT" in out[0]["gate"]) or \
        info["excluded_caption_boilerplate"][0]["claim"].startswith("图为招募流程图")


def S(text, label="PAPER", ids=("b4",)):
    return {"text": text, "label": label, "basis_block_ids": list(ids), "link_label": "结果"}


def _v2():
    a = {"meta": {}, "three_minute": {"key_result": S("MCI 膝伸展角显著更大"), "value": S("膝角可能比时空参数更敏感", "INFERENCE"),
                                      "caution": S("该指标表现最好", "INFERENCE"), "what": S("膝 ROM 更差", "INFERENCE")},
         "sections": {"s4": {"paragraphs": [S("膝关节角度可能比时空参数更敏感。"), S("普通句子")]}}}
    return validate_v2(a, BLOCKS, [])


def test_wording_judge_verdicts_and_gates():
    v = _v2()
    cands = wording_judge.candidates(v.data, {})
    texts = {c["text"]: c["id"] for c in cands}
    assert "普通句子" not in texts
    J = {texts["MCI 膝伸展角显著更大"]: {"verdict": "TESTED", "block_id": "b4", "quote": "MCI 膝伸展角显著增加（p<0.0001）"},
         texts["膝角可能比时空参数更敏感"]: {"verdict": "UNSUPPORTED", "reason": "无比较检验"},
         texts["膝关节角度可能比时空参数更敏感。"]: {"verdict": "AUTHOR_STATEMENT_UNTESTED", "block_id": "b4",
                                                 "quote": "膝关节角度可能比时空参数更敏感"}}
    if "该指标表现最好" in texts:   # rejected earlier by deterministic gate? (no test word in b4? b4 has p -> kept)
        J[texts["该指标表现最好"]] = {"verdict": "TESTED", "block_id": "b4", "quote": "膝伸展角"}   # no statistic -> gate
    t, seen = fake({"items": [{"id": k, **x} for k, x in J.items()]})
    info = wording_judge.apply(v, BLOCKS, {}, CFG.chain("judge"), t, ENV)
    tm = v.data["three_minute"]
    assert tm["key_result"]["text"] == "MCI 膝伸展角显著更大"                                      # TESTED kept
    assert tm["value"] is None                                                                 # 更敏感: no safe rewrite -> rejected
    p = v.data["sections"]["s4"]["paragraphs"]
    assert p[0]["text"].endswith("（作者表述，无对应检验）") and len(p) == 2
    if "该指标表现最好" in texts:
        assert tm["caution"] is None      # gated TESTED -> UNSUPPORTED; no metric named -> no "数值最高" rewrite (review 2)
    assert info["status"] == "OK" and info["usage"]["prompt_tokens"] == 11
    assert any(w.get("rule", "").startswith("judge: unsupported comparative, no safe rewrite") for w in v.wording)
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_wording_judge_fail_closed():
    v = _v2()
    info = wording_judge.apply(v, BLOCKS, {}, CFG.chain("judge"), lambda *a: (500, b""), ENV)
    assert info["status"].startswith("JUDGE_FAILED")
    assert v.data["three_minute"]["key_result"] is None        # 更大: unsupported, no rewrite -> removed
    p = [x["text"] for x in v.data["sections"]["s4"]["paragraphs"]]
    # judge failed, but the comparative is verbatim the paper's wording -> kept, annotated (review 2)
    assert p == ["膝关节角度可能比时空参数更敏感。（作者表述，无对应检验）", "普通句子"]


def test_wording_judge_on_vision_claims():
    v = _v2()
    cross = {"Fig1": [{"claim": "MCI 着地角最小", "verdict": "CONSISTENT", "block_id": "b4", "quote": "MCI", "page": 5}]}
    t, _ = fake({"items": []})
    wording_judge.apply(v, BLOCKS, cross, CFG.chain("judge"), t, ENV)
    assert cross["Fig1"][0]["verdict"] == "UNVERIFIABLE"


def test_malformed_unknown():
    u = {"item": "NC组年龄范围", "why": "正文称NC年龄范围64–84岁，但表1报告72.73（5.30），二者不一致"}
    assert "range" in malformed(u)
    r = rank([u, {"item": "左侧无显著效应原因", "why": "未解释"}])
    assert r[-1]["malformed"] and r[-1]["impact"] == -1 and r[0]["item"] == "左侧无显著效应原因"
    assert malformed({"item": "年龄", "why": "均值 72.1±5.3 与 71.9±5.0 不一致"}) is None


def test_significance_override_rom():
    from litreader.analysis.crosscheck import significance_override
    thr = paper_context(BLOCKS)["thresholds"]
    c = {"claim": "ROM三组差异不显著", "verdict": "CONTRADICTED", "quote": "膝 ROM 组间 F=4.77，p=0.012"}
    assert significance_override(c, thr)["verdict"] == "CONSISTENT"           # only rule is 0.002 -> 0.012 above all
    thr2 = thr + [{"is_rule": True, "text": "这些检验中 p < 0.05 认为有统计学意义"}]
    assert significance_override(c, thr2)["verdict"] == "UNVERIFIABLE"        # between 0.002 and 0.05
    real = {"claim": "伸展角无显著差异", "verdict": "CONTRADICTED", "quote": "F = 8.77, p < 0.0001"}
    assert significance_override(real, thr2)["verdict"] == "CONTRADICTED"     # true conflict (Fig2 v2) stays
    pos = {"claim": "差异显著", "verdict": "CONTRADICTED", "quote": "p=0.3"}
    assert significance_override(pos, thr2)["verdict"] == "CONTRADICTED"      # only negative claims are overridden


def test_significance_override_table_row():
    from litreader.analysis.crosscheck import significance_override
    thr = [{"is_rule": True, "text": "MANCOVA 中 p < 0.002 认为有统计学意义"}, {"is_rule": True, "text": "p < 0.05 认为有统计学意义"}]
    rom = {"claim": "ROM三组差异不显著", "verdict": "CONTRADICTED",
           "quote": "Knee ROM (degree), mean (SD) | 64.58 (5.51) | 62.74 (5.64) | 59.28 (5.57) | 4.77 (0.012) | 5.30 (0.011)"}
    assert significance_override(rom, thr)["verdict"] == "UNVERIFIABLE"
    ext = {"claim": "伸展角无显著差异", "verdict": "CONTRADICTED", "quote": "Knee peak extension | -0.59 (4.54) | 8.77 (<0.0001)"}
    assert significance_override(ext, thr)["verdict"] == "CONTRADICTED"


def test_recommendation_phrasing_not_comparative():
    from litreader.analysis.wording_judge import COMPARATIVE, NEUTRAL
    for t in ("需更大样本验证", "需要更多研究", "需更长期的随访", "有待更深入探讨"):
        assert not COMPARATIVE.search(NEUTRAL.sub("", t)), t
    assert COMPARATIVE.search(NEUTRAL.sub("", "MCI组步速更慢，需更大样本验证"))
