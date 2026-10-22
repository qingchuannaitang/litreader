"""Validator: ties every PAPER fact to its source block (value + context verbatim, page match).

Failures are moved to `rejected` with a reason; required fields without a valid fact become UNKNOWN.
INFERENCE claims must cite >=1 existing block. Placeholders anywhere => rejected.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..parse.blocks import Block
from .chunking import block_id, block_text
from .latex import clean
from .schema import LABELS, REQUIRED_FIELDS

_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\bTODO\b|\bTBD\b|<(?:填写|待定|待补充|placeholder|value|insert)[^<>]*>|示例|占位|xxx", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\\(?=[~*_#\[\]()`|<>-])", "", s)   # markdown escapes are not content
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "", s).casefold()


def qnorm(s: str) -> str:
    """Matching form for quotes: LaTeX cleaned + garbled characters normalised, applied to BOTH sides.
    MinerU renders italic p as U+FFFD, uses '~' as a LaTeX space, and puts citations in <sup>[47]</sup>;
    'VS.'/'vs'/'vs.' are the same token. Only used for matching; displayed/archived text is unchanged."""
    t = clean(s or "").replace("\ufffd", "p").replace("~", " ")
    t = re.sub(r"\^\s*(\[[^\]]*\])", r"\1", t)
    t = norm(t)
    t = re.sub(r"vs\.?", "vs", t)
    return t.replace("，", ",").replace("：", ":")


_ELLIPSIS = re.compile(r"…+|⋯+|\.{3,}|。{3,}")
MAX_ELLIPSIS_GAP = 300


def quote_in(quote: str | None, source: str | None) -> bool:
    """Is `quote` verbatim in `source` (raw, or after the same normalisation of both sides)?
    A quote shortened with an ellipsis (“A……B”) passes only if every piece is verbatim, in order, in the same source,
    with at most MAX_ELLIPSIS_GAP normalised characters skipped between pieces and ≥10 quoted characters in total."""
    if not quote or not source:
        return False
    if norm(quote) in norm(source) or qnorm(quote) in qnorm(source):
        return True
    parts = [p for p in (qnorm(x) for x in _ELLIPSIS.split(quote)) if p]
    if len(parts) < 2 or sum(map(len, parts)) < 10:
        return False
    src, pos, prev = qnorm(source), 0, None
    for p in parts:
        i = src.find(p, pos)
        if i < 0 or (prev is not None and i - prev > MAX_ELLIPSIS_GAP):
            return False
        pos = prev = i + len(p)
    return True


@dataclass
class ValidationReport:
    facts: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    enforced_unknown: list[str] = field(default_factory=list)
    title_zh: dict | None = None
    title_en: dict | None = None

    @property
    def counts(self) -> dict:
        return {"facts_paper_ok": sum(f["label"] == "PAPER" for f in self.facts),
                "facts_unknown": sum(f["label"] == "UNKNOWN" for f in self.facts),
                "claims_ok": len(self.claims), "rejected": len(self.rejected),
                "enforced_unknown": len(self.enforced_unknown)}


def _has_placeholder(*vals) -> bool:
    return any(isinstance(v, str) and _PLACEHOLDER.search(v) for v in vals)


def check_fact(f: dict, idx: dict[str, Block]) -> str | None:
    """Return a rejection reason, or None if OK."""
    lab = f.get("label")
    if lab not in LABELS or lab == "INFERENCE":
        return f"fact label must be PAPER or UNKNOWN, got {lab!r}"
    if _has_placeholder(f.get("value"), f.get("context")):
        return "placeholder text"
    if lab == "UNKNOWN":
        if f.get("value") not in (None, "", "UNKNOWN"):
            return "UNKNOWN fact carries a value"
        return None
    v, ctx, bid, pg = f.get("value"), f.get("context"), f.get("block_id"), f.get("physical_page")
    if not v or not ctx:
        return "PAPER fact missing value or context"
    b = idx.get(bid)
    if b is None:
        return f"block_id {bid!r} not found"
    if pg != b.physical_page:
        return f"page {pg} != block page {b.physical_page}"
    raw_ok = norm(ctx) in norm(block_text(b)) and norm(v) in norm(ctx)
    if raw_ok:
        return None
    # LaTeX-normalised comparison (display cleanup must not change what counts as verbatim)
    if not quote_in(ctx, block_text(b)):
        return "context not verbatim in block"
    if not quote_in(v, ctx):
        return "value not inside context"
    return None


def validate(analysis: dict, blocks: list[Block]) -> ValidationReport:
    idx = {block_id(b): b for b in blocks}
    rep = ValidationReport()
    for key in ("title_zh", "title_en"):
        t = analysis.get(key) or {}
        if t.get("label") == "PAPER":
            reason = check_fact({**t, "context": t.get("value")}, idx)
            if reason:
                rep.rejected.append({"where": key, "item": t, "reason": reason})
                t = {"value": None, "label": "UNKNOWN"}
        else:
            t = {"value": None, "label": "UNKNOWN"}
        setattr(rep, key, t)
    for f in analysis.get("facts") or []:
        reason = check_fact(f, idx)
        (rep.rejected.append({"where": "fact", "item": f, "reason": reason}) if reason else rep.facts.append(f))
    for c in analysis.get("claims") or []:
        reason = None
        if c.get("label") not in ("PAPER", "INFERENCE"):
            reason = f"claim label {c.get('label')!r}"
        elif not c.get("text") or _has_placeholder(c.get("text")):
            reason = "empty or placeholder claim"
        elif not c.get("basis_block_ids") or any(b not in idx for b in c["basis_block_ids"]):
            reason = "claim basis_block_ids missing or unknown"
        (rep.rejected.append({"where": "claim", "item": c, "reason": reason}) if reason else rep.claims.append(c))
    covered = {f.get("field") for f in rep.facts if f["label"] == "PAPER"}
    for fld in REQUIRED_FIELDS:
        if fld not in covered and not any(f.get("field") == fld for f in rep.facts):
            rep.facts.append({"field": fld, "value": None, "context": None, "block_id": None,
                              "physical_page": None, "label": "UNKNOWN"})
            rep.enforced_unknown.append(fld)
    return rep
