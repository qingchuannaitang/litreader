---
litreader_template: 1
id: module.rct
title: RCT/干预研究评价模块
role: module
version: 1.0.0
applies_to:
  study_types: [rct, non_randomized_intervention]
  reading_levels: [L2, L3]
priority: 50
compatible_with: [any_main]
adds_fields:
  - {name: randomization, label: 随机化方法, label_rule: ANY, description: 随机序列如何产生；非随机研究写分组方式}
  - {name: allocation_concealment, label: 分配隐藏, label_rule: ANY, description: 分配方案是否隐藏及方式}
  - {name: blinding, label: 盲法, label_rule: ANY, description: 受试者、实施者、结局评估者是否设盲}
  - {name: attrition_itt, label: 失访与意向性分析, label_rule: ANY, description: 各组失访人数与是否按意向性分析}
  - {name: primary_outcome_effect, label: 主要结局效应量, label_rule: PAPER, description: 主要结局的组间差异、效应量与置信区间}
  - {name: adverse_events, label: 不良事件, label_rule: ANY, description: 不良事件或安全性报告}
adds_sections:
  - {id: mod_rct, title: RCT/干预研究专项评价（专业模块）, blocks: [module_fields, paragraphs]}
---
# RCT/干预研究评价模块（预览）

## RCT/干预研究专项评价（专业模块）
> 写作提示：按随机化、分配隐藏、盲法、失访与意向性分析、主要结局效应量、不良事件逐项写；原文未报告的一项写 UNKNOWN；不显著不等于无效。
