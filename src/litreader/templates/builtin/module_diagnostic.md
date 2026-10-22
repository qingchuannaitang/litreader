---
litreader_template: 1
id: module.diagnostic
title: 诊断准确性与预测模型评价模块
role: module
version: 1.0.0
applies_to:
  study_types: [diagnostic_accuracy, prediction_model]
  reading_levels: [L2, L3]
priority: 50
compatible_with: [any_main]
adds_fields:
  - {name: reference_standard, label: 参考标准, label_rule: ANY, description: 金标准或参考标准是什么，是否对所有受试者统一实施}
  - {name: index_test_threshold, label: 指标/模型与阈值, label_rule: ANY, description: 待评价指标或模型及其阈值是否预先设定}
  - {name: derivation_performance, label: 推导集性能, label_rule: PAPER, description: 推导/训练集的 AUC、敏感度、特异度（只写推导集）}
  - {name: validation_performance, label: 验证集性能, label_rule: PAPER, description: 内部或外部验证集的性能，与推导集分开}
  - {name: calibration, label: 校准, label_rule: ANY, description: 校准曲线或校准指标；未报告写 UNKNOWN}
  - {name: spectrum_bias, label: 病例谱与偏倚, label_rule: INFERENCE, description: 病例谱、验证偏倚、过拟合风险}
adds_sections:
  - {id: mod_diag, title: 诊断准确性与预测模型专项评价（专业模块）, blocks: [module_fields, paragraphs]}
---
# 诊断准确性与预测模型评价模块（预览）

## 诊断准确性与预测模型专项评价（专业模块）
> 写作提示：推导集与验证集的 AUC、敏感度、特异度必须分开写，不得混用；“数值最高”不等于差异有统计学显著性；未做外部验证要明确说明。
