"""G7-12 note quality fixes (from the DeepGaitLab review): presumed figure number, sample-size cells, module once,
caption boilerplate out of findings + matching check page, overclaim hedging, U+FFFD, ± / ° spacing, evidence name."""
from litreader.analysis import validator_v2 as VV
from litreader.analysis.crosscheck import caption_boilerplate, page_matches
from litreader.analysis.validator_v2 import V2
from litreader.analysis.wording_judge import NONSIG, hedge_overclaims
from litreader.parse.blocks import Block
from litreader.render.l2_note_v2 import UNREADABLE, presumed_number, units, unreadable_symbols


def B(o, text, page=2, kind="text"):
    return Block(kind=kind, physical_page=page, bbox_norm=None, text=text, order=o)


def fig(n, page):
    return {"id": f"Fig{n}" if n else "figure_unnumbered_7", "kind": "figure", "number": str(n) if n else None,
            "parts": [{"physical_page": page}], "flags": [] if n else ["UNCAPTIONED", "UNCAPTIONED_ORPHAN"]}


def test_presumed_number_only_for_a_real_gap():
    man = [fig(1, 8), fig(2, 12), fig(3, 13), fig(4, 15), fig(5, 17), fig(6, 20), fig(8, 33), fig(9, 34)]
    orphan = fig(None, 21)
    assert presumed_number(orphan, man + [orphan]) == (7, 20, 33)
    assert presumed_number(fig(None, 40), man) is None                 # after the last figure: no guess
    assert presumed_number(orphan, [fig(1, 4)]) is None                # no gap
    assert presumed_number(fig(None, 21), man + [fig(7, 22)]) is None  # nothing missing


def test_unreadable_symbols_and_units():
    t, n = unreadable_symbols("一个 \ufffd - \ufffd 配对，\ufffd = 0.02")
    assert n == 2 and t.count(UNREADABLE) == 0 and "未能识别" in t and "p = 0.02" in t and "\ufffd" not in t  # G8-8 merge
    assert units("3.8° ± 0.5° 对 4.2±0.6°；4.32 ±1.27%") == "3.8 ± 0.5° 对 4.2 ± 0.6°；4.32 ± 1.27%"
    assert units("[[a/3±4.md]] [x](zotero://a?b=1±2)") == "[[a/3±4.md]] [x](zotero://a?b=1±2)"


def test_caption_boilerplate_and_check_page():
    cap = "图9. (A) 健康成人验证的相机配置。红色标记表示最小双相机配置。"
    assert caption_boilerplate("图9A中红色标记表示最小双相机配置", "红色标记表示最小双相机配置", cap)
    assert caption_boilerplate("每个箱线图中水平线表示中位数", None, "")
    assert caption_boilerplate("双相机下 DeepGaitLab 的 RMSD 显著低于 OpenCap", "p < 0.0001", cap) is None
    assert page_matches("双相机下 RMSD 为 4.2", "双相机配置下 RMSD 为 4.2 ± 0.6°")
    assert not page_matches("跑台步行中步长不对称 4.2", "Table 3 4.2 0.6 5.9 1.3")


def test_sample_size_cells_use_verified_paper_numbers_and_english_denominators():
    blocks = [B(0, "We recruited 23 healthy participants and 38 individuals after ACLR.", 10),
              B(1, "MCI 组共 19 名参与者。", 36), B(2, "Table 1 summary", 12, "table")]
    assert {"23", "38", "19"} <= VV.denominators(blocks)
    c = VV._Ctx(blocks)
    s = c.stmt({"text": "验证共 19 名参与者，另有 64 次记录。", "label": "PAPER", "basis_block_ids": ["b1"]}, "x")
    assert s is None                                                   # 64 not in basis -> rejected
    s = c.stmt({"text": "神经组共 19 名参与者。", "label": "PAPER", "basis_block_ids": ["b1"]}, "x")
    assert s and "19" in c.paper_nums
    t = c.table({"columns": ["人群", "样本量"], "rows": [["MCI+卒中", "19 名"], ["健康", "23 名"]],
                 "basis_block_ids": ["b2"], "title": "分母"}, "t")
    assert all("UNKNOWN" not in str(x) for r in t["rows"] for x in r)


def test_overclaims_hedged():
    blocks = [B(0, "DeepGaitLab 在多数比较中误差更低，但 Theia3D 比较不显著（p = 0.0977）。", 11)]
    v = V2(data={"s6": {"evaluation": {"text": "该结果为合成数据有效性提供了直接证据，并显示泛化优势，均优于对照工具。",
                                       "label": "INFERENCE", "basis_block_ids": ["b0"]}}})
    assert hedge_overclaims(v, blocks) == 1
    t = v.data["s6"]["evaluation"]["text"]
    assert "直接证据" not in t and "泛化优势" not in t and "均优于" not in t
    assert "初步证据" in t and t.endswith(NONSIG + "（基于单项研究）") and v.wording[-1]["gate"] == "wording_judge.overclaim"


def test_evidence_name_uses_item_key_on_author_conflict():
    from litreader.realrun import evidence_stem
    free = lambda c: False  # noqa: E731
    assert evidence_stem("题名——Halilaj2026", "题名", "GBLV2NPH", True, "Eni Halilaj", "2026", "Halilaj", free) \
        == "题名——GBLV2NPH——证据档案"
    assert evidence_stem("题名", "题名", "K", False, "Eni Halilaj", "2026", "Halilaj", free) == "题名——证据档案"


def test_g8_block_ids_are_not_numbers_and_source_column_dropped():
    assert VV.numbers("见 b104 与 B7，数值 23 名") == {"23"}
    blocks = [B(0, "We recruited 23 healthy participants.", 10), B(1, "8 MCI and 11 stroke; 12 healthy subset.", 36)]
    c = VV._Ctx(blocks)
    t = c.table({"columns": ["验证人群", "例数", "依据块"],
                 "rows": [["健康成人", "23", "b0"], ["逆动力学子集", "12", "b104"]],
                 "basis_block_ids": ["b0", "b1"], "title": "分母"}, "t")
    assert t["columns"] == ["验证人群", "例数"] and t["rows"] == [["健康成人", "23"], ["逆动力学子集", "12"]]
    assert not t.get("unknown_cells") and t["dropped_columns"] == 1


def test_g8_figures_sorted_and_presumed_follows_previous():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import test_note_v2 as T
    from litreader.analysis.validator_v2 import validate_v2
    part = lambda p: [{"img_path": f"images/{p}.jpg", "physical_page": p, "bbox_norm": [0, 0, 500, 500]}]  # noqa: E731
    man = [{"id": f"Fig{n}", "kind": "figure", "number": str(n), "caption": f"图 {n}. 示例", "parts": part(p), "flags": []}
           for n, p in ((4, 9), (1, 4), (2, 6))]
    man.append({"id": "figure_unnumbered_9", "kind": "figure", "number": None, "caption": "", "parts": part(7),
                "flags": ["UNCAPTIONED", "UNCAPTIONED_ORPHAN"]})
    a = T.good()
    secs = {"Fig1": "s2", "Fig2": "s3", "Fig4": "s4", "figure_unnumbered_9": "s4"}
    a["figures"] = [{"id": m["id"], "section": secs[m["id"]], "title": ""} for m in man]
    v = validate_v2(a, T.BLOCKS, man)
    md = T.render(v, blocks=T.BLOCKS, manifest=man, vision_obs=None, figure_paths={}, attachment_key="A", parent_key="K",
                  e_level="E3", translation_notice=None, link_mechanism_verified=False, read_date="d",
                  evidence_link="ev", model_info={"text": "m"})
    heads = [l.split("｜")[0] for l in md.splitlines() if l.startswith("### 图")]
    assert heads == ["### 图1", "### 图2", "### 图3（推定，图注缺失）", "### 图4"], heads


def test_g10_evidence_name_key_appears_once_on_rerun():
    from datetime import date
    from litreader.realrun import evidence_stem
    first = "题名——GBLV2NPH——证据档案"
    taken = {first}
    got = evidence_stem("题名——Shin2026", "题名", "GBLV2NPH", True, "Eni Halilaj", "2026", "Halilaj", taken.__contains__)
    assert got == f"{first}（{date.today().isoformat()}）" and got.count("GBLV2NPH") == 1
    taken.add(got)
    got2 = evidence_stem("题名——Shin2026", "题名", "GBLV2NPH", True, "Eni Halilaj", "2026", "Halilaj", taken.__contains__)
    assert got2.endswith("（2）") and got2.count("GBLV2NPH") == 1
    stem = "题名——Halilaj2026"     # no conflict: follows the (already unique) note stem, no second author/year
    assert evidence_stem(stem, "题名", "K", False, "Eni Halilaj", "2026", "Halilaj", lambda c: False) == \
        "题名——Halilaj2026——证据档案"
