"""Human-readable Chinese filenames (display only). Identity is library + parent key + PDF SHA, never the filename.

Rules
- colon (ASCII/full-width) -> "——" (Chinese dash); other cross-platform illegal chars <>"/\\|?* -> full-width forms;
  control chars removed; whitespace collapsed; trailing dots/spaces stripped.
- Windows reserved stems (CON, PRN, AUX, NUL, COM1-9, LPT1-9) get a trailing "_".
- length: at most MAX_BYTES UTF-8 bytes for the stem (leaves room for suffix + extension under 255 bytes);
  truncated at a character boundary and reported (truncated=True) - the full title stays in the note body.
- collisions: <标题> -> <标题>——<姓><年份> -> <标题>——<姓><年份><条目Key> -> …（YYYY-MM-DD） -> …（YYYY-MM-DD）（2）…
  (G8-3: only after all three are taken, e.g. a re-read of the same paper); never overwrites.
  <姓> (family_name): the Zotero last name when the caller has it ("Shin" -> "——Shin2026"); else from the full name:
  "Last, First" -> Last; Latin "First [Middle] Last" -> last word (Jr./Sr./II/III skipped). CJK names (Chinese/Japanese/
  Korean script, no Latin letters) keep the FULL name without spaces ("王鸿涛" -> "——王鸿涛2026"): a CJK surname alone
  is far too common to tell papers apart. No author -> "——<年份>"; no year -> "——<姓>".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from ..errors import Stop

MAX_BYTES = 180
_MAP = {"<": "〈", ">": "〉", '"': "“", "/": "／", "\\": "＼", "|": "｜", "?": "？", "*": "＊"}
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class Sanitized:
    stem: str
    truncated: bool


def sanitize(title: str | None, max_bytes: int = MAX_BYTES) -> Sanitized | None:
    if not title:
        return None
    s = unicodedata.normalize("NFC", title)
    s = "".join(ch for ch in s if ch in "\t\n\r" or unicodedata.category(ch)[0] != "C")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[:：]\s*", "——", s)
    s = "".join(_MAP.get(ch, ch) for ch in s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    s = s.lstrip(". ")
    if not s or s.upper() == "UNKNOWN":
        return None
    truncated = False
    if len(s.encode("utf-8")) > max_bytes:
        while len(s.encode("utf-8")) > max_bytes:
            s = s[:-1]
        s, truncated = s.rstrip(". -—"), True
    if s.split(".")[0].upper() in _RESERVED:
        s += "_"
    return Sanitized(s, truncated)


_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f]")
_SUFFIX = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def family_name(full: str | None, family: str | None = None) -> str | None:
    """The author part of the collision suffix (see module doc)."""
    full = (full or "").strip()
    if full and _CJK.search(full) and not _LATIN.search(full):
        return re.sub(r"[\s·・]+", "", full) or None
    if family and family.strip():
        return family.strip()
    if not full:
        return None
    if "," in full or "，" in full:
        return re.split(r"[,，]", full)[0].strip() or None
    words = [w for w in full.split() if w.lower() not in _SUFFIX]
    return words[-1] if words else None


def candidates(title: str | None, first_author: str | None, year: str | None, item_key: str,
               family: str | None = None) -> list[str]:
    base = sanitize(title)
    key = sanitize(item_key).stem if sanitize(item_key) else "UNKNOWN_KEY"
    if base is None:
        return [key]
    fam = sanitize(family_name(first_author, family))
    ay = "".join(x for x in ((fam.stem if fam else ""), year or "") if x)
    out = [base.stem]
    if ay:
        out.append(f"{base.stem}——{ay}")
    out.append(f"{base.stem}——{ay}{key}")
    return out


MAX_EXTRA = 99


def choose_fixed(stem: str, taken: Callable[[str], bool], today: str | None = None) -> str:
    """G10-3: a stem that already carries its own identity (e.g. 〈题名〉——〈KEY〉——证据档案) gets only the date suffix on a
    collision — never the author/key candidates again, so the key appears once. Never overwrites."""
    s = sanitize(stem)
    base0 = s.stem if s else stem
    if not taken(base0):
        return base0
    from datetime import date
    base = f"{base0}（{today or date.today().isoformat()}）"
    for i in range(1, MAX_EXTRA + 1):
        c = base if i == 1 else f"{base}（{i}）"
        if not taken(c):
            return c
    raise Stop(f"同名文件太多：「{base0}」及带日期的 {MAX_EXTRA} 个备用文件名都已存在。"
               "已停止，未覆盖任何文件；请先移走或删除旧的文件再试。")


def choose(title, first_author, year, item_key, taken: Callable[[str], bool], family: str | None = None,
           today: str | None = None) -> str:
    """First candidate stem whose path is free. G8-3: when all three are taken (the same paper read again), last
    resort <最后一个候选>（YYYY-MM-DD）, then （YYYY-MM-DD）（2）（3）… Existing files are never overwritten."""
    cands = candidates(title, first_author, year, item_key, family)
    for c in cands:
        if not taken(c):
            return c
    from datetime import date
    base = f"{cands[-1]}（{today or date.today().isoformat()}）"
    for i in range(1, MAX_EXTRA + 1):
        c = base if i == 1 else f"{base}（{i}）"
        if not taken(c):
            return c
    raise Stop(f"同名文件太多：「{cands[-1]}」及带日期的 {MAX_EXTRA} 个备用文件名都已存在。"
               "已停止，未覆盖任何文件；请先移走或删除旧的笔记再试。")
