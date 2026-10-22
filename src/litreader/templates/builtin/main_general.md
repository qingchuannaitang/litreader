---
litreader_template: 1
id: main.general
title: 单篇科研精读笔记V2.0
role: main
version: 2.0.0
language: zh-CN
description: 内置通用主模板（照用户认可的 Yang 参考样稿，十章）；无合格专用模板时的回退模板
applies_to:
  study_types: [any]
  reading_levels: [L2]
priority: 10
header_blocks: [info_callout, nav, three_minute, one_liner, pdf_nav, reading_convention]
sections:
  - {id: s1, title: 一、为什么读这篇, suffix: colon, blocks: [paragraphs, supports, tables, negative_results, figures]}
  - {id: s2, title: 二、研究设计与对象, suffix: colon, blocks: [paragraphs, tables, negative_results, figures]}
  - {id: s3, title: 三、实验怎么做, suffix: colon, blocks: [paragraphs, tables, negative_results, figures]}
  - {id: s4, title: 四、核心结果, suffix: colon, blocks: [paragraphs, tables, negative_results, figures]}
  - {id: s5, title: 五、, suffix: append, suffix_default: 深入分析, blocks: [paragraphs, tables, negative_results, figures]}
  - {id: s6, title: 六、作者结论与独立科研评价, blocks: [author_conclusion, evaluation]}
  - {id: s7, title: 七、最影响结论与复现的待核实问题, blocks: [review_items, module_slot]}
  - {id: s8, title: 八、本篇论文最值得借鉴的3件事, blocks: [borrow_items]}
  - {id: s9, title: 九、待解决问题与我的批注, blocks: [next_checks, protected_zone]}
  - {id: unknown, title: 重点待确认问题（UNKNOWN）, blocks: [unknown_top]}
  - {id: s10, title: 十、证据与阅读导航, blocks: [evidence_nav]}
---
# 中文标题（英文原题）

（以下为人类预览；程序只读取上面的 front matter。论文信息卡、三分钟了解、一句话、阅读约定由程序生成。）

## 一、为什么读这篇
## 二、研究设计与对象
## 三、实验怎么做
## 四、核心结果
## 五、〈本文特有的深入主题〉
## 六、作者结论与独立科研评价
## 七、最影响结论与复现的待核实问题
## 八、本篇论文最值得借鉴的3件事
## 九、待解决问题与我的批注
## 重点待确认问题（UNKNOWN）
## 十、证据与阅读导航
