"""Review 5 (DeepGaitLab, Mac inspect-parse --text on p17/p21):
p17 — the real 图4 caption sits after a panel label inside a chart caption: '(C) 图4. …';
p21 — MinerU dropped the 图7 caption entirely (not in any block, not in discarded_blocks)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_note_v2 as T  # noqa: E402

from litreader.analysis.validator_v2 import validate_v2  # noqa: E402
from litreader.parse.blocks import Block, ParseResult  # noqa: E402
from litreader.parse.figures import build_manifest, split_panel_caption  # noqa: E402

CAP4 = "图4. 轻度认知障碍或脑卒中患者的时空不对称性能。(A) 双相机配置下…"


def B(o, kind, page, text="", bbox=None, **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=bbox, text=text, order=o, **kw)


def manifest(blocks):
    return {m["id"]: m for m in build_manifest(ParseResult("mineru", "x", 49, "norm1000_assumed", blocks), "sha", "A")}


P17 = [B(106, "text", 17, "两组患者的步长不对称均被检测到（图 4A）。", bbox=(117, 80, 877, 200)),
       B(107, "figure", 17, bbox=(117, 210, 877, 420), img_path="a.jpg", caption="(A)"),
       B(108, "figure", 17, bbox=(117, 430, 490, 640), img_path="b.jpg", caption="(B)"),
       B(109, "figure", 17, bbox=(500, 430, 877, 640), img_path="c.jpg", caption="(C) " + CAP4)]


def test_split_panel_caption():
    assert split_panel_caption("(C) " + CAP4) == ("(C)", CAP4)
    assert split_panel_caption("（A–C） Figure 3. Effect of x") == ("（A–C）", "Figure 3. Effect of x")
    assert split_panel_caption("C. 图 4：x") == ("C.", "图 4：x")
    for t in ["(A)", "(C) 如图 4 所示", "(C) 图 4 显示改善", "(C) 见图 4。", "Anova 图4. x", "(C) Fig. 4c shows", ""]:
        assert split_panel_caption(t) == (None, t), t


def test_p17_embedded_caption_becomes_fig4_verbatim_with_panel_labels():
    m = manifest(P17)
    assert list(m) == ["Fig4"]
    g = m["Fig4"]
    assert g["caption"] == CAP4 and g["number"] == "4"                     # verbatim, without the '(C) ' label
    assert [p.get("panel_label") for p in g["parts"]] == ["(A)", "(B)", "(C)"]
    assert "CAPTION_AFTER_PANEL_LABEL" in g["flags"] and "UNCAPTIONED" not in g["flags"]
    assert "NUMBER_INFERRED_FROM_TEXT" not in g["flags"]
    assert P17[3].caption == "(C) " + CAP4                                 # parse blocks are not mutated


def test_body_reference_after_panel_label_is_not_a_caption():
    blocks = P17[:3] + [B(109, "figure", 17, bbox=(500, 430, 877, 640), img_path="c.jpg", caption="(C) 如图 4 所示")]
    g = list(manifest(blocks).values())[0]
    assert g["caption"] == "" and "UNCAPTIONED" in g["flags"]             # number only inferred from the body ref


def _render(man):
    v = validate_v2(T.good(), T.BLOCKS, man)
    return T.render(v, blocks=T.BLOCKS, manifest=man, vision_obs=None, figure_paths={}, attachment_key="A", parent_key="K",
                    e_level="E3", translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev",
                    model_info={"text": "m"})


def test_mineru_dropped_caption_points_to_zotero_page_and_never_invents_one():
    part = {"img_path": "images/g1.jpg", "physical_page": 21, "bbox_norm": [117, 420, 243, 594]}
    man = T.MAN + [{"id": "figure__2", "kind": "figure", "number": None, "caption": "", "parts": [part],
                    "flags": ["SUBFIGURES_MERGED", "UNCAPTIONED", "UNCAPTIONED_ORPHAN"]}]
    md = _render(man)
    assert "图注请在 Zotero 原页阅读：[物理p21](zotero://open-pdf/library/items/A?page=21)" in md
    # G7-12: the user asked for a presumed number when exactly one missing number fits the position
    from litreader.render.l2_note_v2 import presumed_number
    g = presumed_number(man[-1], man)
    if g:
        assert f"### 图{g[0]}（推定，图注缺失）" in md and "图注缺失，图号为推定" in md and "不转录、不猜测图注" in md
    else:
        assert "不转录、不猜测图注和图号" in md
    assert "看图模型转录" not in md
    man[-1] = {**man[-1], "id": "Fig4", "number": "4", "flags": ["UNCAPTIONED", "NUMBER_INFERRED_FROM_TEXT"],
               "parts": [{**part, "physical_page": 17}]}
    md = _render(man)
    assert "图注未识别" in md and "图号由正文引用推断" in md and "?page=17" in md


def test_study_type_unknown_dropped_when_classifier_supplied_it():
    from test_review_notes import _doc, _r, BLOCKS
    for prov, expect in [({"study_type": "methods_technical"}, "CLASSIFIER"), (None, None)]:
        v = validate_v2(_doc(), BLOCKS, T.MAN)
        v.unknowns = [u for u in v.unknowns if u["item"] != "元数据 study_type"]
        v.unknowns.append({"item": "元数据 study_type", "why": "原文未找到或未通过逐字核对"})
        n_before = len([u for u in v.unknowns if not u.get("resolved_by")])
        _r(v, provenance=prov) if prov else _r(v)
        u = next(x for x in v.unknowns if x["item"] == "元数据 study_type")
        assert u.get("resolved_by") == expect
        assert v.stats["unknowns_in_note"] <= n_before - (1 if expect else 0)
