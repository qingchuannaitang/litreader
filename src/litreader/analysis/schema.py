"""Structured analysis schema (R1/R2). Every fact/claim is PAPER, INFERENCE or UNKNOWN."""
from __future__ import annotations

LABELS = {"PAPER", "INFERENCE", "UNKNOWN"}

# Fields an L2 note must address; absent => UNKNOWN is enforced by the validator.
REQUIRED_FIELDS = [
    "study_design", "setting_country", "sample_size_total", "groups_and_sizes", "diagnostic_criteria",
    "inclusion_exclusion", "gait_measurement_device", "primary_outcomes", "statistical_methods",
    "key_result_1", "key_result_2", "negative_or_null_results", "author_conclusion", "limitations_reported",
    "funding", "ethics_approval",
]

SCHEMA_DOC = """
返回唯一 JSON 对象：
{
 "title_zh": {"value": str|null, "block_id": str|null, "physical_page": int|null, "label": "PAPER"|"UNKNOWN"},
 "title_en": {同上；若原文中没有英文原题则 label=UNKNOWN, value=null},
 "facts": [
   {"field": <REQUIRED_FIELDS 之一或其他简短英文字段名>,
    "value": str,            # 必须是原文中逐字出现的短片段（数字、术语等）；UNKNOWN 时为 null
    "context": str,          # 必须是包含 value 的原文逐字连续片段（≤200字），不可改写、不可翻译
    "block_id": str,         # 例如 "b42"，必须来自输入中的方括号标注
    "physical_page": int,    # 必须等于该 block 的 p 值
    "label": "PAPER" | "UNKNOWN"}
 ],
 "claims": [
   {"text": str,             # 中文概括或独立评价
    "label": "PAPER" | "INFERENCE",   # PAPER=作者原述的转述；INFERENCE=你的独立推断/评价
    "basis_block_ids": [str, ...],    # 依据的 block_id，至少 1 个
    "kind": "summary" | "method" | "result" | "limitation" | "evaluation" | "conclusion"}
 ]
}
规则：
1. 原文没有的内容必须用 label=UNKNOWN、value=null、context=null、block_id=null、physical_page=null。不得猜测、不得补全。
2. 每个 REQUIRED_FIELDS 字段都必须出现在 facts 中（找不到就 UNKNOWN）。
3. 推导集/验证集、组别、样本分母不能混淆；阴性结果也要报告。
4. 不得输出 {{...}}、TODO、示例占位符。
"""
