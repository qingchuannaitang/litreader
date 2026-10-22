"""Section-aware chunking of unified blocks.

Every block gets a stable block_id (b<order>). Chunks never split a section unless the section alone
exceeds max_chars; headers/footers/page numbers/references are excluded from model input.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ..parse.blocks import Block

EXCLUDE = {"header", "footer", "page_number", "reference", "aside", "other", "caption"}


def block_id(b: Block) -> str:
    return f"b{b.order}"


def table_text(h: str | None) -> str:
    if not h:
        return ""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, flags=re.S | re.I)
    out = []
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)]
        out.append(" | ".join(cells))
    return "\n".join(out)


def block_text(b: Block) -> str:
    """The canonical text a fact must be found in (what the validator checks against)."""
    parts = []
    if b.kind == "table":
        parts += [b.caption, table_text(b.table_html), b.footnote]
    elif b.kind == "figure":
        parts += [b.caption, b.footnote]
    else:
        parts.append(b.text)
    return "\n".join(p for p in parts if p).strip()


@dataclass
class Section:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Chunk:
    index: int
    sections: list[str]
    blocks: list[Block]

    def render(self) -> str:
        return "\n".join(f"[{block_id(b)}|p{b.physical_page}|{b.kind}] {block_text(b)}" for b in self.blocks)


def sections(blocks: list[Block]) -> list[Section]:
    out = [Section("（文首）")]
    for b in blocks:
        front = b.physical_page == 1 and b.kind in ("header", "footer")  # page-1 masthead carries DOI/journal
        if (b.kind in EXCLUDE and not front) or not block_text(b):
            continue
        if b.kind == "title":
            out.append(Section(b.text.strip()))
        out[-1].blocks.append(b)
    return [s for s in out if s.blocks]


def chunk(blocks: list[Block], max_chars: int = 60000) -> list[Chunk]:
    chunks: list[Chunk] = []
    cur, cur_titles, size = [], [], 0

    def flush():
        nonlocal cur, cur_titles, size
        if cur:
            chunks.append(Chunk(len(chunks), cur_titles, cur))
        cur, cur_titles, size = [], [], 0

    for s in sections(blocks):
        s_size = sum(len(block_text(b)) + 20 for b in s.blocks)
        if size and size + s_size > max_chars:
            flush()
        if s_size > max_chars:  # oversize section: split by blocks, never inside a block
            for b in s.blocks:
                n = len(block_text(b)) + 20
                if size and size + n > max_chars:
                    flush()
                cur.append(b); size += n
                if s.title not in cur_titles:
                    cur_titles.append(s.title)
            continue
        cur.extend(s.blocks); cur_titles.append(s.title); size += s_size
    flush()
    return chunks
