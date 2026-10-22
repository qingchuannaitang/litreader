"""Group visual blocks into figures/tables and build figures.json manifest (R4)."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from collections import Counter
from pathlib import Path

from .blocks import Block, ParseResult, caption_number

# a caption that MinerU emitted as an ordinary text block ("图 4. …" / "Figure 4 | …")
_CAP_TEXT = re.compile(r"^\s*(?:图|Fig(?:ure)?\.?)\s*(\d+)\s*(?:[.．:：|｜、]|\s)")
# a caption paragraph START (review 4): '图 7.' / '图 7：' / 'Figure 7.' / 'Fig. 7 Effect…'; never '（图 7C）' or
# '图 7 显示…' (a body sentence). Leading markup (**, #, <b>) is ignored; Chinese '图 N' needs punctuation.
_CAP_START = re.compile(r"^(?:图\s*(\d+)\s*[.．:：|｜、]|Fig(?:ure)?\.?\s*(\d+)\s*(?:[.．:：|｜]|\s+(?=[A-Z])))")
_MARKUP = re.compile(r"^(?:[\s*_#>`]|<[^>]{1,10}>)*")
# in-text figure references: "（图 2C）", "(图 5A)", "(Fig. 3b)", "图 2A 所示"
_REF = re.compile(r"(?:图|Fig(?:ure)?\.?)\s*(\d+)\s*[A-Za-z]?(?![\d])")
_END = re.compile(r"[。．.!?！？)）\]】」”\"]\s*$")
# page furniture between a cut caption and its continuation (review 2: Fig1/Fig8 captions stopped mid-word)
_SKIP = {"figure", "table", "header", "footer", "page_number", "aside", "footnote"}
# a figure caption can be detected as a side note / footnote block (review 2: DeepGaitLab Fig4 had no caption)
_CAP_KINDS = ("text", "title", "aside", "footnote")   # a bold caption line can come out as a title block
ROW_GAP = 40        # ‰ of page height: caption-less blocks this close (or in one row) are one figure
CAP_GAP_BELOW = 120  # ‰: caption paragraph directly below the figure
CAP_GAP_ABOVE = 80   # ‰: or directly above it


# a sub-panel label in front of the real caption inside one image/chart caption (review 5, DeepGaitLab p17:
# '(C) 图4. 轻度认知障碍或脑卒中患者…'): '(C) ' / '（A–C）' / 'C. ' / 'C ' — one letter or a letter range only
_PANEL = re.compile(r"^\s*(?:[(（]\s*[A-Za-z](?:\s*[-–—~,，、]\s*[A-Za-z])*\s*[)）]|[A-Za-z][.．]?(?=\s))\s*")


def split_panel_caption(caption: str) -> tuple[str | None, str]:
    """('(C)', '图4. …') when a caption pattern follows a leading panel label; else (None, caption) unchanged.
    The caption text is kept verbatim; a body reference ('(C) 如图 4 所示') is not a caption start."""
    m = _PANEL.match(caption or "")
    if not m or m.end() >= len(caption):
        return None, caption
    rest = caption[m.end():]
    if not cap_start(rest):
        return None, caption
    return caption[:m.end()].strip(), rest.strip()


def cap_start(text: str) -> str | None:
    """Figure number if the paragraph STARTS like a caption, else None."""
    m = _CAP_START.match(_MARKUP.sub("", text or ""))
    return (m.group(1) or m.group(2)) if m else None


def _caption_continuation(cap: str, after: list[Block]) -> tuple[str, int | None]:
    """A caption cut mid-sentence by the parser continues in the next text block on the same/next page."""
    from ..analysis.latex import clean
    if not cap or _END.search(clean(cap)):
        return cap, None
    for b in after:
        if b.kind in _SKIP:
            continue
        if b.kind == "text" and b.text.strip() and not _CAP_TEXT.match(b.text) and not caption_number(b.text):
            sep = "" if re.search(r"[\u4e00-\u9fff\-]$", cap) else " "
            return cap.rstrip("-") + sep + b.text.strip(), b.order
        break
    return cap, None


def group_visuals(res: ParseResult) -> list[dict]:
    vis = []
    for b in res.blocks:
        if b.kind not in ("figure", "table"):
            continue
        label, cap = split_panel_caption(b.caption) if b.kind == "figure" else (None, b.caption)
        if label:   # copy: the parse cache / other readers keep MinerU's caption as emitted
            b = replace(b, caption=cap, meta={**b.meta, "panel_label": label, "caption_split_from_panel": True})
        vis.append(b)
    groups: list[dict] = []
    texts = [b for b in res.blocks if b.kind == "text" and b.text.strip()]
    cap_texts = [b for b in res.blocks if b.kind in _CAP_KINDS and b.text.strip()]
    used_numbers = {caption_number(b.caption)[1] for b in vis if b.kind == "figure" and caption_number(b.caption)
                    and caption_number(b.caption)[0] == "figure"}
    taken_caption_blocks: set[int] = set()
    orphans: list[tuple[int, list[Block]]] = []
    # --- figures: sub-figure merge per page ---
    by_page: dict[int, list[Block]] = {}
    for b in vis:
        if b.kind == "figure":
            by_page.setdefault(b.physical_page, []).append(b)
    for page, items in sorted(by_page.items()):
        captioned = [i for i, b in enumerate(items) if caption_number(b.caption)]
        if not captioned:
            orphans.append((page, items))
            continue
        assign: dict[int, list[Block]] = {i: [] for i in captioned}
        for i, b in enumerate(items):
            nxt = [c for c in captioned if c >= i]
            assign[nxt[0] if nxt else captioned[-1]].append(b)
        for ci in captioned:
            parts = assign[ci]
            flags = ["SUBFIGURES_MERGED"] if len(parts) > 1 else []
            g = _g("figure", caption_number(items[ci].caption)[1], parts, flags, items[ci])
            if items[ci].meta.get("caption_split_from_panel"):
                g["flags"].append("CAPTION_AFTER_PANEL_LABEL")
            groups.append(g)
    # --- figures without any caption on their page (review fix 3) ---
    for page, items in orphans:
        groups.extend(_orphan_groups(page, items, texts, used_numbers, taken_caption_blocks, cap_texts))
    # --- captions cut mid-sentence (review fix 17) ---
    by_order = sorted(res.blocks, key=lambda b: b.order)
    pos = {b.order: i for i, b in enumerate(by_order)}
    for g in groups:
        if g["kind"] != "figure" or not g["caption"]:
            continue
        anchor = g.get("caption_block", max(p["order"] for p in g["parts"]))
        i = pos.get(anchor)
        if i is None:
            continue
        nxt = [b for b in by_order[i + 1:i + 9] if b.physical_page - by_order[i].physical_page in (0, 1)
               and b.order not in taken_caption_blocks]
        cap, used = _caption_continuation(g["caption"], nxt)
        if used is not None:
            g["caption"] = cap
            g["flags"].append("CAPTION_CONTINUED")
    # --- tables: continuation handling ---
    last_table: dict | None = None
    for b in [v for v in vis if v.kind == "table"]:
        num = caption_number(b.caption)
        if num and num[0] == "table":
            last_table = _g("table", num[1], [b], [], b)
            groups.append(last_table)
        elif last_table and b.physical_page - max(p["physical_page"] for p in last_table["parts"]) in (0, 1):
            last_table["parts"].append(_part(b))
            if "CONTINUATION_ASSUMED" not in last_table["flags"]:
                last_table["flags"].append("CONTINUATION_ASSUMED")
        else:
            groups.append(_g("table", None, [b], ["UNCAPTIONED"]))
    return sorted(groups, key=lambda g: (g["parts"][0]["physical_page"], g["parts"][0]["order"]))


def _clusters(items: list[Block]) -> list[list[Block]]:
    """Caption-less blocks of one page -> figures: blocks in one row (vertical overlap) or vertically adjacent
    (gap ≤ ROW_GAP) belong together. Blocks without bbox join the first cluster."""
    boxed = [b for b in items if b.bbox_norm]
    cl: list[list[Block]] = []
    for b in sorted(boxed, key=lambda b: (b.bbox_norm[1], b.bbox_norm[0])):
        for c in cl:
            y0, y1 = min(x.bbox_norm[1] for x in c), max(x.bbox_norm[3] for x in c)
            if b.bbox_norm[1] <= y1 + ROW_GAP and b.bbox_norm[3] >= y0 - ROW_GAP:
                c.append(b)
                break
        else:
            cl.append([b])
    rest = [b for b in items if not b.bbox_norm]
    if rest:
        cl = [cl[0] + rest] + cl[1:] if cl else [rest]
    return [sorted(c, key=lambda b: b.order) for c in cl]


def _adjacent_caption(cluster: list[Block], cap_texts, used_numbers, taken) -> Block | None:
    """A caption paragraph directly below (≤ CAP_GAP_BELOW) or above (≤ CAP_GAP_ABOVE) the cluster on the same page,
    overlapping it horizontally; nearest wins (below preferred on a tie)."""
    bbs = [b.bbox_norm for b in cluster if b.bbox_norm]
    if not bbs:
        return None
    page = cluster[0].physical_page
    x0, y0, x1, y1 = min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)
    best = None
    for t in cap_texts:
        if t.physical_page != page or not t.bbox_norm or t.order in taken:
            continue
        n = cap_start(t.text)
        if not n or n in used_numbers or min(x1, t.bbox_norm[2]) <= max(x0, t.bbox_norm[0]):
            continue
        below, above = t.bbox_norm[1] - y1, y0 - t.bbox_norm[3]
        if -10 <= below <= CAP_GAP_BELOW:
            d = (max(below, 0), 0)
        elif -10 <= above <= CAP_GAP_ABOVE:
            d = (max(above, 0), 1)
        else:
            continue
        if best is None or d < best[0]:
            best = (d, t)
    return best[1] if best else None


def _orphan_groups(page, items, texts, used_numbers, taken, cap_texts) -> list[dict]:
    """Review 4: each row/adjacent cluster of caption-less blocks whose caption paragraph sits directly below/above it
    becomes that numbered figure (DeepGaitLab p21: three box-plot blocks + the text paragraph '图 7. …' below). The
    remaining blocks of the page keep the earlier behaviour together (_orphan_group)."""
    out, rest = [], []
    for c in _clusters(items):
        t = _adjacent_caption(c, cap_texts, used_numbers, taken)
        if t is None:
            rest += c
            continue
        n = cap_start(t.text)
        used_numbers.add(n); taken.add(t.order)
        g = _g("figure", n, c, (["SUBFIGURES_MERGED"] if len(c) > 1 else []) + ["CAPTION_FROM_TEXT", "CAPTION_ADJACENT"])
        g["caption"], g["caption_block"] = t.text.strip(), t.order
        out.append(g)
    if rest:
        out.append(_orphan_group(page, sorted(rest, key=lambda b: b.order), texts, used_numbers, taken, cap_texts))
    return out


def _orphan_group(page, items, texts, used_numbers, taken, cap_texts=None):
    """Uncaptioned figure blocks of one page become ONE figure:
    1) caption found as a text block ('图 N. …') on the same page, else the next, else the previous page;
    2) else the figure number inferred from in-text references ('（图 2C）') near the page;
    3) else one uncaptioned, unnumbered figure (all blocks of the page together), flagged UNCAPTIONED_ORPHAN.
    Review 3: uncaptioned blocks are never merged into a captioned figure on another page any more — on DeepGaitLab
    three p21 blocks were shown under 图 6 (p20) although the user found no such sub-figures on p21; what they are can
    only be checked in the PDF / MinerU cache (`litreader inspect-parse <job> --page 21`)."""
    parts = list(items)
    flags = ["SUBFIGURES_MERGED"] if len(parts) > 1 else []
    for p in (page, page + 1, page - 1):
        for t in (cap_texts if cap_texts is not None else texts):
            n = cap_start(t.text)
            if t.physical_page == p and n and n not in used_numbers and t.order not in taken:
                used_numbers.add(n); taken.add(t.order)
                g = _g("figure", n, parts, flags + ["CAPTION_FROM_TEXT"])
                g["caption"], g["caption_block"] = t.text.strip(), t.order
                return g
    refs = Counter()
    for t in texts:
        if page - 2 <= t.physical_page <= page + 1:
            for m in _REF.finditer(t.text):
                if m.group(1) not in used_numbers:
                    refs[(m.group(1), abs(t.physical_page - page))] += 1
    if refs:
        best = Counter()
        for (n, dist), k in refs.items():
            best[n] += k * (3 - min(dist, 2))      # nearer references weigh more
        n = max(best, key=lambda x: (best[x], -int(x)))
        used_numbers.add(n)
        return _g("figure", n, parts, flags + ["NUMBER_INFERRED_FROM_TEXT", "UNCAPTIONED"])
    return _g("figure", None, parts, flags + ["UNCAPTIONED", "UNCAPTIONED_ORPHAN"])


def _part(b: Block) -> dict:
    d = {"img_path": b.img_path, "physical_page": b.physical_page, "bbox_norm": b.bbox_norm,
         "has_table_html": bool(b.table_html), "order": b.order}
    if b.meta.get("panel_label") or _PANEL.fullmatch(b.caption or ""):
        d["panel_label"] = b.meta.get("panel_label") or b.caption.strip()
    return d


def _g(kind, number, parts, flags, cap_block: Block | None = None) -> dict:
    return {"kind": kind, "number": number, "caption": cap_block.caption if cap_block else "",
            "footnote": cap_block.footnote if cap_block else "", "parts": [_part(p) for p in parts],
            "flags": list(flags)}


def build_manifest(res: ParseResult, pdf_sha256: str, attachment_key: str) -> list[dict]:
    out = []
    for i, g in enumerate(group_visuals(res), 1):
        label = f"{'Fig' if g['kind']=='figure' else 'Table'}{g['number']}" if g["number"] else f"{g['kind']}_unnumbered_{i}"
        out.append({**g, "id": label, "type_tag": "ORIGINAL_EXCERPT", "vision_summary": None,
                    "visual_check": "UNVERIFIED",
                    "provenance": {"pdf_sha256": pdf_sha256, "attachment_key": attachment_key,
                                   "parser": res.parser, "parser_version": res.parser_version,
                                   "bbox_space": res.bbox_space}})
    return out


def write_manifest(manifest: list[dict], path: Path) -> None:
    with open(path, "x", encoding="utf-8") as f:  # exclusive create
        json.dump(manifest, f, ensure_ascii=False, indent=2)
