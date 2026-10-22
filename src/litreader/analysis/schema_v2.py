"""Schema v2: reading-note content. Every statement carries label + basis_block_ids; PAPER items are gated."""
from __future__ import annotations

SECTIONS = {  # per spec Appendix A as embodied in the user's reference note
    "s1": "一、为什么读这篇", "s2": "二、研究设计与对象", "s3": "三、实验怎么做", "s4": "四、核心结果",
    "s5": "五、", "s6": "六、作者结论与独立科研评价", "s7": "七、最影响结论与复现的待核实问题",
    "s8": "八、本篇论文最值得借鉴的3件事", "s9": "九、待解决问题与我的批注", "s10": "十、证据与阅读导航",
}
META_FIELDS = ["title_zh", "title_en", "authors", "year", "journal", "doi", "study_type"]

DOC = """
你在为中文科研精读笔记（L2）准备结构化内容。只依据输入原文块；不得使用外部知识补充事实；不得编造。
“陈述”(statement) 统一格式：{"text": 中文句子, "label": "PAPER"|"INFERENCE", "basis_block_ids": ["b12",...], "link_label": 2-4字短标签如"方法""表1""结果"}
- PAPER = 原文直接报告（可中文转述，但其中出现的每个数字都必须在依据块中原样出现）；INFERENCE = 你的独立科研评价/推断。
- 依据块必须来自输入中的 [bN|pM|kind] 标注，至少 1 个。不得输出 {{...}}、TODO、示例等占位符。
- 首次出现的英文缩写请在 abbreviations 中给出中文释义（缩写必须在原文出现）。全文用中文；英文术语第一次出现时写成“中文（English）”。
- 所有小标题（heading_suffix、s5.heading、figures.title）都必须是问句，以“？”结尾。
- s4 段落必须覆盖每一个验证人群（含 MCI、卒中、患者等临床人群）的主要定量结果；facts 里的关键结果数字都要在 s2–s5 某段出现。
- 同一内容只写一次：不要在不同段落/字段重复同一句话或同一组数字。
返回唯一 JSON 对象：
{
 "meta": {字段名: {"value": str|null, "context": 原文逐字片段|null, "block_id": str|null, "physical_page": int|null, "label": "PAPER"|"UNKNOWN"}}，字段为 META_FIELDS；原文没有英文原题时 title_en 必须 UNKNOWN,
 "topic": 中文主题分类（≤10字）, "tags": [≤5 个中文标签],
 "facts": [{"field": 英文短字段名, "value": 原文逐字短片段, "context": 含 value 的原文逐字连续片段(≤200字), "block_id": str, "physical_page": int, "label": "PAPER"|"UNKNOWN"}]  (关键数字/分母/设计/结论，10–25 条，每个 field 只出现一次),
 "three_minute": {"what": 陈述, "how": 陈述, "key_result": 陈述(PAPER), "value": 陈述(INFERENCE，通用科研价值，因无关联课题), "caution": 陈述},
 "one_liner": 陈述(INFERENCE，最值得长期记住的一句话),
 "sections": {
   "s1": {"heading_suffix": 问句式小标题, "paragraphs": [陈述], "supports": [陈述], "cannot_answer": [陈述]},
   "s2": {"heading_suffix": ..., "paragraphs": [...], "tables": [表格]}   ← s2 必须有“招募/最终分析分母”表,
   "s3": {"heading_suffix": ..., "paragraphs": [...], "tables": [...]},
   "s4": {"heading_suffix": ..., "paragraphs": [...], "tables": [...], "negative_results": [陈述]},
   "s5": {"heading": 本文特有的深入主题，必须写成问句（以“？”结尾，不含序号）, "paragraphs": [...]},
   "s6": {"author_conclusion": 陈述(PAPER), "evaluation": 陈述(INFERENCE)},
   "s7": {"items": [陈述]}  (最影响结论与复现的 3–5 个待核实问题),
   "s8": {"items": [{"title": str, "basis": 陈述(PAPER), "help": 陈述(INFERENCE), "limit": 陈述}] (3 项), "review_summary": 陈述(INFERENCE，可用于综述起草的概括)},
   "s9": {"next_checks": [str]}
 },
 表格 = {"title": str, "label": "PAPER", "columns": [str], "rows": [[str]], "basis_block_ids": [str]}  (单元格数字必须原样见于依据块；每一行的含义必须与列标题一致——比较对象不同（如“工具A 对 工具B”与“患者 对 健康者”）必须分成不同的表；原文没有的单元格不要写数字),
 "figures": [{"id": 输入图表清单中的 id, "section": "s2".."s5", "title": 问句式短标题,
              "finding": 陈述(PAPER，仅依据图注与正文), "interpretation": 陈述(INFERENCE), "limitation": 陈述}],
 "abbreviations": [{"abbr": str, "zh": str}],
 "unknowns": [{"item": 中文, "why": 中文}]  (原文缺失/冲突/无法确认的事项)
}
"""
