"""Minimal L2 note renderer (draft). Chinese; only validated content is rendered.

Page links use zotero://open-pdf/library/items/<attachment_key>?page=N. Each link is labelled
UNVERIFIED (R3): only the URL mechanism may be marked verified; individual links are never
claimed to land on the right page unless a human clicked them.
"""
from __future__ import annotations

from ..analysis.validator import ValidationReport
from .protected_zone import BEGIN, END

FIELD_ZH = {
    "study_design": "研究设计", "setting_country": "研究地点", "sample_size_total": "总样本量",
    "groups_and_sizes": "分组与各组人数", "diagnostic_criteria": "诊断标准", "inclusion_exclusion": "纳入/排除",
    "gait_measurement_device": "步态测量设备", "primary_outcomes": "主要结局指标", "statistical_methods": "统计方法",
    "key_result_1": "关键结果 1", "key_result_2": "关键结果 2", "negative_or_null_results": "阴性/无差异结果",
    "author_conclusion": "作者结论", "limitations_reported": "作者自述局限", "funding": "资助", "ethics_approval": "伦理审批",
}
KIND_ZH = {"summary": "三分钟读懂", "method": "方法要点", "result": "主要结果", "limitation": "局限",
           "conclusion": "结论", "evaluation": "独立评价（INFERENCE）"}


def page_link(attachment_key: str, page: int | None) -> str:
    if not page:
        return ""
    return f"[p.{page}](zotero://open-pdf/library/items/{attachment_key}?page={page}) `UNVERIFIED`"


def render(rep: ValidationReport, *, attachment_key: str, translation_notice: str | None,
           link_mechanism_verified: bool, e_level: str, model: str) -> str:
    zh = (rep.title_zh or {}).get("value") or "UNKNOWN"
    en = (rep.title_en or {}).get("value") or "英文原题 UNKNOWN"
    L = [f"# {zh}（{en}）", ""]
    if translation_notice:
        L += [f"> [!warning] 版本声明", f"> {translation_notice}", ""]
    mech = "已核验" if link_mechanism_verified else "未核验"
    L += ["> [!info] 生成信息",
          f"> 级别 L2（草稿）· 抽取完整度 {e_level} · 模型 {model}",
          f"> 页码链接：链接机制{mech}；下文每条页码链接均为 `UNVERIFIED`（未逐条点击核验）。",
          "> 标签：PAPER=原文逐字核对通过；INFERENCE=模型推断；UNKNOWN=原文未找到。", ""]
    L += ["## 研究信息卡", "", "| 项目 | 内容 | 标签 | 出处 |", "|---|---|---|---|"]
    order = {k: i for i, k in enumerate(FIELD_ZH)}
    for f in sorted(rep.facts, key=lambda f: order.get(f.get("field"), 999)):
        name = FIELD_ZH.get(f.get("field"), f.get("field"))
        val = (f.get("value") or "UNKNOWN").replace("|", "\\|").replace("\n", " ")
        L.append(f"| {name} | {val} | {f['label']} | {page_link(attachment_key, f.get('physical_page'))} |")
    L.append("")
    for kind in KIND_ZH:
        cs = [c for c in rep.claims if c.get("kind") == kind]
        if not cs:
            continue
        L += [f"## {KIND_ZH[kind]}", ""]
        for c in cs:
            L.append(f"- {c['text']} `{c['label']}` （依据 {', '.join(c['basis_block_ids'])}）")
        L.append("")
    unk = [FIELD_ZH.get(f["field"], f["field"]) for f in rep.facts if f["label"] == "UNKNOWN"]
    if unk:
        L += ["## 原文未找到（UNKNOWN）", "", "、".join(unk), ""]
    L += ["## 校验摘要", "", f"- 通过的 PAPER 事实：{rep.counts['facts_paper_ok']}；被拒：{rep.counts['rejected']}；"
          f"强制 UNKNOWN：{rep.counts['enforced_unknown']}", ""]
    L += ["## 我的批注", "", BEGIN, "", END, ""]
    return "\n".join(L)
