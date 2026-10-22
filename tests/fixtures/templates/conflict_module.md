---
litreader_template: 1
id: user.dup_module
title: 与 RCT 模块冲突的模块
role: module
applies_to:
  study_types: [rct]
compatible_with: [any_main]
adds_fields:
  - {name: randomization, label: 随机化（重复）, label_rule: ANY, description: 与内置 RCT 模块重名}
adds_sections:
  - {id: mod_rct, title: 重复章节, blocks: [module_fields]}
---
