"""Unit layer: parser adapters, figure grouping, E-level. Synthetic fixtures mirroring real shapes."""
import json

import pytest

from litreader.errors import Stop
from litreader.parse import mineru, ppstructure
from litreader.parse.blocks import caption_number, cjk_ratio
from litreader.parse.extraction_level import assess
from litreader.parse.figures import build_manifest, group_visuals, write_manifest


def T(p, text="body", lvl=None):
    d = {"type": "text", "text": text, "bbox": [50, 100, 900, 200], "page_idx": p}
    if lvl: d["text_level"] = lvl
    return d


def synthetic_content_list():
    """3-page doc: p0 title+text; p1 figure 1 + table 1; p2 5-part figure 2 (caption on last) + continuation table."""
    return [
        T(0, "Synthetic title", 1), T(0),
        T(1), {"type": "image", "img_path": "images/f1.jpg", "image_caption": ["图 1 | 流程图。"],
               "image_footnote": [], "bbox": [77, 79, 873, 503], "page_idx": 1},
        {"type": "table", "img_path": "images/t1.jpg", "table_caption": ["表 1 | 基线。"], "table_footnote": ["SD"],
         "table_body": "<table><tr><td>a</td></tr></table>", "bbox": [68, 520, 922, 900], "page_idx": 1},
        T(2),
        *[{"type": "chart", "img_path": f"images/c{i}.jpg", "chart_caption": [], "chart_footnote": [],
           "content": "", "bbox": [100, 100 + i, 400, 300], "page_idx": 2} for i in range(4)],
        {"type": "chart", "img_path": "images/c4.jpg", "chart_caption": ["Figure 2. Kinematics."],
         "chart_footnote": [], "content": "", "bbox": [100, 400, 400, 600], "page_idx": 2},
        {"type": "table", "img_path": "images/t2.jpg", "table_caption": [], "table_footnote": [],
         "table_body": "<table></table>", "bbox": [68, 700, 922, 950], "page_idx": 2},
        {"type": "page_number", "text": "3", "bbox": [500, 960, 520, 970], "page_idx": 2},
    ]


def test_mineru_physical_page_is_page_idx_plus_one():
    r = mineru.parse_content_list(synthetic_content_list())
    assert {b.physical_page for b in r.blocks} == {1, 2, 3}
    assert r.bbox_space == "norm1000_assumed"
    assert r.blocks[0].kind == "title"


def test_mineru_rejects_missing_page_and_bad_bbox():
    with pytest.raises(Stop):
        mineru.parse_content_list([{"type": "text", "text": "x"}])
    with pytest.raises(Stop):
        mineru.parse_content_list([{"type": "text", "text": "x", "page_idx": 0, "bbox": [0, 0, 1191, 50]}])


@pytest.mark.parametrize("cap,exp", [("图 1 | x", ("figure", "1")), ("Figure 2. y", ("figure", "2")),
                                     ("Fig.3 z", ("figure", "3")), ("表 2 | t", ("table", "2")),
                                     ("Table 1", ("table", "1")), ("表1|基线", ("table", "1")), ("Results", None)])
def test_caption_number(cap, exp):
    assert caption_number(cap) == exp


def test_subfigure_merge_and_continuation_table():
    g = group_visuals(mineru.parse_content_list(synthetic_content_list()))
    figs = {x["number"]: x for x in g if x["kind"] == "figure"}
    assert len(figs["2"]["parts"]) == 5 and "SUBFIGURES_MERGED" in figs["2"]["flags"]
    assert len(figs["1"]["parts"]) == 1
    tabs = [x for x in g if x["kind"] == "table"]
    assert len(tabs) == 1 and tabs[0]["number"] == "1"
    assert "CONTINUATION_ASSUMED" in tabs[0]["flags"] and [p["physical_page"] for p in tabs[0]["parts"]] == [2, 3]


def test_uncaptioned_table_without_predecessor_not_numbered():
    cl = [T(0), {"type": "table", "img_path": "images/t.jpg", "table_caption": [], "table_body": "<table/>",
                 "bbox": [0, 0, 10, 10], "page_idx": 0}]
    g = group_visuals(mineru.parse_content_list(cl))
    assert g[0]["number"] is None and "UNCAPTIONED" in g[0]["flags"]


def test_uncaptioned_figures_page_stay_unnumbered():
    cl = [T(0), {"type": "image", "img_path": "images/a.jpg", "image_caption": [], "bbox": [0, 0, 10, 10], "page_idx": 0}]
    g = group_visuals(mineru.parse_content_list(cl))
    assert g[0]["number"] is None and g[0]["flags"] == ["UNCAPTIONED", "UNCAPTIONED_ORPHAN"]


def test_manifest_provenance_and_exclusive_write(tmp_path):
    r = mineru.parse_content_list(synthetic_content_list(), version="x.y")
    m = build_manifest(r, "a" * 64, "PDF00001")
    assert {e["id"] for e in m} >= {"Fig1", "Fig2", "Table1"}
    for e in m:
        assert e["provenance"]["pdf_sha256"] == "a" * 64 and e["provenance"]["attachment_key"] == "PDF00001"
        assert e["type_tag"] == "ORIGINAL_EXCERPT" and e["visual_check"] == "UNVERIFIED" and e["vision_summary"] is None
    p = tmp_path / "figures.json"
    write_manifest(m, p)
    with pytest.raises(FileExistsError):
        write_manifest(m, p)


# ---------- E levels ----------
def _assets(tmp_path, names):
    (tmp_path / "images").mkdir()
    for n in names:
        (tmp_path / "images" / n).write_bytes(b"jpg")
    return str(tmp_path)


ALL_IMGS = ["f1.jpg", "t1.jpg", "t2.jpg"] + [f"c{i}.jpg" for i in range(5)]


def test_E0_encrypted_or_empty():
    r = mineru.parse_content_list(synthetic_content_list())
    assert assess(r, 3, encrypted=True).level == "E0"
    assert assess(mineru.parse_content_list([{"type": "header", "text": "h", "page_idx": 0}]), 1).level == "E0"


def test_E1_missing_page_or_count_mismatch():
    r = mineru.parse_content_list(synthetic_content_list())
    rep = assess(r, 4)
    assert rep.level == "E1" and rep.metrics["missing_text_pages"] == [4]
    r2 = mineru.parse_content_list(synthetic_content_list(), page_count=5)
    assert assess(r2, 3).level == "E1"


def test_E2_when_no_assets_or_missing_image(tmp_path):
    assert assess(mineru.parse_content_list(synthetic_content_list()), 3).level == "E2"
    d = _assets(tmp_path, ALL_IMGS[:-1])
    assert assess(mineru.parse_content_list(synthetic_content_list(), assets_dir=d), 3).level == "E2"


def test_E2_cap_when_no_visuals():
    rep = assess(mineru.parse_content_list([T(0), T(1)]), 2)
    assert rep.level == "E2" and "no figures" in rep.reasons[0]


def test_E3_and_E4(tmp_path):
    d = _assets(tmp_path, ALL_IMGS)
    r = mineru.parse_content_list(synthetic_content_list(), assets_dir=d, page_count=3)
    assert assess(r, 3).level == "E3"
    assert assess(r, 3, supplements=[{"name": "s.pdf", "sha256": "b" * 64}]).level == "E4"
    assert assess(r, 3, supplements=[{"name": "s.pdf"}]).level == "E3"


def test_cjk_ratio():
    r = mineru.parse_content_list([T(0, "轻度认知障碍"), T(0, "abc")])
    assert cjk_ratio(r.blocks) > 0.5


# ---------- PP-StructureV3 ----------
def pp_line(blocks, w=1191, h=1560):
    return json.dumps({"result": {"layoutParsingResults": [{"prunedResult": {
        "width": w, "height": h, "parsing_res_list": blocks}, "markdown": {"text": "", "images": {}}}]}})


def B(label, bbox, content=""):
    return {"block_label": label, "block_content": content, "block_bbox": bbox, "block_id": "1", "block_order": None}


def test_pp_page_from_line_order_and_pixel_normalisation():
    jl = "\n".join([pp_line([B("text", [0, 0, 1191, 156], "a")]), pp_line([B("text", [0, 0, 595.5, 780], "b")])])
    r = ppstructure.parse_jsonl(jl)
    assert [b.physical_page for b in r.blocks] == [1, 2]
    assert r.blocks[0].bbox_norm == (0.0, 0.0, 1000.0, 100.0)
    assert r.blocks[1].bbox_norm[2:] == pytest.approx((500.0, 500.0))
    assert r.bbox_space == "norm1000_from_pixels" and r.page_count_reported == 2


def test_pp_caption_pairing_by_position_and_kind():
    blocks = [B("figure_title", [83, 116, 400, 134], "表1|基线特征。"),
              B("table", [83, 150, 1099, 596], "<table/>"),
              B("image", [90, 700, 1097, 1100]),
              B("figure_title", "[90, 1110, 600, 1130]", "图1|招募流程图。"),
              B("text", [0, 1400, 100, 1450], "body")]
    r = ppstructure.parse_jsonl(pp_line(blocks))
    t = [b for b in r.blocks if b.kind == "table"][0]
    f = [b for b in r.blocks if b.kind == "figure"][0]
    assert t.caption.startswith("表1") and f.caption.startswith("图1")
    assert not [b for b in r.blocks if b.kind == "caption"]  # paired captions consumed
    assert t.img_path == "page_000/imgs/img_in_table_box_83_150_1099_596.jpg"


def test_pp_unpaired_caption_kept_and_far_caption_not_paired():
    blocks = [B("image", [0, 0, 100, 100]), B("figure_title", [0, 1400, 100, 1420], "图9|远处")]
    r = ppstructure.parse_jsonl(pp_line(blocks))
    assert [b for b in r.blocks if b.kind == "figure"][0].caption == ""
    assert [b for b in r.blocks if b.kind == "caption"]


def test_pp_multi_result_line_is_ambiguous_stop():
    bad = json.dumps({"result": {"layoutParsingResults": [{}, {}]}})
    with pytest.raises(Stop):
        ppstructure.parse_jsonl(bad)
