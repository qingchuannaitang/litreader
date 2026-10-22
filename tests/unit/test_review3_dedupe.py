"""Review 2 follow-up (approved): stricter near-duplicate merging — never negative results, never a unique fact,
page links always combined."""
from litreader.parse.blocks import Block
from litreader.render.l2_note_v2 import Ctx

BLOCKS = [Block(kind="text", physical_page=p, bbox_norm=None, text="x", order=p) for p in (4, 9, 12, 17)]
IDS = {p: f"b{p}" for p in (4, 9, 12, 17)}


def S(text, page, label="PAPER"):
    return {"text": text, "label": label, "basis_block_ids": [IDS[page]], "link_label": "可得性"}


def render(c, items):
    """Like the note: kept statements render (as placeholders), merged ones are omitted; then resolve."""
    shown = [c.st(s) for s in items if not c.dup(s)]
    return [c.resolve(x) for x in shown]


def test_code_availability_pair_merges_and_combines_links():
    c = Ctx(BLOCKS, "A")
    a = S("作者声明所有数据、代码和训练模型均公开共享，但正文未给出具体获取地址。", 4)
    b = S("作者报告所有数据、代码和训练模型均公开共享，但正文未给出具体仓库地址与许可条款，可复现性需进一步核实。", 9, "INFERENCE")
    out = render(c, [a, b])
    assert len(out) == 1 and out[0].startswith("作者声明所有数据")          # PAPER fact kept
    assert "page=4" in out[0] and "page=9" in out[0]                       # both sources survive


def test_later_text_with_more_facts_replaces_earlier_and_keeps_its_link():
    c = Ctx(BLOCKS, "A")
    a = S("双相机下自动校准的误差与棋盘格校准相似，可替代棋盘格。", 12)
    b = S("双相机下自动校准的误差与棋盘格校准相似（p = 0.5054），可替代棋盘格。", 17)
    out = render(Ctx(BLOCKS, "A"), [a, b])
    assert len(out) == 1 and "0.5054" in out[0] and "page=12" in out[0] and "page=17" in out[0]


def test_negative_results_are_never_merged():
    c = Ctx(BLOCKS, "A")
    neg = S("十相机配置下 DeepGaitLab 与 Theia3D 在所有活动上均无显著差异。", 12)
    again = S("十相机配置下 DeepGaitLab 与 Theia3D 在所有活动上均无显著差异，两者性能相当。", 17)
    assert c.dup(neg, neg=True) is False
    assert c.dup(again) is False                                           # both shown
    c = Ctx(BLOCKS, "A")
    pos = S("十相机配置下 DeepGaitLab 与 Theia3D 在所有活动上表现接近。", 12)
    assert c.dup(pos) is False and c.dup(S("十相机配置下 DeepGaitLab 与 Theia3D 在所有活动上表现接近，但 p > 0.05。", 17)) is False


def test_each_side_has_a_unique_fact_so_both_stay():
    c = Ctx(BLOCKS, "A")
    a = S("编码器权重由 ViTPose 初始化，再在合成数据上以较低学习率微调。", 12)
    b = S("编码器权重由 DINOv2 初始化，再在合成数据上以较低学习率微调。", 17)
    assert c.dup(a) is False and c.dup(b) is False


def test_full_note_has_no_placeholder_left_and_dup_links_combined():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import test_review_notes as R
    from litreader.analysis.validator_v2 import validate_v2
    md = R._r(validate_v2(R._doc(), R.BLOCKS, R.T.MAN))
    assert "\x00" not in md
    assert md.count("共纳入 79 名老年受试者并完成步态分析") == 1
