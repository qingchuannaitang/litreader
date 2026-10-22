"""Template selection (spec §5.4; design §5.3). Eligibility -> five priority tiers -> modules -> freeze.

Tiers (spec §5.4 第二关):
  0 template the user named for this run
  1 user's first choice for this study type (`templates prefer <id> --for <type>`, spec §8)
  2 specialised main template whose applies_to names this study type
  3 main template the user associated with the frozen project (`templates prefer <id> --project <课题>`)
  4 user default main template (`templates prefer <id>`)
  5 general (applies_to any): the V2.0 general template is the fallback
Two different specialised templates tied at the top -> ambiguous -> the user must choose (never random).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import builtin, vocab
from .vocab import STUDY_TYPES

MAX_MODULES = 3
TIER_ZH = {0: "你本次指定", 1: "你为该论文类型设定的首选", 2: "与本篇研究设计匹配的专用主模板", 3: "与当前课题兼容的专用模板",
           4: "你的默认主模板", 5: "通用主模板"}


@dataclass
class Choice:
    main: dict
    modules: list[dict]
    tier: int
    reason: str
    ambiguous: bool
    candidates: list[tuple[dict, int | None, str]] = field(default_factory=list)   # (record, tier or None, note)
    skipped_modules: list[str] = field(default_factory=list)


def _effective_records(reg, snap) -> dict[str, dict]:
    out = {}
    for tid in {r["id"] for r in snap["records"]}:
        r = reg.effective(snap, tid)
        if r and r["status"] not in ("REJECTED", "NEEDS_REVIEW", "CONFLICT"):
            out[tid] = r
    return out


def _fits(r, study_type, secondary, level="L2") -> bool:
    st = r["applies_to"]["study_types"]
    lv = r["applies_to"].get("reading_levels") or ["L2"]
    return level in lv and (vocab.ANY in st or study_type in st)


def mains(reg, snap) -> list[dict]:
    """Every main template the user may pick manually (ACTIVE or pinned; never overview/evidence/review)."""
    eff = _effective_records(reg, snap)
    return sorted([r for r in eff.values() if r["role"] == "MAIN_NOTE" and r["status"] in ("ACTIVE", "SUPERSEDED", "REMOVED")
                   and (r["status"] == "ACTIVE" or r["id"] in snap["prefs"]["pins"])],
                  key=lambda r: (-r["priority"], r["id"]))


def choose(reg, snap, study: dict, *, requested: str | None = None, level: str = "L2",
           project_id: str | None = None) -> Choice:
    st, sec = study["study_type"], study.get("secondary") or []
    prefs = snap["prefs"]
    proj_pref = (prefs.get("prefer_for_project") or {}).get(project_id) if project_id else None
    pool = mains(reg, snap)
    cands = []
    for r in pool:
        fits = _fits(r, st, sec, level)
        tier = None
        if requested and requested in (r["id"], r["title"]):
            tier = 0
        elif fits and prefs["prefer_for"].get(st) == r["id"]:
            tier = 1
        elif fits and vocab.ANY not in r["applies_to"]["study_types"]:
            tier = 2
        elif fits and proj_pref == r["id"]:
            tier = 3
        elif fits and prefs.get("default_main") == r["id"]:
            tier = 4
        elif fits:
            tier = 5
        note = "" if tier is not None else ("论文类型不符" if not fits else "")
        cands.append((r, tier, note))
    ranked = sorted([c for c in cands if c[1] is not None], key=lambda c: (c[1], -c[0]["priority"], c[0]["id"]))
    if not ranked:   # nothing eligible: built-in fallback (always registered and ACTIVE)
        fb = reg.effective(snap, builtin.FALLBACK)
        ranked = [(fb, 5, "回退")]
    top = ranked[0]
    ambiguous = bool(study.get("ambiguous"))
    if len(ranked) > 1 and top[1] == 2 and ranked[1][1] == 2 and ranked[1][0]["priority"] == top[0]["priority"]:
        ambiguous = True
    if requested and top[1] != 0:
        ambiguous = True
    main = top[0]
    reason = TIER_ZH[top[1]]
    if top[1] == 5:
        reason += f"（没有适用于{STUDY_TYPES.get(st, st)}的专用主模板）" if st != "other" else "（论文类型未能确定）"
    mods, skipped = pick_modules(reg, snap, main, st, sec)
    others = [c for c in cands if c[0] is not main]
    return Choice(main, mods, top[1], reason, ambiguous, [top] + others, skipped)


def pick_modules(reg, snap, main: dict, st: str, sec: list[str]) -> tuple[list[dict], list[str]]:
    eff = _effective_records(reg, snap)
    want = {st}   # automatic modules follow the PRIMARY type only; secondary-type modules are offered, not added
    out, skipped, ids, fields = [], [], set(), set()
    for r in sorted(eff.values(), key=lambda r: (-r["priority"], r["id"])):
        if r["role"] != "MODULE" or r["status"] != "ACTIVE":
            continue
        if not (want & set(r["applies_to"]["study_types"]) or vocab.ANY in r["applies_to"]["study_types"]):
            if set(sec) & set(r["applies_to"]["study_types"]):
                skipped.append(f"{r['title']}（适用于次要类型，可按 m 手动添加）")
            continue
        cw = r.get("compatible_with") or []
        if "any_main" not in cw and main["id"] not in cw:
            skipped.append(f"{r['title']}（与主模板不兼容）")
            continue
        if len(out) >= MAX_MODULES:
            skipped.append(f"{r['title']}（模块已达 {MAX_MODULES} 个上限）")
            continue
        f = set(r.get("required_fields") or [])
        if f & fields:
            skipped.append(f"{r['title']}（字段与已选模块重复）")
            continue
        fields |= f
        out.append(r)
    return out, skipped


def label(r: dict) -> str:
    src = {"builtin": "内置", "library": "模板库", "ai_draft": "AI 草稿", "user": "界面新建"}.get(r["source"], r["source"])
    return f"{r['title']}（{src} v{r['registry_version']}）"
