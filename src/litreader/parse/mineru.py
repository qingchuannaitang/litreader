"""MinerU content_list.json -> unified blocks.

Facts from Stage 0 spike (docs/spikes/S0_mineru.md): page_idx is 0-based; bbox values up to ~1000 while
page is 595x779pt => assumed 0-1000 normalised; image/chart/table carry img_path;
bbox space confirmed per axis on DeepGaitLab (2026-10-18): pages are 612x792 pt, yet figure bboxes start at x≈117–122
(= 72 pt / 612) and y≈89–94 (= 72 pt / 792), i.e. 1-inch margins in a 0–1000 space for EACH axis — not points, not
pixels. All ‰ gaps in parse/figures.py (row/adjacency/caption distance) are therefore ‰ of page width/height.
tables carry table_body (HTML) + table_caption/table_footnote.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..errors import Stop
from .blocks import Block, ParseResult

TYPE_MAP = {"text": "text", "image": "figure", "chart": "figure", "table": "table", "header": "header",
            "footer": "footer", "page_number": "page_number", "ref_text": "reference", "aside_text": "aside",
            "page_footnote": "footnote", "equation": "text", "list": "text", "code": "text"}


def _join(v) -> str:
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x)
    return str(v or "")


def _text(it: dict) -> str:
    """Text of a block; list blocks carry list_items, code blocks code_body (both were dropped before)."""
    t = it.get("text") or ""
    if not t and it.get("list_items"):
        t = "\n".join(str(x) for x in it["list_items"] if x)
    if not t and it.get("code_body"):
        t = str(it["code_body"])
    return t


def parse_content_list(items: list[dict], version: str | None = None, assets_dir: str | None = None,
                       page_count: int | None = None) -> ParseResult:
    blocks = []
    for i, it in enumerate(items):
        if "page_idx" not in it or not isinstance(it["page_idx"], int) or it["page_idx"] < 0:
            raise Stop(f"block {i} lacks valid page_idx")
        t = it.get("type", "")
        kind = TYPE_MAP.get(t, "other")
        if kind == "text" and it.get("text_level"):
            kind = "title"
        bbox = it.get("bbox")
        if bbox is not None and (len(bbox) != 4 or max(bbox) > 1000 or min(bbox) < 0):
            raise Stop(f"block {i} bbox outside assumed 0-1000 space: {bbox}")
        cap = _join(it.get("image_caption") or it.get("chart_caption") or it.get("table_caption"))
        foot = _join(it.get("image_footnote") or it.get("chart_footnote") or it.get("table_footnote"))
        blocks.append(Block(kind=kind, physical_page=it["page_idx"] + 1,
                            bbox_norm=tuple(float(x) for x in bbox) if bbox else None,
                            text=_text(it), raw_type=t, img_path=it.get("img_path") or None,
                            table_html=it.get("table_body") or None, caption=cap, footnote=foot, order=i))
    return ParseResult("mineru", version, page_count, "norm1000_assumed", blocks, assets_dir)


def load_extracted_dir(d: Path) -> ParseResult:
    d = Path(d)
    cl = [p for p in d.glob("*_content_list.json")]
    if len(cl) != 1:
        raise Stop(f"expected exactly one *_content_list.json in {d}, found {len(cl)}")
    version = None
    lj = d / "layout.json"
    page_count = None
    if lj.exists():
        lay = json.loads(lj.read_text("utf-8"))
        version = lay.get("_version_name")
        page_count = len(lay.get("pdf_info", [])) or None
    return parse_content_list(json.loads(cl[0].read_text("utf-8")), version, str(d), page_count)
