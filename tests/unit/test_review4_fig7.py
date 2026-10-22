"""Review 4: DeepGaitLab p21 = 图 7, one box-plot figure split by MinerU into 3 caption-less blocks in one row, with
the caption as a plain text paragraph directly below (Chinese-translated PDF). Bboxes of the blocks are from the
2nd-run evidence file; the caption bbox is assumed (just below the row)."""
from litreader.parse.blocks import Block, ParseResult
from litreader.parse.figures import build_manifest, cap_start

CAP7 = ("图 7. 环境特定微调对逆运动学性能的影响。利用环境特定合成数据，微调后的模型在平地行走中与基于标记的运动分析结果更为一致，"
        "其中膝关节屈曲/伸展和踝关节背屈/跖屈的改善最为明显。每个箱线图中，水平线表示中位数，箱体覆盖四分位距（第 25 至第 75 百分位数），"
        "须线表示四分位距的 1.5 倍。")


def B(o, kind, page, text="", bbox=None, **kw):
    return Block(kind=kind, physical_page=page, bbox_norm=bbox, text=text, order=o, **kw)


ROW = [B(134, "figure", 21, bbox=(117, 420, 243, 594), img_path="g1.jpg"),
       B(135, "figure", 21, bbox=(259, 420, 490, 606), img_path="g2.jpg"),
       B(136, "figure", 21, bbox=(508, 415, 877, 604), img_path="g3.jpg")]
FIG6 = B(128, "figure", 20, bbox=(218, 315, 777, 584), caption="图 6. 自动校准对逆运动学性能的影响。", img_path="f.jpg")


def manifest(blocks):
    return {m["id"]: m for m in build_manifest(ParseResult("mineru", "x", 49, "norm1000_assumed", blocks), "sha", "A")}


def page21(caption_block, extra=()):
    return [FIG6, B(130, "text", 21, "环境特定微调在平地行走中改善一致性（图 7A）。", bbox=(117, 150, 877, 400))] + ROW + \
        [caption_block, B(140, "text", 22, "讨论。", bbox=(117, 100, 877, 200))] + list(extra)


def test_cap_start_only_at_paragraph_start_with_caption_punctuation():
    for t, n in [("图 7. 环境", "7"), ("图7：影响", "7"), ("图 12｜流程", "12"), ("Figure 7. Effect", "7"), ("Fig. 7 Effect", "7"),
                 ("**图 7.** 影响", "7"), ("<b>Figure 3:</b> x", "3")]:
        assert cap_start(t) == n, t
    for t in ["（图 7C）显示改善", "如图 7 所示", "图 7 显示微调后改善", "图 7C 显示", "Fig. 7c shows", "figure 7 shows the", "见图 7。"]:
        assert cap_start(t) is None, t


def test_p21_row_with_text_caption_below_becomes_fig7():
    m = manifest(page21(B(137, "text", 21, CAP7, bbox=(117, 618, 877, 700))))
    assert [p["order"] for p in m["Fig7"]["parts"]] == [134, 135, 136]
    assert m["Fig7"]["caption"] == CAP7                                         # verbatim
    assert {"CAPTION_FROM_TEXT", "CAPTION_ADJACENT", "SUBFIGURES_MERGED"} <= set(m["Fig7"]["flags"])
    assert [p["order"] for p in m["Fig6"]["parts"]] == [128]                     # nothing moved into 图6
    assert not [k for k in m if not k.startswith("Fig")]


def test_caption_detected_as_title_with_markup_and_caption_above():
    m = manifest(page21(B(137, "title", 21, "**" + CAP7, bbox=(117, 618, 877, 700))))
    assert m["Fig7"]["caption"].startswith("**图 7.")
    above = [FIG6] + ROW + [B(133, "text", 21, CAP7, bbox=(117, 330, 877, 405))]
    assert "CAPTION_ADJACENT" in manifest(above)["Fig7"]["flags"]


def test_cut_adjacent_caption_still_continues():
    m = manifest(page21(B(137, "text", 21, "图 7. 环境特定微调对逆运动学性能的影响。利用环境特定", bbox=(117, 618, 877, 650)),
                        [B(138, "text", 21, "合成数据，微调后的模型更为一致。", bbox=(117, 652, 877, 680))]))
    assert m["Fig7"]["caption"].endswith("利用环境特定合成数据，微调后的模型更为一致。") and "CAPTION_CONTINUED" in m["Fig7"]["flags"]


def test_body_reference_below_is_not_a_caption():
    for body in ("（图 7C）显示膝关节改善最大。", "图 7 显示微调后改善。"):
        m = manifest(page21(B(137, "text", 21, body, bbox=(117, 618, 877, 700))))
        g = next(x for x in m.values() if [p["order"] for p in x["parts"]] == [134, 135, 136])
        assert g["caption"] == "" and "CAPTION_FROM_TEXT" not in g["flags"] and "CAPTION_ADJACENT" not in g["flags"]


def test_far_or_sideways_caption_is_not_adjacent_and_used_number_is_not_taken():
    far = manifest(page21(B(137, "text", 21, CAP7, bbox=(117, 900, 877, 960))))
    assert "CAPTION_ADJACENT" not in far["Fig7"]["flags"]                       # page-level fallback only
    side = manifest(page21(B(137, "text", 21, CAP7, bbox=(890, 620, 990, 700))))
    assert "CAPTION_ADJACENT" not in side["Fig7"]["flags"]
    used = manifest([FIG6, B(128, "figure", 20, caption="图 7. 另一张图。", img_path="x.jpg")] + ROW
                    + [B(137, "text", 21, CAP7, bbox=(117, 618, 877, 700))])
    orphan = [x for k, x in used.items() if not k.startswith("Fig")]
    assert len(orphan) == 1 and {"UNCAPTIONED", "UNCAPTIONED_ORPHAN"} <= set(orphan[0]["flags"])   # c513e5b safety


def test_two_rows_on_one_page_each_take_their_own_caption():
    top = [B(1, "figure", 5, bbox=(100, 80, 450, 300), img_path="a.jpg"), B(2, "figure", 5, bbox=(500, 80, 900, 310), img_path="b.jpg")]
    bot = [B(4, "figure", 5, bbox=(100, 520, 900, 800), img_path="c.jpg")]
    m = manifest(top + [B(3, "text", 5, "图 3. 上方图。", bbox=(100, 320, 900, 360))] + bot
                 + [B(5, "text", 5, "图 4. 下方图。", bbox=(100, 815, 900, 850))])
    assert [p["order"] for p in m["Fig3"]["parts"]] == [1, 2] and [p["order"] for p in m["Fig4"]["parts"]] == [4]


def test_inspect_page_lists_caption_paragraph_and_new_grouping(tmp_path):
    from litreader.cli_inspect import page_detail
    res = ParseResult("mineru", "x", 49, "norm1000_assumed", page21(B(137, "title", 21, CAP7, bbox=(117, 618, 877, 700),
                                                                      raw_type="text")), str(tmp_path))
    lines = []
    page_detail(res, tmp_path, [21], False, lines.append)
    out = "\n".join(lines)
    assert "#137 text/title bbox [117, 618, 877, 700]：图注段落「图 7. 环境特定微调对逆运动学性能的影响。利用环境特定合成…」" in out
    assert "归入：Fig7（SUBFIGURES_MERGED、CAPTION_FROM_TEXT、CAPTION_ADJACENT）" in out
    assert "改善一致性" not in out                                              # body text only with --text


def test_inspect_text_lists_all_blocks_loose_and_mid_captions_and_discarded(tmp_path):
    import json
    from litreader.cli_inspect import page_detail
    (tmp_path / "layout.json").write_text(json.dumps({"pdf_info": [{"page_idx": 20, "page_size": [612, 792], "discarded_blocks": [
        {"type": "discarded", "bbox": [72, 485, 540, 540], "lines": [{"spans": [{"content": "图 7. 环境特定微调对逆运动学性能的影响。"}]}]}]}]}),
        "utf-8")
    blocks = ROW + [B(129, "aside", 21, "图 7 环境特定微调对逆运动学性能的影响", bbox=(117, 618, 877, 640), raw_type="aside_text"),
                    B(133, "text", 21, "该特征未改善性能。图 7. 环境特定微调的影响。", bbox=(117, 100, 877, 400), raw_type="text"),
                    B(137, "title", 21, "讨论", bbox=(117, 700, 300, 720), raw_type="text"),
                    B(139, "page_number", 21, "19", bbox=(490, 940, 510, 950), raw_type="page_number")]
    res = ParseResult("mineru", "x", 49, "norm1000_assumed", blocks, str(tmp_path))
    quiet, loud = [], []
    page_detail(res, tmp_path, [21], False, quiet.append)
    page_detail(res, tmp_path, [21], True, loud.append)
    q, t = "\n".join(quiet), "\n".join(loud)
    assert "#129 aside_text/aside bbox [117, 618, 877, 640]：疑似图注（格式不在识别规则内）「图 7 环境特定微调" in q
    assert "丢弃#1 discarded bbox [118, 612, 882, 682]：疑似图注「图 7. 环境特定微调" in q             # points -> ‰
    assert "该特征未改善" not in q and "讨论" not in q
    assert "#137 text/title bbox [117, 700, 300, 720]（2 字）：讨论" in t and "#139 page_number" in t
    assert "↳ 第 9 字处出现「图 7. 环境特定微调的影响。」" in t


def test_multi_crop_rows_fit_obsidian_readable_width():
    from litreader.render.l2_note_v2 import ROW_W, figure_rows
    # DeepGaitLab 图5 row (p19): 134+243+376 = 753 px wrapped onto two lines in the 3rd-run screenshot
    parts = [{"physical_page": 19, "bbox_norm": b} for b in ([124, 99, 254, 268], [264, 102, 501, 273], [511, 94, 877, 279])]
    rows = figure_rows(parts, [f"x/Fig5-{i}.jpg" for i in (1, 2, 3)])
    assert len(rows) == 1 and sum(w for _, w in rows[0]) <= ROW_W <= 690
    assert figure_rows([{"physical_page": 20, "bbox_norm": [218, 315, 777, 584]}], ["x/Fig6-1.jpg"])[0][0][1] == 574
