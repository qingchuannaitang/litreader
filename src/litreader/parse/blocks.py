"""Unified block model shared by all parser adapters."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

BODY_KINDS = {"text", "title"}
VISUAL_KINDS = {"figure", "table"}

_NUM = re.compile(r"^\s*(图|Fig(?:ure)?\.?|表|Table|Tab\.?)\s*([0-9]+[A-Za-z]?)", re.I)


@dataclass
class Block:
    kind: str                 # text|title|figure|table|header|footer|page_number|reference|aside|footnote|other
    physical_page: int        # 1-based PDF page
    bbox_norm: tuple[float, float, float, float] | None  # 0-1000 page-normalised (see bbox_space)
    text: str = ""
    raw_type: str = ""
    img_path: str | None = None
    table_html: str | None = None
    caption: str = ""
    footnote: str = ""
    order: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class ParseResult:
    parser: str
    parser_version: str | None
    page_count_reported: int | None
    bbox_space: str           # e.g. "norm1000_assumed" (MinerU, unverified) | "norm1000_from_pixels"
    blocks: list[Block]
    assets_dir: str | None = None


def caption_number(caption: str) -> tuple[str, str] | None:
    """('figure'|'table', number) from a caption like '图 1 | ...' / 'Table 2.' ; None if absent."""
    m = _NUM.match(caption or "")
    if not m:
        return None
    word = m.group(1).lower()
    kind = "table" if word.startswith(("表", "tab")) else "figure"
    return kind, m.group(2)


def cjk_ratio(blocks: list[Block]) -> float:
    txt = "".join(b.text for b in blocks if b.kind in BODY_KINDS)
    letters = [c for c in txt if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u4e00" <= c <= "\u9fff") / len(letters)
