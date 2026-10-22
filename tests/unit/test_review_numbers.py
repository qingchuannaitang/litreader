"""Review fix 2 (number gate) and 7 (table cells): denominators + multi-block basis allowed; per-cell UNKNOWN."""
from litreader.analysis.validator_v2 import CELL_UNKNOWN, denominators, validate_v2
from litreader.render.l2_note_v2 import render
from tests.fixtures.deepgaitlab import BLOCKS


def S(t, ids, label="PAPER"):
    return {"text": t, "label": label, "basis_block_ids": list(ids), "link_label": "结果"}


def test_denominators_collected():
    d = denominators(BLOCKS)
    assert {"80", "23", "19", "11"} <= d          # "8名" is a small integer anyway


def test_key_result_with_denominator_from_other_block_passes():
    # archive: 3min.key_result rejected "numbers not found in basis blocks: ['23']"
    a = {"meta": {}, "three_minute": {"key_result": S(
        "在 23 名无步态障碍成人中，双相机 DeepGaitLab 相对标记点参考的 RMSD 为 4.2 ± 0.6°，显著低于 OpenCap 的 5.9 ± 1.3°（p < 0.0001）。", ["b78"])},
        "sections": {}}
    v = validate_v2(a, BLOCKS, [])
    assert v.data["three_minute"]["key_result"] is not None
    a["three_minute"]["key_result"] = S("RMSD 为 4.2 ± 0.6° 与 3.9 ± 0.1°", ["b78"])          # 3.9/0.1 invented
    assert validate_v2(a, BLOCKS, []).data["three_minute"]["key_result"] is None


def test_multi_block_basis():
    a = {"meta": {}, "three_minute": {"key_result": S("ACLR 髋屈/伸 OpenCap 13.4 ± 7.9°；不对称 RMSD 4.32 ± 1.27%", ["b89", "b104"])},
         "sections": {}}
    assert validate_v2(a, BLOCKS, []).data["three_minute"]["key_result"] is not None


def test_table_cells_checked_one_by_one():
    t = {"title": "健康成人运动学 RMSD（°）", "label": "PAPER", "columns": ["比较", "DeepGaitLab", "对照工具", "p 值"],
         "rows": [["2 相机 vs OpenCap", "4.2 ± 0.6", "5.9 ± 1.3", "p < 0.0001"],
                  ["6 相机 vs Theia3D", "3.8 ± 0.5", "4.1 ± 0.7", "p = 0.0003"]], "basis_block_ids": ["b78", "b79"]}
    v = validate_v2({"meta": {}, "sections": {"s3": {"tables": [t]}}}, BLOCKS, [])
    rows = v.data["sections"]["s3"]["tables"][0]["rows"]
    assert rows[0][1:] == ["4.2 ± 0.6", "5.9 ± 1.3", "p < 0.0001"]
    assert rows[1][1] == "3.8 ± 0.5" and rows[1][2] == CELL_UNKNOWN and rows[1][3] == CELL_UNKNOWN
    assert any(r["where"] == "s3.t0.cells" for r in v.rejected)
    md = render(v, blocks=BLOCKS, manifest=[], vision_obs=None, figure_paths={}, attachment_key="A", parent_key="P",
                e_level="E3", translation_notice=None, link_mechanism_verified=False, read_date="d", evidence_link="ev",
                model_info={"text": "m"})
    assert "4.1 ± 0.7" not in md and CELL_UNKNOWN in md
