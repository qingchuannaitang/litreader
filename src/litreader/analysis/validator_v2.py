"""Gates for schema v2. Nothing unvalidated reaches the note; every rejection is kept for the evidence archive.

Gates:
  G1 facts/meta PAPER: value+context verbatim in block (raw or LaTeX-normalised), page matches   (validator.check_fact)
  G2 statements: label allowed for the slot, basis_block_ids non-empty and existing, no placeholders
  G3 PAPER statements / PAPER table cells: every number (except small integers 0-10) appears in the cited blocks
     (several blocks may be cited) or is a participant count stated anywhere in the paper ("23 名", "n = 38").
     Table cells are checked one by one: a failing cell is shown as UNKNOWN, the rest of the table stays.
  G4 figures: id must exist in the manifest; finding must be PAPER
  G5 abbreviations: abbr must occur in the source text
  G6 dedupe: one fact per field (first valid wins; later ones archived as DUPLICATE)
  G7 required meta absent/invalid => UNKNOWN
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..parse.blocks import Block
from .chunking import block_id, block_text
from .latex import clean
from .schema_v2 import META_FIELDS
from .validator import _has_placeholder, check_fact, norm
from . import unknown_rank, wording

_NUM = re.compile(r"\d+(?:\.\d+)?")
_DEN = re.compile(r"(\d+)\s*(?:名|人|例|位|只|个个体|个体)|[nN]\s*=\s*(\d+)"
                  r"|(\d+)\s+(?:[A-Za-z-]+\s+){0,3}(?:participants|subjects|patients|individuals|adults|people|persons"
                  r"|volunteers|controls|cases|survivors|children|men|women)\b", re.I)
CELL_UNKNOWN = "UNKNOWN（表格引用的原文段落里没有这个数字，见证据档案）"


def denominators(blocks) -> set[str]:
    """Participant counts stated anywhere in the paper (allowed in any PAPER statement)."""
    out = set()
    for b in blocks:
        for m in _DEN.finditer(clean(block_text(b))):
            out.add((m.group(1) or m.group(2) or m.group(3)).lstrip("0") or "0")
    return out


def refresh_stats(v2) -> dict:
    """Keep counters equal to the actual records (wording/rejections are appended after validation)."""
    v2.stats["wording_changes"] = len(v2.wording)
    v2.stats["rejected"] = len(v2.rejected)
    v2.stats["duplicates"] = len(v2.duplicates)   # G9-1: module-paragraph duplicates are appended by the renderer
    return v2.stats


_BLOCK_ID = re.compile(r"\b[bB]\d+\b")
SOURCE_COLS = re.compile(r"^\s*(?:依据块|来源块|原文块|block(?:[ _-]?ids?)?|basis(?:[ _-]?block(?:[ _-]?ids?)?)?)\s*$", re.I)


def numbers(s: str) -> set[str]:
    out = set()
    for n in _NUM.findall(_BLOCK_ID.sub(" ", clean(s or "")).replace(",", "")):
        if "." not in n and int(n) <= 10:
            continue
        out.add(n.lstrip("0") or "0" if "." not in n else n)
    return out


@dataclass
class V2:
    meta: dict = field(default_factory=dict)
    facts: list = field(default_factory=list)
    data: dict = field(default_factory=dict)          # validated content (statements replaced by None if rejected)
    figures: list = field(default_factory=list)
    abbreviations: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    flagged: list = field(default_factory=list)
    wording: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class _Ctx:
    def __init__(self, blocks):
        self.idx = {block_id(b): b for b in blocks}
        self.all_text = norm(clean("\n".join(block_text(b) for b in blocks)))
        self.den = denominators(blocks)
        self.located: list = []     # G10-6: table cells verified elsewhere in the paper (number + unit)
        self.ok = 0
        self.rej: list = []
        self.flagged: list = []
        self.wording: list = []
        self.paper_nums: set[str] = set()     # numbers of accepted PAPER statements (already checked against basis)

    def title(self, text, where):
        """Headings/titles: no cited blocks -> always gated; rejected wording drops the heading text."""
        if not text:
            return text
        new, rule = wording.gate(text, None)
        if rule:
            self.wording.append({"where": where, "original": text, "result": new, "rule": rule, "gate": wording.GATE})
        return new or ""

    def number_with_unit_in_paper(self, n: str, cell: str) -> bool:
        """G10-6: a table cell number missing from the table's cited blocks is still accepted when the paper states the
        same number with the same unit word right after it (e.g. cell “20 台红外 + 10 台 RGB”, figure caption “由 20 台
        红外相机…记录”). A bare number elsewhere in the paper is NOT enough."""
        c = norm(clean(cell))
        m = re.search(rf"(?<![\d.]){re.escape(n)}([^\d.,+、，;；/()（）%±~-]{{2}})", c)
        if not m:
            return False
        return re.search(rf"(?<![\d.]){re.escape(n)}{re.escape(m.group(1))}", self.all_text) is not None

    def nums_in(self, ids) -> set[str]:
        return numbers("\n".join(block_text(self.idx[i]) for i in ids if i in self.idx)) | self.den

    def stmt(self, s, where, allowed=("PAPER", "INFERENCE")):
        if s is None:
            return None
        if isinstance(s, str) or not isinstance(s, dict):
            return self._rej(where, s, "statement is not an object with label/basis")
        if s.get("label") not in allowed:
            return self._rej(where, s, f"label {s.get('label')!r} not allowed here (allowed {list(allowed)})")
        if not s.get("text") or _has_placeholder(s.get("text")):
            return self._rej(where, s, "empty or placeholder text")
        ids = s.get("basis_block_ids") or []
        if not ids or any(i not in self.idx for i in ids):
            return self._rej(where, s, f"basis_block_ids missing or unknown: {ids}")
        basis_text = "\n".join(block_text(self.idx[i]) for i in ids)
        new, rule = wording.gate(s["text"], basis_text, s.get("label"))
        if new is None:
            self.wording.append({"where": where, "original": s["text"], "result": None, "rule": rule, "gate": wording.GATE})
            return self._rej(where, s, rule)
        if rule:
            self.wording.append({"where": where, "original": s["text"], "result": new, "rule": rule, "gate": wording.GATE})
            s = {**s, "text": new}
        miss = numbers(s["text"]) - self.nums_in(ids)
        if s["label"] == "PAPER" and miss:
            return self._rej(where, s, f"numbers not found in basis blocks: {sorted(miss)}")
        if miss:  # INFERENCE: kept, but every number not in its basis is flagged 未核对 in the note
            s = {**s, "unchecked_numbers": sorted(miss)}
            self.flagged.append({"where": where, "numbers": sorted(miss), "text": s["text"]})
        if s["label"] == "PAPER":
            self.paper_nums |= numbers(s["text"])
        self.ok += 1
        return s

    def table(self, t, where):
        if not isinstance(t, dict) or not t.get("rows") or not t.get("columns"):
            return self._rej(where, t, "malformed table")
        ids = t.get("basis_block_ids") or []
        if not ids or any(i not in self.idx for i in ids):
            return self._rej(where, t, f"table basis_block_ids missing or unknown: {ids}")
        cells = " ".join(" ".join(map(str, r)) for r in t["rows"])
        if _has_placeholder(cells, t.get("title")):
            return self._rej(where, t, "placeholder in table")
        if any(len(r) != len(t["columns"]) for r in t["rows"]):
            return self._rej(where, t, "row/column count mismatch")
        # G8-4: a column that only lists source block ids (依据块/block) is dropped; the note links the table's pages
        drop = [i for i, h in enumerate(t["columns"]) if SOURCE_COLS.match(str(h))]
        if drop and len(drop) < len(t["columns"]):
            t = {**t, "columns": [h for i, h in enumerate(t["columns"]) if i not in drop],
                 "rows": [[x for i, x in enumerate(r) if i not in drop] for r in t["rows"]], "dropped_columns": len(drop)}
        # G7-12: a number already verified in an accepted PAPER statement (e.g. "8 名 MCI" in the paragraph above the
        # sample-size table) is not shown as UNKNOWN in the table just because the table cites other blocks.
        allowed = self.nums_in(ids) | {n for n in self.paper_nums if n in self.all_text}
        head_miss = numbers(" ".join(map(str, t["columns"])) + " " + str(t.get("title") or "")) - allowed
        if head_miss:
            return self._rej(where, t, f"table title/header numbers not found in basis blocks: {sorted(head_miss)}")
        rows, bad, numeric = [], [], 0
        for ri, r in enumerate(t["rows"]):
            row = []
            for ci, cell in enumerate(r):
                n = numbers(str(cell))
                numeric += bool(n)
                miss = {x for x in n - allowed if not self.number_with_unit_in_paper(x, str(cell))}
                if n - allowed - miss:
                    self.located.append({"where": where, "cell": str(cell), "numbers": sorted(n - allowed - miss),
                                         "how": "数字+单位在论文其他段落（如图注）逐字出现"})
                if miss:
                    bad.append({"row": ri, "col": ci, "cell": str(cell), "numbers": sorted(miss)})
                    row.append(CELL_UNKNOWN)
                else:
                    row.append(cell)
            rows.append(row)
        if numeric and len(bad) == numeric:
            return self._rej(where, t, f"no table cell passed the number check: {sorted({x for b in bad for x in b['numbers']})}")
        if bad:
            self.rej.append({"where": f"{where}.cells", "item": {"title": t.get("title"), "cells": bad},
                             "reason": "table cells with numbers not found in basis blocks -> shown as UNKNOWN"})
            t = {**t, "rows": rows, "unknown_cells": len(bad)}
        self.ok += 1
        return t

    def _rej(self, where, item, reason):
        self.rej.append({"where": where, "item": item, "reason": reason})
        return None


def validate_v2(a: dict, blocks: list[Block], manifest: list[dict], template_spec: dict | None = None) -> V2:
    c = _Ctx(blocks)
    out = V2()
    # G1/G7 meta
    meta = a.get("meta") or {}
    for f in META_FIELDS:
        m = meta.get(f) if isinstance(meta.get(f), dict) else {}
        m = {**m, "field": f}
        if m.get("label") == "PAPER":
            r = check_fact({**m, "context": m.get("context") or m.get("value")}, c.idx)
            if r:
                c._rej(f"meta.{f}", m, r)
                m = {"field": f, "value": None, "label": "UNKNOWN"}
        else:
            m = {"field": f, "value": None, "label": "UNKNOWN"}
        out.meta[f] = m
    # G1/G6 facts
    seen = set()
    for f in a.get("facts") or []:
        r = check_fact(f, c.idx)
        if r:
            c._rej("fact", f, r)
        elif f.get("field") in seen:
            out.duplicates.append(f)
        else:
            seen.add(f.get("field")); out.facts.append(f)
    # statements
    d = {}
    tm = a.get("three_minute") or {}
    d["three_minute"] = {
        "what": c.stmt(tm.get("what"), "3min.what"), "how": c.stmt(tm.get("how"), "3min.how"),
        "key_result": c.stmt(tm.get("key_result"), "3min.key_result", ("PAPER",)),
        "value": c.stmt(tm.get("value"), "3min.value", ("INFERENCE",)),
        "caution": c.stmt(tm.get("caution"), "3min.caution")}
    d["one_liner"] = c.stmt(a.get("one_liner"), "one_liner", ("INFERENCE",))
    S = a.get("sections") or {}
    secs = {}
    for k in ("s1", "s2", "s3", "s4", "s5"):
        s = S.get(k) or {}
        secs[k] = {"heading_suffix": c.title(str(s.get("heading_suffix") or s.get("heading") or "").strip(), f"{k}.heading"),
                   "paragraphs": [x for i, p in enumerate(s.get("paragraphs") or []) if (x := c.stmt(p, f"{k}.p{i}"))],
                   "tables": [x for i, t in enumerate(s.get("tables") or []) if (x := c.table(t, f"{k}.t{i}"))],
                   "supports": [x for i, p in enumerate(s.get("supports") or []) if (x := c.stmt(p, f"{k}.sup{i}"))],
                   "cannot_answer": [x for i, p in enumerate(s.get("cannot_answer") or []) if (x := c.stmt(p, f"{k}.no{i}"))],
                   "negative_results": [x for i, p in enumerate(s.get("negative_results") or []) if (x := c.stmt(p, f"{k}.neg{i}", ("PAPER",)))]}
        if _has_placeholder(secs[k]["heading_suffix"]):
            secs[k]["heading_suffix"] = ""
    s6 = S.get("s6") or {}
    secs["s6"] = {"author_conclusion": c.stmt(s6.get("author_conclusion"), "s6.conclusion", ("PAPER",)),
                  "evaluation": c.stmt(s6.get("evaluation"), "s6.evaluation", ("INFERENCE",))}
    secs["s7"] = {"items": [x for i, p in enumerate((S.get("s7") or {}).get("items") or []) if (x := c.stmt(p, f"s7.{i}"))]}
    s8 = S.get("s8") or {}
    items = []
    for i, it in enumerate(s8.get("items") or []):
        if not isinstance(it, dict):
            continue
        items.append({"title": c.title(str(it.get("title") or "").strip(), f"s8.{i}.title"), "basis": c.stmt(it.get("basis"), f"s8.{i}.basis", ("PAPER",)),
                      "help": c.stmt(it.get("help"), f"s8.{i}.help", ("INFERENCE",)), "limit": c.stmt(it.get("limit"), f"s8.{i}.limit")})
    secs["s8"] = {"items": items, "review_summary": c.stmt(s8.get("review_summary"), "s8.review", ("INFERENCE",))}
    secs["s9"] = {"next_checks": [str(x) for x in (S.get("s9") or {}).get("next_checks") or [] if x and not _has_placeholder(str(x))]}
    d["sections"] = secs
    if template_spec:   # template-requested content: same gates as every other statement; undeclared keys dropped
        ex = a.get("extra_sections") if isinstance(a.get("extra_sections"), dict) else {}
        d["extra_sections"] = {sid: {"paragraphs": [x for i, p in enumerate((ex.get(sid) or {}).get("paragraphs") or [])
                                                    if (x := c.stmt(p, f"extra.{sid}.p{i}"))]}
                               for sid in template_spec.get("extra_sections") or []}
        for sid in ex:
            if sid not in d["extra_sections"]:
                c._rej(f"extra.{sid}", ex[sid], "section not declared by the selected template")
        mf = a.get("module_fields") if isinstance(a.get("module_fields"), dict) else {}
        rules = template_spec.get("module_fields") or {}
        d["module_fields"] = {}
        for name, s in mf.items():
            if name not in rules:
                c._rej(f"module.{name}", s, "field not declared by the selected modules")
                continue
            allowed = ("PAPER", "INFERENCE") if rules[name] == "ANY" else (rules[name],)
            x = c.stmt(s, f"module.{name}", allowed)
            if x:
                d["module_fields"][name] = x
    topic = a.get("topic") if isinstance(a.get("topic"), str) and not _has_placeholder(a.get("topic")) else None
    tags = [t for t in a.get("tags") or [] if isinstance(t, str) and t.strip() and not _has_placeholder(t)]
    d["_aux"] = {"topic": topic, "tags": tags}
    out.data = d
    # G4 figures
    ids = {m["id"]: m for m in manifest}
    used = set()
    for i, fg in enumerate(a.get("figures") or []):
        if not isinstance(fg, dict) or fg.get("id") not in ids or fg.get("id") in used:
            c._rej(f"figure.{i}", fg, "figure id not in manifest or duplicated"); continue
        sec = fg.get("section") if fg.get("section") in ("s2", "s3", "s4", "s5") else "s4"
        used.add(fg["id"])
        out.figures.append({"id": fg["id"], "section": sec, "title": c.title(str(fg.get("title") or "").strip(), f"figure.{fg['id']}.title"),
                            "finding": c.stmt(fg.get("finding"), f"figure.{fg['id']}.finding", ("PAPER",)),
                            "interpretation": c.stmt(fg.get("interpretation"), f"figure.{fg['id']}.interp", ("INFERENCE",)),
                            "limitation": c.stmt(fg.get("limitation"), f"figure.{fg['id']}.limit")})
    for m in manifest:  # every real figure is shown even if the model skipped it
        if m["id"] not in used:
            out.figures.append({"id": m["id"], "section": "s4", "title": "", "finding": None, "interpretation": None,
                                "limitation": None, "auto": True})
    # G5 abbreviations
    for ab in a.get("abbreviations") or []:
        if isinstance(ab, dict) and ab.get("abbr") and ab.get("zh") and norm(ab["abbr"]) in c.all_text:
            out.abbreviations.append({"abbr": ab["abbr"].strip(), "zh": ab["zh"].strip()})
        else:
            c._rej("abbreviation", ab, "abbr not found in source or malformed")
    out.unknowns = [u for u in a.get("unknowns") or [] if isinstance(u, dict) and u.get("item")]
    out.unknowns += [{"item": f"元数据 {k}", "why": "原文未找到或未通过逐字核对"} for k, m in out.meta.items() if m["label"] == "UNKNOWN"]
    out.rejected = c.rej
    out.located_cells = c.located
    out.flagged = c.flagged
    out.wording = c.wording
    out.unknowns = unknown_rank.rank(out.unknowns)
    out.stats = {"statements_and_tables_ok": c.ok, "facts_ok": len(out.facts), "duplicates": len(out.duplicates),
                 "rejected": len(c.rej), "inference_numbers_flagged": len(c.flagged), "wording_changes": len(c.wording), "meta_unknown": sum(m["label"] == "UNKNOWN" for m in out.meta.values()),
                 "figures": len(out.figures), "figures_without_model_text": sum(1 for f in out.figures if f.get("auto"))}
    refresh_stats(out)
    return out
