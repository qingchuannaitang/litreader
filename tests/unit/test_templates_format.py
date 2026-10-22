"""Stage 6: template format, lint, untrusted-data detection, built-ins, renderer byte-identity."""
import hashlib
import sys
from pathlib import Path

import pytest

from litreader.templates import builtin, fm, sanitize
from litreader.templates.format import parse_template

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "templates"
GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
ROOT = Path(__file__).resolve().parents[2]


def P(name):
    return parse_template((FIX / name).read_bytes(), name)


def test_frontmatter_subset_ok():
    d = fm.parse('a: 1\nb: "x: y"\nc: [p, q]\nd:\n  e: [1, 2]\n  f: true\ng:\n  - {id: s1, title: 一、背景, blocks: [x, y]}\n  - z\n')
    assert d == {"a": 1, "b": "x: y", "c": ["p", "q"], "d": {"e": [1, 2], "f": True},
                 "g": [{"id": "s1", "title": "一、背景", "blocks": ["x", "y"]}, "z"]}


@pytest.mark.parametrize("bad", ["a: &x 1", "a: *x", "a: !!python/object x", "a: |\n  t", "a: 1\na: 2",
                                 "a:\n  b:\n    c: 1", "a: {b: {c: 1}}", "a: [[1]]", "\ta: 1", "a: 1\n---\nb: 2"])
def test_frontmatter_rejects(bad):
    with pytest.raises(fm.FrontMatterError):
        fm.parse(bad)


def test_builtins_valid_and_pinned():
    for tid in builtin.all_ids():
        t = builtin.load(tid)
        assert t.status_hint() == "ACTIVE" and not t.warnings, (tid, t.review, t.warnings)
        assert hashlib.sha256(builtin.raw(tid)).hexdigest() == builtin.SHA256[tid] == t.sha256
    assert builtin.load("overview.v2").role == "OVERVIEW"
    mods = [builtin.load(t) for t in builtin.all_ids() if t.startswith("module.")]
    covered = {s for m in mods for s in m.study_types}
    assert {"rct", "diagnostic_accuracy", "prediction_model", "systematic_review", "methods_technical"} <= covered


def test_builtin_tamper_stops(monkeypatch):
    from litreader.errors import Stop
    monkeypatch.setitem(builtin.SHA256, "main.general", "0" * 64)
    with pytest.raises(Stop):
        builtin.raw("main.general")


def test_spec_appendix_a_headings_verbatim():
    spec_a = ["一、研究背景与科学问题", "二、研究设计、对象及技术路线", "三、实验任务、指标及统计方法", "四、核心结果与阴性结果",
              "五、作者结论与独立科研评价", "六、方法学评价、局限与UNKNOWN", "七、与当前科研项目的关系／通用科研价值",
              "八、待解决问题与我的批注（用户区受保护）", "九、原文证据、附录及技术档案链接"]
    t = builtin.load("main.spec_appendix_a")
    assert [s.title for s in t.sections if s.level == 2] == spec_a
    assert t.priority < builtin.load("main.general").priority      # general stays the fallback


def test_overview_headings_follow_appendix_b():
    t = builtin.load("overview.v2")
    assert [s.title for s in t.sections][0] == "精读统计（真实已核验，按独立论文去重）" and len(t.sections) == 6


def test_malicious_template_needs_review_and_hints_cleaned():
    t = P("malicious_injection.md")
    assert t.status_hint() == "NEEDS_REVIEW"
    codes = " ".join(t.review)
    for c in ("INJECTION_PHRASE", "COMMAND", "URL", "SCOPE", "LOWER_STANDARD", "HTML", "TEMPLATER"):
        assert c in codes, c
    assert any("预览正文" in w for w in t.warnings)
    for s in t.sections:
        assert "http" not in s.hint and "<script" not in s.hint and "<%" not in s.hint and "{{" not in s.hint
        assert "curl" not in s.hint or "`" not in s.hint


def test_rejections():
    assert P("fixture_marked.md").status_hint() == "REJECTED"
    assert P("yaml_anchor.md").status_hint() == "REJECTED"
    assert parse_template("---\nid: x\n---\n".encode("gbk") + "中文".encode("gbk"), "g.md").status_hint() == "REJECTED"
    assert parse_template(b"x" * (64 * 1024 + 1), "big.md").status_hint() == "REJECTED"
    assert parse_template(b"\x00abc", "bin.md").status_hint() == "REJECTED"
    t = parse_template(b"---\nlitreader_template: 1\nid: test.thing\ntitle: t\nrole: main\n---\n", "t.md")
    assert t.status_hint() == "REJECTED"


def test_no_frontmatter_needs_review():
    t = P("no_frontmatter.md")
    assert t.missing_front_matter and t.status_hint() == "NEEDS_REVIEW"


def test_zero_width_and_bidi():
    t = P("zero_width.md")
    assert t.status_hint() == "NEEDS_REVIEW" and any("INVISIBLE" in r for r in t.review)
    assert t.sections[0].title == "一、背景" and "\u202e" not in t.title


def test_unknown_block_and_bad_vocab():
    t = parse_template("---\nlitreader_template: 1\nid: user.x\ntitle: x\nrole: main\napplies_to:\n  study_types: [rct, astrology]\n"
                       "sections:\n  - {id: s1, title: 一, blocks: [paragraphs, run_shell]}\n---\n".encode(), "x.md")
    assert t.status_hint() == "NEEDS_REVIEW" and t.study_types == ["rct"] and t.sections[0].blocks == ["paragraphs"]


def test_sanitize_clean():
    s = sanitize.clean("看 [链接](https://x.y) 和 [[内部]] `rm -rf /` <b>粗</b> {{x}} <% y %> www.evil.cn \u200b完", 300)
    assert "http" not in s and "rm" not in s and "<b>" not in s and "{{" not in s and "www" not in s and "\u200b" not in s
    assert sanitize.clean_title("## 标题 | [[x]] #a") == "标题 x a"


def test_diag_main_hints_and_extra_section():
    t = P("diag_main.md")
    assert t.status_hint() == "ACTIVE"
    sec = {s.id: s for s in t.sections}
    assert "分开写" in sec["s4"].hint and sec["perf"].data is None and "AUC" in sec["perf"].hint


# ---------- renderer byte-identity ----------
sys.path.insert(0, str(Path(__file__).parent))


def _fx():
    import test_note_v2 as T
    return T


def test_golden_fixture_renders_identical():
    T = _fx()
    from litreader.analysis.validator_v2 import validate_v2
    obs = {"Fig1": {"finding": "共 181 人筛查", "numbers": ["181"], "unreadable": "", "model": "vm"}}
    assert T._render(validate_v2(T.good(), T.BLOCKS, T.MAN), None) == (GOLD / "fixture_novision.md").read_text()
    assert T._render(validate_v2(T.good(), T.BLOCKS, T.MAN), obs) == (GOLD / "fixture_vision.md").read_text()
    cross = {"Fig1": [{"claim": "共 79 名纳入", "verdict": "CONSISTENT", "page": 2, "quote": "纳入 79 名", "block_id": "b2", "reason": ""},
                      {"claim": "无差异", "verdict": "CONTRADICTED", "page": 2, "quote": "膝伸展角增加", "block_id": "b2", "reason": "冲突"}]}
    md = T.render(validate_v2(T.good(), T.BLOCKS, T.MAN), blocks=T.BLOCKS, manifest=T.MAN, vision_obs=obs,
                  figure_paths={"Fig1": ["_图表/K/Fig1-1.jpg"]}, attachment_key="7M6C5QRN", parent_key="K", e_level="E3",
                  translation_notice=None, link_mechanism_verified=False, read_date="2026-10-17",
                  evidence_link="_证据档案/K/x——证据档案", model_info={"text": "m", "vision": "vm"}, crosscheck=cross,
                  zotero_meta={"authors": "Zhong 等", "journal": "J", "title_en": "T", "year": "2021"})
    assert md == (GOLD / "fixture_cross.md").read_text()
    # explicit main.general == default
    assert T.render(validate_v2(T.good(), T.BLOCKS, T.MAN), template=builtin.load("main.general"), **_kw(T)) == \
        (GOLD / "fixture_novision.md").read_text()


def _kw(T):
    return dict(blocks=T.BLOCKS, manifest=T.MAN, vision_obs=None, figure_paths={"Fig1": ["_图表/K/Fig1-1.jpg"]},
                attachment_key="7M6C5QRN", parent_key="K", e_level="E3", translation_notice="中文译本。",
                link_mechanism_verified=True, read_date="2026-10-17", evidence_link="_证据档案/K/x——证据档案",
                model_info={"text": "m", "vision": "vm"})


def test_zhong_replay_main_general_byte_identical():
    if not (ROOT / "spikes" / "zhong_render_inputs.py").exists():
        pytest.skip("dev-only spike not in the release tree")
    sys.path.insert(0, str(ROOT / "spikes"))
    import zhong_render_inputs as Z
    if not Z.available():
        pytest.skip("Zhong spike data not on this machine")
    from litreader.render.l2_note_v2 import render
    v2, kw = Z.build()
    out = render(v2, template=builtin.load("main.general"), **kw)
    gold = (ROOT / ".spike_data" / "golden" / "zhong_main_general.md").read_text()
    assert out == gold, "main.general must reproduce the pre-Stage-6 renderer byte for byte"


def test_spec_appendix_a_render_and_gates():
    T = _fx()
    from litreader.analysis.validator_v2 import validate_v2
    from litreader.render import protected_zone
    md = T.render(validate_v2(T.good(), T.BLOCKS, T.MAN), template=builtin.load("main.spec_appendix_a"), **_kw(T))
    for h in ("## 一、研究背景与科学问题", "## 六、方法学评价、局限与UNKNOWN", "## 八、待解决问题与我的批注（用户区受保护）",
              "## 九、原文证据、附录及技术档案链接", "[[#一、研究背景与科学问题|十分钟读懂研究]]",
              "[[#五、作者结论与独立科研评价|深度科研分析]]", "> [!note] 阅读约定", "按对结论、临床适用性"):
        assert h in md, h
    assert "## 一、为什么读这篇" not in md and "## 十、" not in md
    assert md.count(protected_zone.BEGIN) == 1 and "![[_图表/K/Fig1-1.jpg|760]]" in md
    # same facts as main.general: every PAPER page link of the general note is present
    import re
    gen = T._render(validate_v2(T.good(), T.BLOCKS, T.MAN), None)
    links = lambda s: sorted(re.findall(r"\]\((zotero://[^)]+)\)", s))
    assert links(md) == links(gen)
