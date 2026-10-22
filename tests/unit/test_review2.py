"""Second DeepGaitLab Mac run (aa00d72) review fixes — offline, verbatim excerpts from the new evidence archive."""
from litreader.analysis.latex import clean
from litreader.analysis.validator import quote_in


def test_r2_latex_spaced_letters_tilde_and_unknown_commands():
    raw = r"ACLR 参与者在髋屈/伸 $\mathrm { ( O p e n C a p ~ 1 3 . 4 \pm 7 . 9 ^ { \circ } ~ v s . ~ 7 . 3 \pm 4 . 3 ^ { \circ } , } p = 0 . 0 0 0 1$ ；"
    out = clean(raw)
    assert "OpenCap 13.4±7.9°" in out and "vs. 7.3±4.3°" in out and "~" not in out and "O p e n" not in out
    icc = clean(r"$( \mathrm { I C C } ; ~ 0 . 9 1 \pm 0 . 0 4 \mathrm { v s } . 0 . 8 3 \pm 0 . 0 9 , ~ p < 0 . 0 0 0 1 )$")
    assert "ICC" in icc and "vs. 0.83±0.09" in icc
    assert "scriptscriptstyle" not in clean(r"$\mathrm { T h e i a 3 D } \vec { \scriptscriptstyle { p } }$")
    assert clean(r"$p < 0 . 0 0 0 1 \ \AA$") == "p < 0.0001" and clean(r"$\Delta x$") == "Δ x"
    assert clean(r"$x \sim y$") == "x ~ y" and clean("$= 3 6 \\pm 1 1$ 岁") == "= 36±11 岁"


B78 = (r"DeepGaitLab 在六相机（ $\cdot 3 . 8 ^ { \circ } \pm 0 . 5 ^ { \circ } ~ \mathrm { { V S } } . ~ 4 . 1 ^ { \circ } \pm 0 . 7 ^ { \circ } ~ ; ~ p =$ 0.0003 ）"
       r"和十相机配置 $( 3 . 7 ^ { \circ } \pm 0 . 6 ^ { \circ } \ : \mathrm { v s . 4 . 0 ^ { \circ } \pm 0 . 7 ^ { \circ } } ; \ : p < 0 . 0 0 0 1 )$ 中均比 "
       r"$\mathrm { T h e i a 3 D } \vec { \scriptscriptstyle { p } }$ 生更低的 ${ \mathrm { R M S D } } _ { \circ }$")


def test_r2_ellipsis_quote_pieces_verbatim_in_order():
    q = "十相机配置 ( 3.7°±0.6°: v s .4.0°±0.7°; : p < 0.0001 ) 中均比 T h e i a 3 D……更低的 R M S D"
    assert quote_in(q, B78)                                   # the judge's real quote (Fig2 '10 Cams ns' claim)
    assert not quote_in("更低的 R M S D……十相机配置", B78)      # pieces out of order
    assert not quote_in("十相机配置……不显著", B78)               # a piece that is not in the block
    assert not quote_in("六相机……RMSD", B78)                    # too little quoted text
    far = "开头的一句话很长很长" + "无关内容" * 100 + "结尾的话"
    assert not quote_in("开头的一句话很长很长……结尾的话", far)     # gap > MAX_ELLIPSIS_GAP


def test_r2_fig2_10cam_ns_claim_is_an_aligned_contradiction():
    from litreader.analysis.crosscheck import contradiction_aligned
    q = "十相机配置 ( 3.7°±0.6°: v s .4.0°±0.7°; : p < 0.0001 ) 中均比 T h e i a 3 D……更低的 R M S D"
    assert contradiction_aligned("10台相机配置下Theia3D与DeepGaitLab的对比标注为ns（无显著差异）", q) is None


def _r2_note(**kw):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import test_review_notes as R
    from litreader.analysis.validator_v2 import validate_v2
    d = R._doc()
    for k, v in kw.items():
        d[k] = v
    return R, d, validate_v2


def test_r2_writer_unknown_for_zotero_resolved_title_excluded_but_journal_volume_kept():
    R, d, V = _r2_note(unknowns=[{"item": "英文原题", "why": "原文仅提供中文标题，未出现英文原题。"},
                                 {"item": "期刊卷期页码", "why": "原文为预印本，未报告期刊卷期页码。"}])
    v = V(d, R.BLOCKS, R.T.MAN)
    md = R._r(v, zotero_meta={"title_en": "DeepGaitLab: Accurate…", "journal": "Research Square"})
    top = md[md.index("## 重点待确认问题"):]
    assert "**英文原题**" not in top and "期刊卷期页码" in top


def test_r2_key_result_fallback_is_earliest_result_not_a_population_fact():
    R, d, V = _r2_note()
    d["facts"].insert(0, {"field": "early", "value": "5.91°", "context": "膝伸展角增加 5.91°", "block_id": "b2",
                          "physical_page": 2, "label": "PAPER"})
    d["three_minute"]["key_result"] = None
    md = R._r(V(d, R.BLOCKS, R.T.MAN))
    line = next(l for l in md.splitlines() if "最重要的结果" in l)
    assert "page=2" in line and "page=14" not in line          # p2 result first, not the p14 MCI fact


def test_r2_gloss_skips_verbatim_and_redundant_gloss():
    from litreader.render.l2_note_v2 import gloss
    ab = [{"abbr": "ACLR", "zh": "前交叉韧带重建"}, {"abbr": "BEDLAM", "zh": "BEDLAM 合成数据集"}]
    out = gloss("原文摘录：「ACLR 参与者」\n*真实原图摘录，ACLR 患者*\n在 BEDLAM 上训练的 ACLR 组", ab)
    assert "「ACLR 参与者」" in out and "*真实原图摘录，ACLR 患者*" in out
    assert "BEDLAM（合成数据集）" in out and "ACLR（前交叉韧带重建） 组" in out or "ACLR（前交叉韧带重建）组" in out


def test_r2_subfigure_crops_side_by_side_with_proportional_widths():
    from litreader.render.l2_note_v2 import figure_rows
    # Fig1-like layout (illustrative bboxes): 4 small panels, 4 more, then one full-width panel
    bbs = [[120, 114, 305, 313], [341, 89, 455, 314], [491, 90, 661, 315], [692, 92, 861, 313],
           [148, 364, 336, 529], [374, 363, 549, 518], [553, 362, 723, 520], [746, 373, 857, 516], [120, 573, 862, 834]]
    parts = [{"physical_page": 8, "bbox_norm": b} for b in bbs]
    rows = figure_rows(parts, [f"_图表/K/Fig1-{i}.jpg" for i in range(1, 10)])
    assert [len(r) for r in rows] == [4, 4, 1]
    assert all(sum(w for _, w in r) <= 760 for r in rows) and rows[2][0][1] == 760 and rows[0][1][1] < 200
    assert figure_rows([{"physical_page": 1}], ["x/Fig1-1.jpg"]) == [[("x/Fig1-1.jpg", 760)]]   # no bbox: as before
