---
litreader_template: 1
id: module.sysreview
title: 系统综述/Meta 分析评价模块
role: module
version: 1.0.0
applies_to:
  study_types: [systematic_review]
  reading_levels: [L2, L3]
priority: 50
compatible_with: [any_main]
adds_fields:
  - {name: search_strategy, label: 检索策略, label_rule: ANY, description: 数据库、检索时间范围、是否注册方案}
  - {name: eligibility, label: 纳入排除标准, label_rule: ANY, description: PICOS 纳入与排除标准}
  - {name: risk_of_bias_tool, label: 偏倚风险工具, label_rule: ANY, description: 使用的偏倚风险评价工具及主要结果}
  - {name: heterogeneity, label: 异质性, label_rule: PAPER, description: I² 等异质性统计量及处理方式}
  - {name: pooled_effect, label: 合并效应量, label_rule: PAPER, description: 主要结局合并效应量与置信区间}
  - {name: publication_bias, label: 发表偏倚与证据确定性, label_rule: ANY, description: 漏斗图/Egger 检验、GRADE 证据等级}
adds_sections:
  - {id: mod_sr, title: 系统综述/Meta 分析专项评价（专业模块）, blocks: [module_fields, paragraphs]}
---
# 系统综述/Meta 分析评价模块（预览）

## 系统综述/Meta 分析专项评价（专业模块）
> 写作提示：先写检索与纳入，再写偏倚风险与异质性，最后写合并效应量；纳入研究数和总样本量要与原文一致；未报告的项目写 UNKNOWN。
