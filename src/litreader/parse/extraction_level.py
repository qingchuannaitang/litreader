"""Extraction completeness level E0-E4 (ROADMAP_v2 §2.1), computed only from our own checks.

E0  no extractable body text OR encrypted                                              -> STOP
E1  page map inconsistent, OR pages with NO content inside methods/results, OR such pages > 20 % of the PDF -> STOP
E2  every page is covered (see below), or a few content-less pages outside methods/results (listed as UNKNOWN pages)
E3  E2 with every page covered AND >=1 visual detected AND every table part has HTML or image AND every visual part
    has an existing image file (when assets_dir given) on a valid page
E4  E3 AND >=1 supplementary file registered with sha256

A page is COVERED when it has body text, or a figure/chart, table, equation, caption, reference list, title block, or
other real content (side note, footnote) — or it lies in recognised back matter (references / appendix / supplement /
acknowledgements) and has any block. A page is MISSING only when it has nothing, or only header/footer/page number.
(Full-page figures are the common case: MinerU puts the caption inside the image block, so such a page has no text.)
Conservative choices: zero detected visuals caps at E2 (cannot verify figures); missing assets_dir caps at E2.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .blocks import BODY_KINDS, ParseResult

MAX_MISSING_SHARE = 0.20
CHROME = {"header", "footer", "page_number"}
KIND_ZH = {"text": "正文", "figure": "整页图（无正文）", "table": "表格（无正文）", "equation": "公式（无正文）",
           "caption": "只有图注/表注", "reference": "参考文献", "title": "只有标题", "back_matter": "附录/补充材料/致谢",
           "other": "只有旁注/脚注", "chrome_only": "只有页眉页脚/页码", "empty": "空白（没有任何内容）"}
CORE_START = re.compile(r"^\s*(?:[0-9IVX]+(?:\.[0-9]+)*\.?\s*)?(?:materials?\s+and\s+methods|methods?|methodology|"
                        r"experimental\s+(?:setup|design|procedures?)|experiments?|results?|"
                        r"材料与方法|对象与方法|资料与方法|研究方法|方法|结果|实验)\b", re.I)
CORE_END = re.compile(r"^\s*(?:[0-9IVX]+(?:\.[0-9]+)*\.?\s*)?(?:discussion|conclusions?|limitations|references|bibliography|"
                      r"acknowledge?ments?|supplementary|supplemental|appendix|appendices|"
                      r"讨论|结论|局限|参考文献|致谢|附录|补充材料)\b", re.I)
BACK = re.compile(r"^\s*(?:[0-9IVX]+(?:\.[0-9]+)*\.?\s*)?(?:references|bibliography|acknowledge?ments?|supplementary|"
                  r"supplemental|appendix|appendices|extended\s+data|参考文献|致谢|附录|补充材料)\b", re.I)


@dataclass
class ExtractionReport:
    level: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def page_kinds(res: ParseResult, n: int) -> dict[int, str]:
    """Kind of every page 1..n (see KIND_ZH)."""
    by: dict[int, list] = {p: [] for p in range(1, n + 1)}
    for b in res.blocks:
        if b.physical_page in by:
            by[b.physical_page].append(b)
    back_from = min((b.physical_page for b in res.blocks if b.kind == "title" and BACK.match(b.text or "")), default=None)
    out = {}
    for p, bs in by.items():
        real = [b for b in bs if b.kind not in CHROME]
        if any(b.kind in BODY_KINDS and b.text.strip() and b.raw_type != "equation" for b in real):
            k = "text"
        elif any(b.kind == "figure" for b in real):
            k = "figure"
        elif any(b.kind == "table" for b in real):
            k = "table"
        elif any(b.raw_type == "equation" for b in real):
            k = "equation"
        elif any(b.caption.strip() for b in real):
            k = "caption"
        elif any(b.kind == "reference" for b in real):
            k = "reference"
        elif any(b.kind == "title" for b in real):
            k = "title"
        elif real and back_from is not None and p >= back_from:
            k = "back_matter"
        elif real:
            k = "other"
        elif bs:
            k = "chrome_only"
        else:
            k = "empty"
        out[p] = k
    return out


def core_pages(res: ParseResult, n: int) -> set[int]:
    """Pages spanned by methods/results headings up to the next discussion/references/appendix heading."""
    titles = sorted((b for b in res.blocks if b.kind == "title" and b.text.strip()), key=lambda b: (b.physical_page, b.order))
    start = next((b for b in titles if CORE_START.match(b.text)), None)
    if not start:
        return set()
    end = next((b for b in titles if (b.physical_page, b.order) > (start.physical_page, start.order) and CORE_END.match(b.text)
                and not CORE_START.match(b.text)), None)
    last = end.physical_page if end else max((b.physical_page for b in res.blocks if b.kind in BODY_KINDS), default=n)
    return set(range(start.physical_page, min(last, n) + 1))


def describe(pages: list[int], kinds: dict[int, str], core: set[int]) -> str:
    return "；".join(f"第 {p} 页：{KIND_ZH[kinds[p]]}" + ("（在方法/结果部分）" if p in core else "") for p in pages)


def assess(res: ParseResult, pdf_page_count: int, encrypted: bool = False,
           supplements: list[dict] | None = None) -> ExtractionReport:
    m: dict = {"pdf_pages": pdf_page_count, "parser_pages": res.page_count_reported}
    if encrypted:
        return ExtractionReport("E0", ["PDF encrypted"], m)
    body = [b for b in res.blocks if b.kind in BODY_KINDS and b.text.strip()]
    if not body or pdf_page_count <= 0:
        return ExtractionReport("E0", ["no extractable body text"], m)
    reasons = []
    out_of_range = [b.physical_page for b in res.blocks if not 1 <= b.physical_page <= pdf_page_count]
    kinds = page_kinds(res, pdf_page_count)
    core = core_pages(res, pdf_page_count)
    missing = [p for p, k in kinds.items() if k in ("empty", "chrome_only")]
    no_text = [p for p, k in kinds.items() if k != "text"]
    m.update(pages_with_text=pdf_page_count - len(no_text), page_kinds={str(p): kinds[p] for p in no_text},
             missing_pages=missing, core_pages=[min(core), max(core)] if core else None,
             missing_text_pages=no_text)
    if out_of_range:
        reasons.append(f"blocks on pages outside 1..{pdf_page_count}: {sorted(set(out_of_range))}")
    if res.page_count_reported is not None and res.page_count_reported != pdf_page_count:
        reasons.append(f"parser page count {res.page_count_reported} != PDF {pdf_page_count}")
    in_core = [p for p in missing if p in core]
    share = len(missing) / pdf_page_count
    if in_core:
        reasons.append(f"方法/结果部分有页面没有解析出任何内容：{describe(in_core, kinds, core)}")
    if share > MAX_MISSING_SHARE:
        reasons.append(f"没有内容的页面占 {share:.0%}（超过 {MAX_MISSING_SHARE:.0%}）：{describe(missing, kinds, core)}")
    if reasons:
        m["stop_pages"] = in_core or missing
        return ExtractionReport("E1", reasons, m)
    m["unknown_pages"] = [{"page": p, "kind": kinds[p], "why": KIND_ZH[kinds[p]]} for p in missing]
    if missing:
        return ExtractionReport("E2", [f"以下页面没有解析出内容，记为 UNKNOWN 页面：{describe(missing, kinds, core)}"], m)
    vis = [b for b in res.blocks if b.kind in ("figure", "table")]
    m["visual_blocks"] = len(vis)
    if not vis:
        return ExtractionReport("E2", ["no figures/tables detected (E3 not verifiable)"], m)
    if not res.assets_dir:
        return ExtractionReport("E2", ["no assets_dir; image files not checkable"], m)
    bad = []
    for b in vis:
        if b.kind == "table" and not (b.table_html or b.img_path):
            bad.append(f"table p{b.physical_page} has neither HTML nor image")
        if not b.img_path or not os.path.isfile(os.path.join(res.assets_dir, b.img_path)):
            bad.append(f"{b.kind} p{b.physical_page} image missing: {b.img_path}")
    if bad:
        return ExtractionReport("E2", bad, m)
    sup = [s for s in (supplements or []) if s.get("sha256")]
    if sup:
        return ExtractionReport("E4", [f"{len(sup)} supplement(s) registered"], m)
    return ExtractionReport("E3", ["all visuals have page + image (visual check still UNVERIFIED)"], m)
