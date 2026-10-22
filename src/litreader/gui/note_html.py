"""Note preview for the 结果页 (stage G6): the note Markdown (Obsidian flavour, as written by render/l2_note_v2) →
HTML for a QTextBrowser. Qt-free so it is unit-testable; no QtWebEngine (keeps the app small).

Rendered like the prototype: Obsidian callouts as coloured cards (论文信息 blue, 三分钟了解论文 teal, 阅读约定 purple,
warnings amber), PAPER / INFERENCE / UNKNOWN as coloured chips, zotero:// page links as small accent links (clicking
opens Zotero), figures from the trial folder inline. QTextDocument has no per-side borders or rounded corners, so a
callout is a two-cell table: a 4 px coloured strip + a tinted body."""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Callable

FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
CALLOUT = {  # type -> (strip colour token, background token, glyph)
    "info": ("accent", "accent_soft", "ℹ"), "abstract": ("teal", "teal_soft", "▤"), "summary": ("teal", "teal_soft", "▤"),
    "note": ("info", "info_soft", "✎"), "warning": ("warn", "warn_soft", "⚠"), "caution": ("warn", "warn_soft", "⚠"),
    "tip": ("ok", "ok_soft", "✓"), "success": ("ok", "ok_soft", "✓"), "question": ("info", "info_soft", "?"),
    "danger": ("stop", "stop_soft", "!"), "failure": ("stop", "stop_soft", "!"), "quote": ("muted", "hover", "❝"),
}
TAG = {"PAPER": ("ok", "ok_soft"), "INFERENCE": ("info", "info_soft"), "UNKNOWN": ("warn", "warn_soft")}


def colours(pal: dict, dark: bool) -> dict:
    return dict(pal)


def _chip(word: str, c: dict) -> str:
    fg, bg = TAG[word]
    return (f'<span style="background-color:{c[bg]}; color:{c[fg]}; font-size:10px; font-weight:700;">'
            f'&nbsp;{word}&nbsp;</span>')


def inline(s: str, c: dict, image: Callable[[str], str | None] | None = None) -> str:
    """One line of Markdown → HTML (escape first, then links / emphasis / tags)."""
    s = re.sub(r"%%.*?%%", "", s)
    s = re.sub(r"\s\^[\w-]+$", "", s)
    links: list[str] = []

    def keep(h: str) -> str:
        links.append(h)
        return f"\x00{len(links) - 1}\x00"

    def img(m):
        name = m.group(1)
        src = image(name) if image else None
        if src:
            return keep(f'<br><img src="{html.escape(src)}" width="{_w(src)}"><br>')
        return keep(f'<span style="color:{c["muted"]};">〔图：{html.escape(Path(name).name)}〕</span>')
    s = re.sub(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", img, s)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", lambda m: keep(html.escape(m.group(2))), s)
    s = re.sub(r"\[\[([^\]]+)\]\]", lambda m: keep(html.escape(Path(m.group(1)).name.lstrip("#^"))), s)

    def link(m):
        text, url = m.group(1), m.group(2)
        if url.startswith(("zotero://", "http://", "https://")):
            small = url.startswith("zotero://")
            return keep(f'<a href="{html.escape(url)}" style="color:{c["accent"]}; text-decoration:none;'
                        f'{" font-size:12px;" if small else ""}">{html.escape(text)}{" ↗" if small else ""}</a>')
        return keep(html.escape(text))
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", lambda m: f'<span style="font-family:monospace; color:{c["muted"]};">{m.group(1)}</span>', s)
    s = re.sub(r"\*\*(PAPER|INFERENCE|UNKNOWN)\*\*", lambda m: _chip(m.group(1), c), s)
    s = re.sub(r"（(PAPER|INFERENCE|UNKNOWN)）", lambda m: " " + _chip(m.group(1), c), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"(?<![A-Za-z_>;])(PAPER|INFERENCE|UNKNOWN)(?![A-Za-z_])", lambda m: _chip(m.group(1), c), s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)
    return s.rstrip("  ").strip()


_WIDTHS: dict[str, int] = {}


def _w(src: str) -> int:
    return _WIDTHS.get(src, 520)


def _callout(kind: str, title: str, body: list[str], c: dict, image) -> str:
    strip, bg, glyph = CALLOUT.get(kind.lower(), CALLOUT["note"])
    inner = "<br>".join(inline(x, c, image) for x in body if x.strip())
    head = f'<b>{glyph} {inline(title, c, image)}</b>' if title.strip() else ""
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px; margin-bottom:8px;">'
            f'<tr><td width="4" bgcolor="{c[strip]}"></td>'
            f'<td bgcolor="{c[bg]}" style="padding:10px 14px;">{head}{"<br>" if head and inner else ""}{inner}</td></tr></table>')


def _table(rows: list[list[str]], c: dict, image) -> str:
    out = ['<table width="100%" cellspacing="0" cellpadding="6" style="margin-top:6px; margin-bottom:10px;">']
    for i, r in enumerate(rows):
        tag = "th" if i == 0 else "td"
        bg = f' bgcolor="{c["hover"]}"' if i == 0 else ""
        out.append("<tr>" + "".join(f'<{tag}{bg} align="left" style="border-bottom:1px solid {c["line"]};">'
                                    f'{inline(x, c, image)}</{tag}>' for x in r) + "</tr>")
    return "".join(out) + "</table>"


def render(md: str, pal: dict, *, dark: bool = False, image: Callable[[str], str | None] | None = None,
           max_chars: int = 80000, widths: dict[str, int] | None = None) -> str:
    c = colours(pal, dark)
    _WIDTHS.clear()
    _WIDTHS.update(widths or {})
    s = FM_RE.sub("", md, count=1)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"%%.*?%%", "", s, flags=re.S)
    cut = len(s) > max_chars
    s = s[:max_chars]
    lines = s.split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush():
        if para:
            out.append(f'<p style="margin-top:4px; margin-bottom:8px;">{"<br>".join(inline(x, c, image) for x in para)}</p>')
            para.clear()
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        m = re.match(r"^>\s*\[!(\w+)\][+-]?\s*(.*)$", ln)
        if m:
            flush()
            body = []
            i += 1
            while i < len(lines) and lines[i].startswith(">"):
                body.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append(_callout(m.group(1), m.group(2), body, c, image))
            continue
        if st.startswith(">"):
            flush()
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(_callout("quote", "", body, c, image))
            continue
        h = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if h:
            flush()
            n = len(h.group(1))
            size = {1: 22, 2: 17, 3: 15, 4: 14}[n]
            out.append(f'<p style="margin-top:{18 if n <= 2 else 12}px; margin-bottom:6px; font-size:{size}px; '
                       f'font-weight:700;">{inline(h.group(2), c, image)}</p>')
            i += 1
            continue
        if re.match(r"^\s*\|.*\|\s*$", ln):
            flush()
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", x) for x in cells if x):
                    rows.append(cells)
                i += 1
            out.append(_table(rows, c, image))
            continue
        li = re.match(r"^\s*(?:[-*]|(\d+)[.)])\s+(.*)$", ln)
        if li:
            flush()
            ordered = li.group(1) is not None
            items = []
            while i < len(lines):
                mm = re.match(r"^\s*(?:[-*]|(\d+)[.)])\s+(.*)$", lines[i])
                if not mm:
                    break
                items.append(inline(mm.group(2), c, image))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f'<{tag} style="margin-top:2px; margin-bottom:8px;">' + "".join(f"<li>{x}</li>" for x in items)
                       + f"</{tag}>")
            continue
        if re.fullmatch(r"\^[\w-]+", st) or re.fullmatch(r"-{3,}|\*{3,}", st):
            flush()
            i += 1
            continue
        if not st:
            flush()
            i += 1
            continue
        para.append(ln)
        i += 1
    flush()
    if cut:
        out.append(f'<p style="color:{c["muted"]};">……（预览到此为止，完整内容请在 Obsidian 中查看）</p>')
    return f'<div style="color:{c["text"]}; font-size:14px;">' + "\n".join(out) + "</div>"


def tag_counts(md: str) -> dict[str, int]:
    body = FM_RE.sub("", md, count=1)
    return {k: len(re.findall(rf"(?<![A-Za-z_]){k}(?![A-Za-z_])", body)) for k in TAG}


# ---------- links for the 结果页 top buttons (Qt-free, tested) ----------
def vault_root_of(note: str | Path, cfg=None) -> Path | None:
    """Vault root: cfg.vault_root when the note is inside it; else the nearest parent with .obsidian/, else the parent of the litreader / _litreader_* folder."""
    p = Path(note)
    if cfg is not None:
        try:
            p.relative_to(cfg.vault_root)
            return Path(cfg.vault_root)
        except ValueError:
            pass
    for a in p.parents:
        if (a / ".obsidian").is_dir():
            return a
    for a in p.parents:
        if a.name.startswith("_litreader_") or a.name == "litreader":
            return a.parent
    return None


def obsidian_uri(note: str | Path, cfg=None) -> str:
    """obsidian://open?vault=<name>&file=<path in vault, no .md> (falls back to ?path=<absolute path>)."""
    from urllib.parse import quote
    p = Path(note)
    root = vault_root_of(p, cfg)
    if root is not None:
        rel = p.relative_to(root).as_posix()
        rel = rel[:-3] if rel.endswith(".md") else rel
        return f"obsidian://open?vault={quote(root.name, safe='')}&file={quote(rel, safe='')}"
    return f"obsidian://open?path={quote(str(p), safe='')}"


def item_key_of(r: dict) -> str | None:
    p = r.get("paper") or {}
    k = p.get("item_key") or (r.get("identity") or {}).get("parent_key") or (r.get("row") or {}).get("item_key")
    return k if k and k != "UNKNOWN" else None


def zotero_uri(key: str) -> str:
    return f"zotero://select/library/items/{key}"


def image_resolver(note: str | Path, cfg=None):
    """![[vault/relative/path.png]] → file:// URL of an existing file (else None → placeholder)."""
    root = vault_root_of(note, cfg)

    def find(name: str) -> str | None:
        cands = []
        if root is not None:
            cands.append(root / name)
        cands.append(Path(note).parent / name)
        for c in cands:
            if c.is_file():
                return c.resolve().as_uri()
        return None
    return find


def preview_head(md: str) -> str:
    """G7 结果页 drawer: only the title + the first two callouts (论文信息, 三分钟了解论文). Falls back to the
    first ~40 body lines when the note has no callouts."""
    body = FM_RE.sub("", md, count=1)
    lines = body.split("\n")
    out, callouts, i = [], 0, 0
    while i < len(lines) and callouts < 2:
        ln = lines[i]
        if re.match(r"^>\s*\[!\w+\]", ln):
            while i < len(lines) and lines[i].startswith(">"):
                out.append(lines[i])
                i += 1
            out.append("")
            callouts += 1
            continue
        if ln.startswith("# ") or (not out and ln.startswith("*")):
            out.append(ln)
        i += 1
    if callouts == 0:
        return "\n".join(lines[:40])
    return "\n".join(out).strip() + "\n"
