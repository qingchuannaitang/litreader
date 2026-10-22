"""Create a user template from the GUI (stage G6): "based on an existing template" (copy its structure, new id and
title, optionally renamed/removed/added sections) or blank. The result is ordinary template Markdown that goes
through the same parse_template / lint rules as a library file, and is stored ONLY in the registry
(source "user", objects/<sha>.md + a new snapshot). The vault 模板库 folder and the built-in templates (incl. the
frozen Yang-based main.general) are never written: a copy gets a new id, so the original stays byte-identical."""
from __future__ import annotations

import re
from datetime import datetime

from ..errors import Stop
from . import sanitize, vocab
from .format import ID_RE, Section, Template, parse_template

ROLE_KEY = {"MAIN_NOTE": "main", "MODULE": "module"}


def _q(v: str) -> str:
    return '"' + str(v).replace("\\", "").replace('"', "'") + '"'


def _lst(xs) -> str:
    return "[" + ", ".join(str(x) for x in xs) + "]"


def _sec(s: Section, module: bool = False) -> str:
    parts = [f"id: {s.id}", f"title: {_q(s.title)}"]
    if s.suffix != "none" and not module:
        parts.append(f"suffix: {s.suffix}")
        if s.suffix_default:
            parts.append(f"suffix_default: {_q(s.suffix_default)}")
    if s.level != 2:
        parts.append(f"level: {s.level}")
    parts.append(f"blocks: {_lst(s.blocks)}")
    return "  - {" + ", ".join(parts) + "}"


def new_id(existing: set[str], role: str) -> str:
    base = f"user.{ROLE_KEY.get(role, 'main')}.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    tid, n = base, 1
    while tid in existing:
        n += 1
        tid = f"{base}-{n}"
    return tid


def plan_sections(base: Template | None, titles: list[str], role: str) -> list[Section]:
    """Map the edited section titles onto the base sections: same title -> that section (keeps its blocks / data
    key); when the list still has exactly the base's length, a changed line renames the section at that position;
    any other new line becomes a free section (paragraphs, filled through the template's extra-section data)."""
    titles = [sanitize.clean_title(t, 40) for t in titles if t and t.strip()]
    titles = [t for t in titles if t]
    pool = list((base.sections if role == "MAIN_NOTE" else base.adds_sections) if base else [])
    used, out, n = set(), [], 0
    by_title = {s.title: s for s in pool}
    for i, t in enumerate(titles):
        s = by_title.get(t) if by_title.get(t) and by_title[t].id not in used else None
        if s is None and len(titles) == len(pool) and pool[i].id not in used and pool[i].title not in titles:
            s = pool[i]
        if s is not None:
            used.add(s.id)
            out.append(Section(s.id, t, list(s.blocks), s.data, s.suffix if t == s.title else "none",
                               s.suffix_default if t == s.title else "", s.level))
        else:
            n += 1
            sid = f"x{n}" if role == "MAIN_NOTE" else f"mod_x{n}"
            while sid in used or any(p.id == sid for p in pool):
                n += 1
                sid = f"x{n}" if role == "MAIN_NOTE" else f"mod_x{n}"
            used.add(sid)
            out.append(Section(sid, t, ["paragraphs"] if role == "MAIN_NOTE" else ["module_fields", "paragraphs"], None))
    return out


def build(*, tid: str, title: str, role: str, study_types: list[str], sections: list[Section],
          base: Template | None = None, description: str = "") -> bytes:
    if not ID_RE.match(tid):
        raise Stop(f"模板 id「{tid}」不合法")
    if role not in ROLE_KEY:
        raise Stop("只能新建主模板或专业模块")
    title = sanitize.clean_title(title, 60)
    if not title:
        raise Stop("请填写模板名称")
    types = [t for t in study_types if t == vocab.ANY or t in vocab.STUDY_TYPES] or [vocab.ANY]
    desc = sanitize.clean(description or (f"在界面中基于「{base.title}」（{base.id}）新建" if base else "在界面中新建（空白）"), 120)
    L = ["---", "litreader_template: 1", f"id: {tid}", f"title: {_q(title)}", f"role: {ROLE_KEY[role]}",
         "version: 1.0.0", "language: zh-CN", f"description: {_q(desc)}", "applies_to:", f"  study_types: {_lst(types)}",
         f"  reading_levels: {_lst((base.reading_levels if base else None) or ['L2'])}",
         f"priority: {base.priority if base else 50}"]
    if role == "MAIN_NOTE":
        L.append(f"header_blocks: {_lst((base.header_blocks if base else None) or vocab.HEADER_BLOCKS)}")
        if not sections:
            raise Stop("主模板至少需要一个章节")
        L.append("sections:")
        L += [_sec(s) for s in sections]
        if base and base.required_blocks:
            L.append(f"required_blocks: {_lst(base.required_blocks)}")
    else:
        L.append(f"compatible_with: {_lst((base.compatible_with if base else None) or ['any_main'])}")
        fields = base.adds_fields if base else []
        if fields:
            L.append("adds_fields:")
            L += ["  - {" + f"name: {f['name']}, label: {_q(f['label'])}, label_rule: {f['label_rule']}, "
                  f"description: {_q(f['description'])}" + "}" for f in fields]
        if sections:
            L.append("adds_sections:")
            L += [_sec(s, module=True) for s in sections]
    L += ["---", f"# {title}（预览）", "", "（在 Litreader 界面中新建；程序只读取上面的 front matter。）", ""]
    hints = {s.title: s.hint for s in ((base.sections + base.adds_sections) if base else []) if s.hint}
    for s in sections:
        L.append(f"## {s.title}")
        if hints.get(s.title):
            L.append(f"> 写作提示：{hints[s.title]}")
    return ("\n".join(L) + "\n").encode("utf-8")


def preview(raw: bytes) -> Template:
    return parse_template(raw, "user:preview")


def section_titles(t: Template) -> list[str]:
    return [s.title for s in (t.sections if t.role == "MAIN_NOTE" else t.adds_sections)]


def safe_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()
