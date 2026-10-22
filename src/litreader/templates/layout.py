"""Effective layout of a main template + modules, with the code-enforced gates (design §7, spec §5.4/§5.5).

Whatever a template says, the result always contains: the reading convention (PAPER/INFERENCE/UNKNOWN), every core
data section s1–s9 (so no verified content or UNKNOWN is silently dropped), exactly one UNKNOWN top list, exactly one
protected user zone, and the evidence navigation. Missing pieces are re-inserted and reported as warnings.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import vocab
from .format import Section, Template

DEFAULT_SECTIONS = {   # titles/blocks used when a template omits a core data section (same as main.general)
    "s1": ("一、为什么读这篇", ["paragraphs", "supports", "tables", "negative_results", "figures"]),
    "s2": ("二、研究设计与对象", ["paragraphs", "tables", "negative_results", "figures"]),
    "s3": ("三、实验怎么做", ["paragraphs", "tables", "negative_results", "figures"]),
    "s4": ("四、核心结果", ["paragraphs", "tables", "negative_results", "figures"]),
    "s5": ("五、", ["paragraphs", "tables", "negative_results", "figures"]),
    "s6": ("作者结论与独立科研评价", ["author_conclusion", "evaluation"]),
    "s7": ("最影响结论与复现的待核实问题", ["review_items"]),
    "s8": ("本篇论文最值得借鉴的3件事", ["borrow_items"]),
    "s9": ("待解决问题与我的批注", ["next_checks"]),
}


@dataclass
class Layout:
    header: list[str]
    sections: list[Section]
    modules: list[Template] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _find(sections, block):
    return next((i for i, s in enumerate(sections) if block in s.blocks), None)


def build(main: Template, modules: list[Template] = ()) -> Layout:
    w: list[str] = []
    header = list(dict.fromkeys(main.header_blocks))
    if not header:
        header = list(vocab.HEADER_BLOCKS)
    for b in vocab.MANDATORY_HEADER:
        if b not in header:
            header.append(b)
            w.append(f"模板缺少必需块 {b}，已由程序补回")
    secs = [copy.deepcopy(s) for s in main.sections]
    # each mandatory block exactly once (keep the first occurrence)
    for b in ("unknown_top", "protected_zone", "evidence_nav", "module_slot", "project_lens"):
        seen = False
        for s in secs:
            if s.blocks.count(b) > (0 if seen else 1):
                w.append(f"块 {b} 重复出现，只保留第一次")
            if b in s.blocks:
                i = s.blocks.index(b)
                s.blocks = [x for j, x in enumerate(s.blocks) if x != b or (j == i and not seen)]
                seen = True
    for s in secs:   # a block bound to a missing data key cannot silently show other content
        if s.data is None and s.id in vocab.DATA_KEYS:
            s.data = s.id
    # evidence nav last-resort section
    if _find(secs, "evidence_nav") is None:
        secs.append(Section("_evidence", "证据与阅读导航", ["evidence_nav"], "s10"))
        w.append("模板缺少证据导航，已在末尾补回")
    ev = _find(secs, "evidence_nav")
    bound = {s.data for s in secs if s.data}
    missing = [k for k in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9") if k not in bound]
    for k in missing:
        t, blocks = DEFAULT_SECTIONS[k]
        secs.insert(ev, Section(k if k not in {s.id for s in secs} else f"_{k}", t, list(blocks), k,
                                "append" if k == "s5" else "none", "深入分析" if k == "s5" else ""))
        ev += 1
        w.append(f"模板未包含核心章节 {k}（{t}），为不丢失已核验内容已补回")
    if _find(secs, "protected_zone") is None:
        i = _find(secs, "next_checks")
        if i is not None:
            secs[i].blocks.append("protected_zone")
        else:
            secs.insert(_find(secs, "evidence_nav"), Section("_notes", "我的批注", ["protected_zone"], None))
        w.append("模板缺少用户批注保护区，已由程序补回")
    if _find(secs, "unknown_top") is None:
        secs.insert(_find(secs, "evidence_nav"), Section("_unknown", "重点待确认问题（UNKNOWN）", ["unknown_top"], None))
        w.append("模板缺少重点 UNKNOWN 列表，已由程序补回")
    if _find(secs, "project_lens") is None:   # Stage 7: the project view sits right after the "borrow" items
        i = _find(secs, "borrow_items")
        if i is not None:
            bl = secs[i].blocks
            bl.insert(bl.index("borrow_items") + 1, "project_lens")
        else:
            secs.insert(_find(secs, "unknown_top"), Section("_lens", "与当前课题的关联", ["project_lens"], None))
    if not any(s.data == "s10" for s in secs):
        secs[_find(secs, "evidence_nav")].data = "s10"
    # modules: never two main templates; skip a module whose section/field ids collide (spec §5.5, T07)
    used_ids = {s.id for s in secs}
    used_fields: set[str] = set()
    kept = []
    for m in modules:
        ids = {s.id for s in m.adds_sections}
        names = set(m.required_fields)
        if m.role != "MODULE":
            w.append(f"{m.id} 不是专业模块，已跳过")
            continue
        if ids & used_ids or names & used_fields:
            w.append(f"模块 {m.id} 的章节或字段与已选模板重复（{', '.join(sorted((ids & used_ids) | (names & used_fields)))}），本次不用")
            continue
        used_ids |= ids
        used_fields |= names
        kept.append(m)
    return Layout(header, secs, kept, w)


def extra_sections(main: Template, modules: list[Template]) -> list[Section]:
    """Sections the writer must fill through TEMPLATE_DATA (no schema data key)."""
    out = [s for s in main.sections if s.data is None and s.id not in vocab.DATA_KEYS
           and ("paragraphs" in s.blocks or "module_fields" in s.blocks)]
    for m in modules:
        out += m.adds_sections
    return out
