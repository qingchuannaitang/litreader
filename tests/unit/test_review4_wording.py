"""Review 4 (DeepGaitLab 3rd Mac run): no metric borrowed from cited blocks, idioms are not comparatives,
yes/no question headings pass."""
from litreader.analysis import wording, wording_judge


def test_metric_never_borrowed_from_basis():
    t = "在健康成人、ACLR 术后、MCI 和卒中人群中，DeepGaitLab 的运动学、动力学和不对称性指标多优于或相当于 OpenCap 和 Theia3D，且双相机配置即可达到有竞争力的精度。"
    basis = "DeepGaitLab 与基于标记点分析的一致性优于 OpenCap 与 Theia3D。"
    new, why = wording.rewrite(t, basis)
    assert new is None and why == wording.NO_METRIC                     # was “多数值高于”
    assert wording_judge._rewrite(t, basis)[0] is None


def test_best_balance_is_not_a_comparative():
    t = "现有无标记方案在准确性、灵活性与可部署性之间尚未取得最佳平衡：OpenCap 超过两台相机后准确度无显著提升，Theia3D 需要密集相机阵列和专有软件。"
    assert wording.gate(t, "摘要：现有方案尚未取得最佳平衡。") == (t, None)   # was “数值最高平衡”
    assert wording_judge.candidates({"sections": {"s1": {"paragraphs": [{"text": t, "basis_block_ids": ["b1"], "label": "PAPER"}]}}}, {}) == []
    assert wording.gate("DeepGaitLab 的 ICC 最佳，最佳平衡仍待研究", None)[0] == "DeepGaitLab 的 ICC 数值最高，最佳平衡仍待研究"


def test_yes_no_question_heading_passes_statement_heading_gated():
    q = "无活动限制人群中 DeepGaitLab 的运动学一致性是否优于对照工具？"
    assert wording.gate(q, None) == (q, None)                           # was “是否数值高于”
    assert wording.gate("DeepGaitLab 优于对照工具", None)[0] is None
    assert wording.gate("DeepGaitLab 为何优于对照工具？", None)[0] is None  # not a yes/no question: still gated
