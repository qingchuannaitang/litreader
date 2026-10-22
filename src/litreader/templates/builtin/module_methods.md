---
litreader_template: 1
id: module.methods
title: 方法学/技术/AI 研究评价模块
role: module
version: 1.0.0
applies_to:
  study_types: [methods_technical, prediction_model]
  reading_levels: [L2, L3]
priority: 40
compatible_with: [any_main]
adds_fields:
  - {name: data_source_split, label: 数据来源与划分, label_rule: ANY, description: 数据集来源、样本量、训练/验证/测试划分方式}
  - {name: baseline_comparison, label: 对照方法, label_rule: ANY, description: 与哪些基线方法比较，比较是否公平}
  - {name: ablation, label: 消融与敏感性分析, label_rule: ANY, description: 关键组件的消融实验或敏感性分析}
  - {name: external_validation, label: 外部验证, label_rule: ANY, description: 是否在独立数据上验证}
  - {name: code_data_availability, label: 代码与数据可得性, label_rule: ANY, description: 代码、模型、数据是否公开}
  - {name: failure_modes, label: 失败情形与适用边界, label_rule: INFERENCE, description: 方法可能失效的场景}
adds_sections:
  - {id: mod_ai, title: 方法学/技术/AI 研究专项评价（专业模块）, blocks: [module_fields, paragraphs]}
---
# 方法学/技术/AI 研究评价模块（预览）

## 方法学/技术/AI 研究专项评价（专业模块）
> 写作提示：区分作者报告的性能（PAPER）与对可复现性的判断（INFERENCE）；测试集结果不得与训练集混写；未公开代码或数据要说明。
