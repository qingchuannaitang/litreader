"""Review fix 3/17: uncaptioned figure blocks -> one figure with caption from a text block, or a number inferred from
in-text references, or merged into the nearest captioned figure; captions cut mid-sentence are continued."""
from litreader.parse.blocks import Block, ParseResult
from litreader.parse.figures import build_manifest


def B(o, kind, page, text="", **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o, **kw)


def manifest(blocks):
    return build_manifest(ParseResult("mineru", "x", 40, "norm1000_assumed", blocks), "sha", "ATT")


# layout of the DeepGaitLab run: p8 captioned Fig1 (caption cut), p12 three panels whose caption is the first text
# block of p13, p17 three panels + caption text block on p17, p21 three panels with only in-text refs, p32 one panel
LAYOUT = [
    B(57, "figure", 8, caption="图 1. DeepGaitLab 概览。(A) 三阶段工作流：(i) 多视角视频记录与密集关键点检测在", img_path="a.jpg"),
    B(58, "text", 8, "合成数据上训练的网络中完成；(ii) 三角化；(iii) 逆运动学。"),
    B(75, "text", 10, "23 名参与者完成了地面行走（图 2A）。"),
    B(78, "text", 11, "DeepGaitLab 的 RMSD 显著更低（图 2C）。"),
    B(82, "figure", 12, img_path="b1.jpg"), B(83, "figure", 12, img_path="b2.jpg"), B(84, "figure", 12, img_path="b3.jpg"),
    B(85, "text", 13, "图 2. 健康成人的逆运动学性能。(A) 九种动作。"),
    B(96, "figure", 15, caption="图 3. ACL 重建术后患者的逆运动学性能。", img_path="c.jpg"),
    B(107, "figure", 17, img_path="d1.jpg"), B(108, "figure", 17, img_path="d2.jpg"),
    B(109, "text", 17, "图 4. MCI 与卒中人群的步长不对称。(B) 一致性高于 OpenCap。"),
    B(110, "figure", 17, img_path="d3.jpg"),
    B(120, "figure", 19, caption="图 5. 逆动力学性能。", img_path="e.jpg"),
    B(128, "figure", 20, caption="图 6. 自动校准的影响。", img_path="f.jpg"),
    B(130, "text", 21, "微调在动态活动上改善（图 7A），膝与踝改善（图 7C）。"),
    B(131, "figure", 21, img_path="g1.jpg"), B(132, "figure", 21, img_path="g2.jpg"), B(133, "figure", 21, img_path="g3.jpg"),
    B(174, "figure", 29, caption="图 8. 密集标志点检测网络架构。", img_path="h.jpg"),
    B(190, "figure", 30, img_path="h2.jpg"),
]


def test_deepgaitlab_like_layout_numbers_figures_and_keeps_orphans_apart():
    m = {x["id"]: x for x in manifest(LAYOUT)}
    assert sorted(x for x in m if x.startswith("Fig")) == ["Fig1", "Fig2", "Fig3", "Fig4", "Fig5", "Fig6", "Fig7", "Fig8"]
    assert len(m["Fig2"]["parts"]) == 3 and m["Fig2"]["caption"].startswith("图 2. 健康成人") and "CAPTION_FROM_TEXT" in m["Fig2"]["flags"]
    assert len(m["Fig4"]["parts"]) == 3 and m["Fig4"]["caption"].startswith("图 4.")
    assert len(m["Fig7"]["parts"]) == 3 and "NUMBER_INFERRED_FROM_TEXT" in m["Fig7"]["flags"]
    # review 3: the p30 panel is NOT merged into Fig8 (p29) any more — it stays an unnumbered, flagged figure
    assert len(m["Fig8"]["parts"]) == 1 and "UNCAPTIONED_MERGED" not in m["Fig8"]["flags"]
    orphan = [x for k, x in m.items() if not k.startswith("Fig")]
    assert len(orphan) == 1 and orphan[0]["parts"][0]["physical_page"] == 30 and "UNCAPTIONED_ORPHAN" in orphan[0]["flags"]


def test_cut_caption_is_continued():
    m = {x["id"]: x for x in manifest(LAYOUT)}
    assert m["Fig1"]["caption"].endswith("(iii) 逆运动学。") and "CAPTION_CONTINUED" in m["Fig1"]["flags"]
    assert m["Fig3"]["caption"] == "图 3. ACL 重建术后患者的逆运动学性能。"                     # complete: untouched


def test_lonely_uncaptioned_figure_far_from_others_stays_single_group():
    m = manifest([B(1, "figure", 3, img_path="x.jpg"), B(2, "figure", 3, img_path="y.jpg"), B(3, "text", 9, "无图引用")])
    assert len(m) == 1 and len(m[0]["parts"]) == 2 and m[0]["number"] is None


def test_r2_caption_detected_as_aside_or_footnote_is_found():
    m = manifest([B(1, "text", 17, "（图 4A）显示步长不对称。"), B(2, "figure", 18, img_path="a.jpg"),
                  B(3, "figure", 18, img_path="b.jpg"), B(4, "aside", 18, "图 4. MCI 与卒中人群的步长不对称。")])
    assert len(m) == 1 and m[0]["caption"].startswith("图 4. MCI") and "CAPTION_FROM_TEXT" in m[0]["flags"]
    assert "UNCAPTIONED" not in m[0]["flags"]


def test_r2_cut_caption_continues_past_page_furniture():
    m = manifest([B(1, "figure", 8, caption="图 1. 概览：(i) 多视角视频记录与密集关键点检测在", img_path="a.jpg"),
                  B(2, "page_number", 8, "8"), B(3, "footer", 8, "Research Square"), B(4, "header", 9, "Preprint"),
                  B(5, "aside", 9, "旁注"), B(6, "text", 9, "合成数据上训练的网络中完成。")])
    assert m[0]["caption"].endswith("检测在合成数据上训练的网络中完成。") and "旁注" not in m[0]["caption"]
    stop = manifest([B(1, "figure", 8, caption="图 1. 概览：检测在", img_path="a.jpg"), B(2, "title", 8, "2 结果"),
                     B(3, "text", 8, "正文第一段。")])
    assert stop[0]["caption"] == "图 1. 概览：检测在"                       # a heading ends the search


def test_r3_deepgaitlab_p21_blocks_are_not_shown_under_fig6():
    """Real DeepGaitLab manifest (2nd Mac run): Fig6 caption+image on p20, three uncaptioned blocks on p21 (orders
    134–136, bboxes from the evidence file), no caption text and no in-text figure reference nearby."""
    m = {x["id"]: x for x in manifest([
        B(124, "text", 19, "采用自动校准的 DeepGaitLab 优于采用棋盘格校准的 OpenCap。"),
        B(128, "figure", 20, caption="图 6. 自动校准对逆运动学性能的影响。", img_path="f.jpg"),
        B(130, "text", 21, "环境特定微调在平地行走中改善一致性。"),
        Block(kind="figure", physical_page=21, bbox_norm=(117, 420, 243, 594), text="", order=134, img_path="g1.jpg"),
        Block(kind="figure", physical_page=21, bbox_norm=(259, 420, 490, 606), text="", order=135, img_path="g2.jpg"),
        Block(kind="figure", physical_page=21, bbox_norm=(508, 415, 877, 604), text="", order=136, img_path="g3.jpg"),
        B(140, "text", 22, "讨论。")])}
    assert len(m["Fig6"]["parts"]) == 1 and m["Fig6"]["parts"][0]["physical_page"] == 20
    orphan = [x for k, x in m.items() if k != "Fig6"]
    assert len(orphan) == 1 and len(orphan[0]["parts"]) == 3 and orphan[0]["number"] is None
    assert {"UNCAPTIONED", "UNCAPTIONED_ORPHAN"} <= set(orphan[0]["flags"])


def test_r3_orphan_figure_renders_with_warning_not_under_a_number():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import test_note_v2 as T
    from litreader.analysis.validator_v2 import validate_v2
    man = T.MAN + [{"id": "figure__2", "kind": "figure", "number": None, "caption": "", "flags": ["UNCAPTIONED", "UNCAPTIONED_ORPHAN"],
                    "parts": [{"img_path": "images/g1.jpg", "physical_page": 21, "bbox_norm": [117, 420, 243, 594]}]}]
    v = validate_v2(T.good(), T.BLOCKS, man)
    md = T.render(v, blocks=T.BLOCKS, manifest=man, vision_obs=None, figure_paths={}, attachment_key="A", parent_key="K",
                  e_level="E3", translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev",
                  model_info={"text": "m"})
    assert "### 图（无编号）" in md and "无图注、无编号的图块：MinerU 在 PDF 物理p21" in md and "未并入任何编号图" in md


def test_r3_inspect_page_helpers(tmp_path):
    from litreader.cli_inspect import image_size, page_detail, parse_pages
    from litreader.parse.blocks import ParseResult
    assert parse_pages("20-22") == [20, 21, 22] and parse_pages("8，21") == [8, 21] and parse_pages("22-20") == [20, 21, 22]
    png = tmp_path / "images" / "a.png"
    png.parent.mkdir()
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (300).to_bytes(4, "big") + (120).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
    jpg = tmp_path / "images" / "b.jpg"
    jpg.write_bytes(b"\xff\xd8" + b"\xff\xe0\x00\x04ab" + b"\xff\xc0\x00\x11\x08" + (77).to_bytes(2, "big") + (640).to_bytes(2, "big") + b"\x03" + b"\x00" * 9)
    assert image_size(png) == (300, 120) and image_size(jpg) == (640, 77)
    res = ParseResult("mineru", "x", 30, "norm1000_assumed", [
        Block(kind="figure", physical_page=20, bbox_norm=(218, 315, 777, 584), text="", order=128, caption="图 6. 自动校准。", img_path="images/b.jpg", raw_type="image"),
        Block(kind="page_number", physical_page=21, bbox_norm=None, text="20", order=133, raw_type="page_number"),
        Block(kind="figure", physical_page=21, bbox_norm=(117, 420, 243, 594), text="", order=134, img_path="images/a.png", raw_type="image"),
        Block(kind="text", physical_page=21, bbox_norm=None, text="正文内容不显示", order=137, raw_type="text")], str(tmp_path))
    lines = []
    page_detail(res, tmp_path, [21], False, lines.append)
    out = "\n".join(lines)
    assert "page_number「20」" in out                                   # printed page label ≠ physical page: visible
    assert "#134 image：bbox [117, 420, 243, 594]，宽 126‰ × 高 174‰" in out and "（300×120 像素）" in out
    assert "归入：figure_unnumbered_2（UNCAPTIONED、UNCAPTIONED_ORPHAN）" in out and "正文内容不显示" not in out
