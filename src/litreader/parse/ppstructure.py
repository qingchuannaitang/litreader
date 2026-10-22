"""PP-StructureV3 (AI Studio jobs API JSONL) -> unified blocks.

Facts from spike (docs/spikes/S0_paddle.md): no page field; page = JSONL line order (0-based) + 1;
bbox in rendered-page pixels (prunedResult width/height); captions are separate 'figure_title' blocks.
"""
from __future__ import annotations

import json

from ..errors import Stop
from .blocks import Block, ParseResult, caption_number

LABEL_MAP = {"text": "text", "paragraph_title": "title", "doc_title": "title", "abstract": "text",
             "image": "figure", "chart": "figure", "table": "table", "header": "header", "header_image": "header",
             "footer": "footer", "number": "page_number", "reference": "reference", "aside_text": "aside",
             "footnote": "footnote", "vision_footnote": "footnote", "formula": "text", "figure_title": "caption"}


def _bbox(v):
    if isinstance(v, str):
        v = json.loads(v)
    return [float(x) for x in v]


def parse_jsonl(text: str, max_caption_gap: float = 120.0) -> ParseResult:
    blocks: list[Block] = []
    order = 0
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    for page_i, ln in enumerate(lines):
        results = json.loads(ln)["result"]["layoutParsingResults"]
        if len(results) != 1:
            raise Stop(f"line {page_i}: expected 1 page result, got {len(results)} (page mapping ambiguous)")
        pr = results[0]["prunedResult"]
        w, h = float(pr["width"]), float(pr["height"])
        page_blocks = []
        for b in pr.get("parsing_res_list", []):
            x0, y0, x1, y1 = _bbox(b["block_bbox"])
            nb = (x0 / w * 1000, y0 / h * 1000, x1 / w * 1000, y1 / h * 1000)
            kind = LABEL_MAP.get(b["block_label"], "other")
            blk = Block(kind=kind, physical_page=page_i + 1, bbox_norm=nb, raw_type=b["block_label"], order=order,
                        text=b.get("block_content", "") if kind not in ("figure", "table") else "",
                        table_html=b.get("block_content") if kind == "table" else None)
            if kind in ("figure", "table"):
                blk.img_path = f"page_{page_i:03d}/imgs/img_in_{b['block_label']}_box_{int(x0)}_{int(y0)}_{int(x1)}_{int(y1)}.jpg"
            order += 1
            page_blocks.append(blk)
        _pair_captions(page_blocks, max_caption_gap)
        blocks.extend(b for b in page_blocks if b.kind != "caption" or not b.meta.get("paired"))
    return ParseResult("ppstructure_v3", None, len(lines), "norm1000_from_pixels", blocks)


def _pair_captions(page_blocks: list[Block], gap: float) -> None:
    """Greedy nearest-vertical pairing, each caption used once; kind of caption must match visual kind."""
    caps = [b for b in page_blocks if b.kind == "caption"]
    vis = [b for b in page_blocks if b.kind in ("figure", "table")]
    pairs = []
    for c in caps:
        num = caption_number(c.text)
        for v in vis:
            if num and num[0] != v.kind:
                continue
            d = min(abs(c.bbox_norm[1] - v.bbox_norm[3]), abs(v.bbox_norm[1] - c.bbox_norm[3]))
            if d <= gap:
                pairs.append((d, id(c), c, v))
    used_c, used_v = set(), set()
    for d, _, c, v in sorted(pairs, key=lambda p: p[0]):
        if id(c) in used_c or id(v) in used_v:
            continue
        v.caption, c.meta["paired"] = c.text, True
        used_c.add(id(c)); used_v.add(id(v))
