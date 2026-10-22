"""G10-6: the 健康成人 参考系统 cell (“20 台红外 + 10 台 RGB”) was UNKNOWN because 20 is only stated in a figure caption,
not in the table's cited blocks. Number + same unit word elsewhere in the paper now passes; a bare number does not."""
from litreader.analysis.validator_v2 import CELL_UNKNOWN, validate_v2
from litreader.parse.blocks import Block


def B(o, page, text):
    return Block(kind="text", physical_page=page, bbox_norm=None, text=text, order=o)


BLOCKS = [B(1, 12, "图2. (A) 健康参与者同时由 20 台红外相机和 10 台 RGB 相机同步记录，共 37 次试验。"),
          B(2, 36, "MCI 与卒中实验使用 14 台红外相机与 8 台 RGB 相机。"),
          B(3, 34, "健康成人验证使用 I-MOVE-23 数据集。")]


def _t(cell):
    t = {"title": "相机配置", "label": "PAPER", "columns": ["验证", "参考系统"],
         "rows": [["健康成人", cell], ["MCI", "14 台红外 + 8 台 RGB"]], "basis_block_ids": ["b2", "b3"]}
    v = validate_v2({"meta": {}, "sections": {"s3": {"tables": [t]}}}, BLOCKS, [])
    return v, v.data["sections"]["s3"]["tables"][0]["rows"]


def test_number_with_unit_in_caption_passes():
    v, rows = _t("20 台红外 + 10 台 RGB")
    assert rows[0][1] == "20 台红外 + 10 台 RGB" and v.located_cells[0]["numbers"] == ["20"]


def test_bare_number_or_other_unit_still_unknown():
    _, rows = _t("20 名受试者")
    assert rows[0][1] == CELL_UNKNOWN and "引用的原文段落里没有这个数字" in CELL_UNKNOWN
    _, rows = _t("37 台红外")        # 37 exists in the paper, but as “37 次试验”
    assert rows[0][1] == CELL_UNKNOWN
