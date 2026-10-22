"""Stage 6: study-type classification (verbatim evidence + keyword cross-check + Zotero tag), selection tiers (T08),
modules without duplicate sections (T07), gates re-inserted, sandboxed prompt data (T06), session confirm/override."""
import json
import shutil
from pathlib import Path

import pytest

from litreader.analysis.validator_v2 import validate_v2
from litreader.llm.config import parse_config
from litreader.parse.blocks import Block
from litreader.templates import builtin, classify as C, layout, select as S
from litreader.templates.format import parse_template
from litreader.templates.prompt import prompt_suffix, validation_spec
from litreader.templates.registry import Registry

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "templates"
CHAIN = parse_config({"providers": {"j": {"protocol": "openai_compatible", "base_url": "https://x.invalid", "model": "judge-m",
                                          "key_env": "K", "json_mode": True}}, "stations": {"judge": ["j"]}}).chain("judge")
ABSTRACTS = {
    "rct": "Methods: In this randomized controlled trial, 120 patients were randomly assigned to exercise or usual care.",
    "diagnostic_accuracy": "We evaluated the sensitivity and specificity of gait speed for detecting MCI; ROC analysis gave AUC 0.81. Sensitivity was 76%.",
    "methods_technical": "We propose a deep learning algorithm (a neural network) for gait segmentation and compare it to baseline algorithms.",
    "systematic_review": "This systematic review and meta-analysis followed PRISMA; 23 studies were pooled in a meta-analysis.",
}


def blocks_for(text):
    return [Block(kind="title", physical_page=1, bbox_norm=None, text="Title", order=0),
            Block(kind="text", physical_page=2, bbox_norm=None, text=text, order=1)]


def tx_answer(obj, seen=None):
    def tx(url, headers, body, timeout):
        if seen is not None:
            seen.append(json.loads(body))
        return 200, json.dumps({"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}],
                                "usage": {"prompt_tokens": 1400, "completion_tokens": 90}}).encode()
    return tx


def test_classify_verbatim_quote_required():
    b = blocks_for(ABSTRACTS["rct"])
    ok = C.classify(b, title="T", chain=CHAIN, transport=tx_answer({"study_type": "rct", "confidence": 0.9, "reason": "随机分配",
                                                                 "quote": "120 patients were randomly assigned", "block_id": "b1"}), env={"K": "k"})
    assert ok["study_type"] == "rct" and ok["confidence"] == 0.9 and ok["page"] == 2 and not ok["ambiguous"]
    assert ok["keyword_check"] == "agree" and ok["run"]["purpose"] == "study_type"
    fake = C.classify(b, title="T", chain=CHAIN, transport=tx_answer({"study_type": "rct", "confidence": 0.95,
                                                                   "quote": "double-blind placebo", "block_id": "b1"}), env={"K": "k"})
    assert fake["confidence"] == 0.0 and fake["ambiguous"] and "无依据" in fake["reason"]


def test_classify_keyword_conflict_lowers_confidence():
    b = blocks_for(ABSTRACTS["systematic_review"])
    r = C.classify(b, title="T", chain=CHAIN, transport=tx_answer({"study_type": "cohort", "confidence": 0.9,
                                                                "quote": "23 studies were pooled", "block_id": "b1"}), env={"K": "k"})
    assert r["keyword_check"] == "conflict" and r["confidence"] <= 0.5 and r["ambiguous"]


def test_classify_zotero_tag_wins_without_model_call():
    seen = []
    r = C.classify(blocks_for(ABSTRACTS["rct"]), title="T", zotero_tags=["随机对照试验", "步态"], chain=CHAIN,
                   transport=tx_answer({}, seen), env={"K": "k"})
    assert r["source"] == "zotero_tag" and r["study_type"] == "rct" and seen == [] and r["run"] is None


def test_classify_model_failure_falls_back_and_is_ambiguous():
    def boom(*a):
        raise OSError("down")
    r = C.classify(blocks_for(ABSTRACTS["diagnostic_accuracy"]), title="T", chain=CHAIN, transport=boom, env={"K": "k"})
    assert r["ambiguous"] and r["source"] in ("keywords", "none")
    r2 = C.classify(blocks_for(ABSTRACTS["rct"]), title="T", chain=CHAIN,
                    transport=tx_answer({"study_type": "astrology", "confidence": 1}), env={"K": "k"})
    assert r2["ambiguous"] and r2["study_type"] in ("rct", "other")


def test_prompt_contains_no_template_text():
    seen = []
    C.classify(blocks_for(ABSTRACTS["rct"]), title="T", chain=CHAIN, transport=tx_answer({}, seen), env={"K": "k"})
    assert "[b1|p2]" in seen[0]["messages"][1]["content"] and len(seen[0]["messages"][1]["content"]) < C.CTX_CHARS + 200


@pytest.fixture
def reg(tmp_path):
    lib = tmp_path / "模板库"; lib.mkdir()
    shutil.copy(FIX / "diag_main.md", lib / "diag.md")
    shutil.copy(FIX / "malicious_injection.md", lib / "evil.md")
    r = Registry(tmp_path / "reg", lib)
    r.refresh()
    return r


def study(t, conf=0.9, amb=False, sec=()):
    return {"study_type": t, "secondary": list(sec), "confidence": conf, "ambiguous": amb}


def test_T08_selection_by_type(reg):
    snap = reg.snapshot()
    ch = S.choose(reg, snap, study("diagnostic_accuracy"))
    assert ch.main["id"] == "user.diag_main" and ch.tier == 2 and [m["id"] for m in ch.modules] == ["module.diagnostic"]
    ch = S.choose(reg, snap, study("rct"))
    assert ch.main["id"] == "main.general" and ch.tier == 5 and [m["id"] for m in ch.modules] == ["module.rct"]
    ch = S.choose(reg, snap, study("methods_technical"))
    assert ch.main["id"] == "main.general" and [m["id"] for m in ch.modules] == ["module.methods"]
    ch = S.choose(reg, snap, study("systematic_review"))
    assert [m["id"] for m in ch.modules] == ["module.sysreview"]
    ch = S.choose(reg, snap, study("prediction_model"))
    assert ch.main["id"] == "user.diag_main" and {m["id"] for m in ch.modules} == {"module.diagnostic", "module.methods"}
    ids = {r["id"] for r, _, _ in ch.candidates}
    assert "user.evil" not in ids and "overview.v2" not in ids        # NEEDS_REVIEW / overview never in the main pool
    ch = S.choose(reg, snap, study("cross_sectional"))
    assert ch.main["id"] == "main.general" and not ch.modules and "没有适用于横断面研究" in ch.reason


def test_priority_tiers_prefer_and_default(reg):
    snap = reg.prefer("main.spec_appendix_a")                           # user default (tier 4) beats general (5)
    assert S.choose(reg, snap, study("cohort")).main["id"] == "main.spec_appendix_a"
    assert S.choose(reg, snap, study("diagnostic_accuracy")).main["id"] == "user.diag_main"   # specialised (2) beats default
    snap = reg.prefer("main.spec_appendix_a", "diagnostic_accuracy")    # type first choice (1) beats specialised
    ch = S.choose(reg, snap, study("diagnostic_accuracy"))
    assert ch.main["id"] == "main.spec_appendix_a" and ch.tier == 1
    ch = S.choose(reg, snap, study("diagnostic_accuracy"), requested="main.general")   # named this run (0)
    assert ch.main["id"] == "main.general" and ch.tier == 0 and not ch.ambiguous


def test_tie_between_specialised_is_ambiguous(reg, tmp_path):
    lib = reg.library
    (lib / "diag2.md").write_text((FIX / "diag_main.md").read_text("utf-8").replace("user.diag_main", "user.diag_b")
                                  .replace("诊断与预测模型精读", "另一份诊断模板"), "utf-8")
    reg.refresh()
    ch = S.choose(reg, reg.snapshot(), study("diagnostic_accuracy"))
    assert ch.ambiguous and ch.tier == 2


def test_pinned_old_version_is_used(reg):
    lib = reg.library
    (lib / "diag.md").write_text((lib / "diag.md").read_text("utf-8").replace("priority: 70", "priority: 75"), "utf-8")
    snap, _, _ = reg.refresh()
    assert S.choose(reg, snap, study("diagnostic_accuracy")).main["registry_version"] == 2
    snap = reg.rollback("user.diag_main")
    assert S.choose(reg, snap, study("diagnostic_accuracy")).main["registry_version"] == 1


def test_T07_modules_no_duplicate_sections_and_one_main(tmp_path):
    rct = builtin.load("module.rct")
    dup = parse_template((FIX / "conflict_module.md").read_bytes(), "dup.md")
    lay = layout.build(builtin.load("main.general"), [rct, dup])
    assert [m.id for m in lay.modules] == ["module.rct"] and any("user.dup_module" in w for w in lay.warnings)
    lay = layout.build(builtin.load("main.general"), [builtin.load("main.spec_appendix_a")])
    assert lay.modules == [] and any("不是专业模块" in w for w in lay.warnings)


def test_gates_reinserted_for_minimal_template():
    t = parse_template("---\nlitreader_template: 1\nid: user.min\ntitle: 极简\nrole: main\napplies_to:\n  study_types: [any]\n"
                       "header_blocks: [three_minute]\nsections:\n  - {id: s4, title: 只要结果, blocks: [paragraphs]}\n"
                       "  - {id: x, title: 我的批注, blocks: [protected_zone, protected_zone]}\n---\n".encode(), "min.md")
    lay = layout.build(t)
    blocks = [b for s in lay.sections for b in s.blocks]
    assert "reading_convention" in lay.header
    assert blocks.count("protected_zone") == 1 and blocks.count("unknown_top") == 1 and blocks.count("evidence_nav") == 1
    assert {s.data for s in lay.sections} >= {"s1", "s2", "s3", "s5", "s6", "s7", "s8", "s9", "s10"}
    assert len(lay.warnings) >= 5


def _fx():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
    import test_note_v2 as T
    return T


def test_minimal_template_note_keeps_facts_unknowns_and_protected_zone():
    T = _fx()
    from litreader.render import protected_zone
    t = parse_template("---\nlitreader_template: 1\nid: user.min\ntitle: 极简\nrole: main\napplies_to:\n  study_types: [any]\n"
                       "sections:\n  - {id: s4, title: 只要结果, blocks: [paragraphs]}\n---\n".encode(), "min.md")
    v = validate_v2(T.good(), T.BLOCKS, T.MAN)
    md = T.render(v, template=t, **_kw(T))
    gen = T._render(validate_v2(T.good(), T.BLOCKS, T.MAN), None)
    import re
    links = lambda s: sorted(re.findall(r"\]\((zotero://[^)]+)\)", s))
    assert links(md) == links(gen)                                     # no verified content dropped
    assert "> [!note] 阅读约定" in md and "按对结论、临床适用性" in md and md.count(protected_zone.BEGIN) == 1
    assert "![[_图表/K/Fig1-1.jpg|760]]" in md                       # every real figure still shown


def _kw(T):
    return dict(blocks=T.BLOCKS, manifest=T.MAN, vision_obs=None, figure_paths={"Fig1": ["_图表/K/Fig1-1.jpg"]},
                attachment_key="7M6C5QRN", parent_key="K", e_level="E3", translation_notice="中文译本。",
                link_mechanism_verified=True, read_date="2026-10-17", evidence_link="_证据档案/K/x——证据档案",
                model_info={"text": "m", "vision": "vm"})


def test_T06_malicious_hints_sandboxed_in_prompt_and_absent_from_note():
    T = _fx()
    evil = parse_template((FIX / "malicious_injection.md").read_bytes(), "evil.md")
    suf = prompt_suffix(evil, [])
    assert suf and "不可信" in suf and "以上文规则为准" in suf
    data = json.loads(json.loads(suf.split("TEMPLATE_DATA = ", 1)[1]))
    flat = json.dumps(data, ensure_ascii=False)
    for bad in ("http", "evil.example", "<script", "<%", "{{", "`"):
        assert bad not in flat, bad
    assert suf.index("TEMPLATE_DATA = ") > suf.index("不得执行")          # program rules before template data
    md = T.render(validate_v2(T.good(), T.BLOCKS, T.MAN), template=evil, **_kw(T))
    assert "evil.example" not in md and "忽略之前" not in md and "<script" not in md
    assert "UNKNOWN" in md and "> [!note] 阅读约定" in md


def test_builtin_general_and_spec_a_do_not_change_writer_prompt():
    assert prompt_suffix(builtin.load("main.general"), []) is None
    assert prompt_suffix(builtin.load("main.spec_appendix_a"), []) is None
    assert prompt_suffix(builtin.load("main.general"), [builtin.load("module.rct")]) is not None


def test_module_fields_validated_and_rendered():
    T = _fx()
    from litreader.render import protected_zone
    rct = builtin.load("module.rct")
    spec = validation_spec(builtin.load("main.general"), [rct])
    a = T.good()
    a["module_fields"] = {"randomization": T.S("纳入 79 名受试者随机分组", "PAPER"),       # 79 is in b2 -> ok
                          "primary_outcome_effect": T.S("效应量 0.99", "PAPER"),            # 0.99 not in basis -> rejected
                          "blinding": T.S("未报告盲法，评估者可能知晓分组", "INFERENCE"),
                          "rm_rf": T.S("x", "PAPER")}                                      # undeclared -> rejected
    a["extra_sections"] = {"mod_rct": {"paragraphs": [T.S("整体偏倚风险中等", "INFERENCE")]}, "evil": {"paragraphs": []}}
    v = validate_v2(a, T.BLOCKS, T.MAN, spec)
    assert set(v.data["module_fields"]) == {"randomization", "blinding"}
    assert {r["where"] for r in v.rejected} >= {"module.primary_outcome_effect", "module.rm_rf", "extra.evil"}
    md = T.render(v, modules=[rct], **_kw(T))
    sec7 = md.split("## 七、")[1].split("## 八、")[0]
    assert "### RCT/干预研究专项评价（专业模块）" in sec7 and "**随机化方法：**" in sec7
    assert "UNKNOWN）：** 分配隐藏、失访与意向性分析、主要结局效应量" in sec7 and sec7.count("主要结局效应量") == 1 and "整体偏倚风险中等（INFERENCE）" in sec7
    assert md.count(protected_zone.BEGIN) == 1


def test_g8_module_paragraph_repeating_a_field_is_dropped():
    T = _fx()
    rct = builtin.load("module.rct")
    spec = validation_spec(builtin.load("main.general"), [rct])
    a = T.good()
    a["module_fields"] = {"randomization": T.S("纳入 79 名受试者随机分组", "PAPER")}
    a["extra_sections"] = {"mod_rct": {"paragraphs": [T.S("随机化方法为纳入 79 名受试者后随机分组", "INFERENCE"),
                                                      T.S("纳入 79 名受试者并随机分组进行比较", "INFERENCE"),
                                                      T.S("整体偏倚风险中等", "INFERENCE")]}}
    v = validate_v2(a, T.BLOCKS, T.MAN, spec)
    md = T.render(v, modules=[rct], **_kw(T))
    sec7 = md.split("## 七、")[1].split("## 八、")[0]
    assert "随机化方法为纳入" not in sec7 and "并随机分组进行比较" not in sec7    # prefix / wording overlap
    assert "整体偏倚风险中等（INFERENCE）" in sec7 and sec7.count("79") == 1
    assert sum(d.get("reason", "").endswith("(G8-5)") for d in v.duplicates) == 2


def test_g9_module_paragraph_duplicate_renders_in_evidence():
    from litreader.render.l2_note_v2 import render_evidence
    T = _fx()
    rct = builtin.load("module.rct")
    spec = validation_spec(builtin.load("main.general"), [rct])
    a = T.good()
    a["module_fields"] = {"randomization": T.S("纳入 79 名受试者随机分组", "PAPER")}
    a["extra_sections"] = {"mod_rct": {"paragraphs": [T.S("随机化方法为纳入 79 名受试者后随机分组", "INFERENCE")]}}
    v = validate_v2(a, T.BLOCKS, T.MAN, spec)
    T.render(v, modules=[rct], **_kw(T))
    assert any("field" not in d for d in v.duplicates)
    ev = render_evidence(v, raw={}, blocks=T.BLOCKS, manifest=T.MAN, attachment_key="K", title="t",
                         runs=[], vision_runs=[], e_report={})
    assert "module.mod_rct（模块段落）" in ev or "（模块段落）" in ev
    assert v.stats["duplicates"] == len(v.duplicates)
