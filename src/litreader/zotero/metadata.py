"""Bibliographic metadata from a Zotero item (Local API JSON `{"key":..., "data":{...}}`).

Zotero metadata is user-curated and outranks text extraction for authors/journal/English title/year/DOI.
Values are labelled ZOTERO; anything absent stays None (renderer shows UNKNOWN).
"""
from __future__ import annotations

import re



def _cjk(s: str) -> float:
    chars = [c for c in s if not c.isspace()]
    return sum(1 for c in chars if "\u4e00" <= c <= "\u9fff") / len(chars) if chars else 0.0


def from_item(item: dict | None) -> dict:
    if not item:
        return {}
    d = item.get("data") or item
    out = {"parent_key": item.get("key") or d.get("key")}
    names, last = [], []
    for c in d.get("creators") or []:
        if c.get("creatorType", "author") != "author":
            continue
        fn, ln = (c.get("firstName") or "").strip(), (c.get("lastName") or "").strip()
        cjk = _cjk(fn + ln) > 0.5   # Chinese/Japanese/Korean names: family name first, no space ("王鸿涛")
        n = c.get("name") or ((ln + fn) if cjk else " ".join(x for x in (fn, ln) if x))
        if n.strip():
            names.append(n.strip())
            last.append((c.get("lastName") or n.split()[-1]).strip())
    if names:
        out["authors"] = names[0] + (" 等" if len(names) > 1 else "")
        out["authors_full"] = names
        out["authors_last"] = last
    title = (d.get("title") or "").strip()
    if title and _cjk(title) < 0.2:          # translated PDFs: Zotero title is the English original
        out["title_en"] = title
    elif title:
        out["title_zh_zotero"] = title
    if (d.get("publicationTitle") or "").strip():
        out["journal"] = d["publicationTitle"].strip()
    y = re.search(r"\b(19|20)\d{2}\b", d.get("date") or "")
    if y:
        out["year"] = y.group(0)
    if (d.get("DOI") or "").strip():
        out["doi"] = d["DOI"].strip()
    return {k: v for k, v in out.items() if v}


def _pos(text: str, name: str) -> int | None:
    m = re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text, flags=re.I)
    return m.start() if m else None


def author_order_check(zm: dict, blocks, pdf_authors: str | None = None, pages: int = 3) -> dict | None:
    """Zotero vs PDF author order (review fix 10). Returns None when consistent or undecidable, else
    {"zotero_first", "pdf_first", "evidence"}. PDF order = order in which the Zotero authors' family names occur in the
    first pages (author line), or the first name in the writer's (unvalidated) author string."""
    full, last = zm.get("authors_full") or [], zm.get("authors_last") or []
    if not full:
        return None
    front = "\n".join(b.text or "" for b in blocks if b.physical_page <= pages and (b.text or "").strip())
    found = sorted((p, i) for i, n in enumerate(last) if n and (p := _pos(front, n)) is not None)
    if len(found) >= 2 and found[0][1] != 0:
        return {"zotero_first": full[0], "pdf_first": full[found[0][1]], "evidence": "PDF 前几页作者行中的出现顺序",
                "verified": True}   # names found verbatim in the PDF text
    if pdf_authors:
        first_pdf = re.split(r"[,，;；、]| and |等", pdf_authors.strip())[0].strip()
        if first_pdf and last[0] and _pos(first_pdf, last[0]) is None and len(first_pdf) <= 60:
            return {"zotero_first": full[0], "pdf_first": first_pdf, "evidence": "主笔从 PDF 读取的作者串（未通过逐字核对）",
                    "verified": False}
    return None
