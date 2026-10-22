"""Comparative-claim judge: a comparative/superlative must be backed by a test that compares THOSE two things.

Detection (deterministic): comparative lexicon, excluding already-neutral phrases (数值最高/数值更高/数值高于).
One batched DeepSeek call (JSON mode). Per item verdict:
  TESTED                    - quote (verbatim in a basis block) contains a test statistic comparing the two things
  AUTHOR_STATEMENT_UNTESTED - PAPER item whose comparative is the authors' own wording (verbatim quote contains it);
                              kept, annotated（作者表述，无对应检验）
  UNSUPPORTED               - otherwise
Gates: bad/non-verbatim quote, or TESTED quote without a test statistic -> UNSUPPORTED.
UNSUPPORTED -> deterministic rewrite (wording.REWRITE) if possible, else rejected (removed). All logged.
Judge failure -> every candidate treated as UNSUPPORTED (fail-closed).
"""
from __future__ import annotations

import json
import re

from ..llm.jsonparse import loads_lenient
from ..llm.client import AllProvidersFailed, run_chain
from .chunking import block_id, block_text
from .latex import clean
from .validator import quote_in
from .validator_v2 import numbers, refresh_stats
from .validator import qnorm
from .wording import ANNOT_INFER, ANNOT_PAPER, IDIOM, has_stat, has_test, rewrite

COMPARATIVE = re.compile(r"最(?:好|佳|优|差|强|弱|明显|高|低|大|小|敏感)|更[\u4e00-\u9fff]{1,2}|优于|劣于|胜过|高于|低于|强于|弱于")
# Neutral phrases + research-recommendation phrasing (not a comparison between study groups/methods)
NEUTRAL = re.compile(r"数值最高|数值更高|数值高于|数值最低|数值更低|数值低于"
                     r"|更大(?:规模)?(?:的)?样本|更多(?:的)?(?:研究|样本|数据)|更长(?:期)?(?:的)?随访|更(?:深入|进一步)"
                     r"|更严重(?:的)?[\u4e00-\u9fff]{0,6}?(?:人群|患者|病例|障碍)")   # limitation phrasing, not a comparison

PROMPT = """你是统计措辞审查员。每条陈述含比较/最高级措辞。判断该比较是否被依据块中“确实比较这两者”的统计检验支持。
- TESTED：依据块中有直接比较这两个对象的检验结果（p 值/F/t/置信区间等），给出含该检验统计量的逐字 quote；
- AUTHOR_STATEMENT_UNTESTED：陈述是作者原文的比较性表述（逐字 quote 中含该比较），但没有对应检验；
- UNSUPPORTED：以上都不是（例如检验比较的是别的对象，或比较由整理者推断）。
只返回 JSON：{"items":[{"id": str, "verdict": "...", "block_id": str|null, "quote": str|null, "reason": 中文≤50字}]}"""


def _collect(data, cross):
    """Yield (ref, stmt_like) where ref lets us replace/remove. stmt_like has text/label/basis or is a vision claim."""
    out = []

    def walk(o, parent, key):
        if isinstance(o, dict):
            if "text" in o and "basis_block_ids" in o and "label" in o:
                out.append(("stmt", parent, key, o))
                return
            for k, v in o.items():
                walk(v, o, k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, o, i)
    walk(data, None, None)
    for fid, claims in (cross or {}).items():
        for i, c in enumerate(claims):
            if c.get("verdict") == "CONSISTENT":
                out.append(("vision", claims, i, c))
    return out


def candidates(data, cross):
    cands = []
    for kind, parent, key, o in _collect(data, cross):
        text = o["text"] if kind == "stmt" else o["claim"]
        stripped = IDIOM.sub("", NEUTRAL.sub("", text or ""))   # “最佳平衡” compares nothing
        if ANNOT_PAPER in (text or "") or ANNOT_INFER in (text or ""):
            continue   # already annotated by the deterministic gate
        if COMPARATIVE.search(stripped):
            ids = o["basis_block_ids"] if kind == "stmt" else [o["block_id"]]
            cands.append({"id": f"c{len(cands)}", "kind": kind, "parent": parent, "key": key, "obj": o, "text": text,
                          "ids": [i for i in ids if i], "label": o.get("label", "PAPER")})
    return cands


def _rewrite(text: str, basis: str = "") -> tuple[str | None, str | None]:
    """Neutral rewrite; never for lower-is-better metrics (wording.rewrite refuses those)."""
    new, refused = rewrite(text, basis)
    if new is None:
        return None, refused
    return (new, None) if new != text and not COMPARATIVE.search(IDIOM.sub("", NEUTRAL.sub("", new))) else (None, None)


def verbatim_comparative(text: str, basis: str) -> bool:
    """Every comparative in the claim occurs, with the 3 characters that follow it, verbatim in the cited text —
    i.e. the paper's own wording (“红色表示最小双相机配置”), not a comparison the model made up."""
    src = qnorm(basis or "")
    ms = list(COMPARATIVE.finditer(NEUTRAL.sub(lambda m: " " * len(m.group(0)), text or "")))
    return bool(ms and src) and all(qnorm(text[m.start():m.end() + 3]) in src for m in ms)


def paired_test_in_basis(text: str, ids, idx) -> str | None:
    """Deterministic support: the statement itself carries a test statistic, and ALL its numbers (paired values + p)
    occur together in ONE cited block that also carries the statistic. Returns that block id."""
    if not has_stat(text):
        return None
    nums = numbers(text)
    if not nums:
        return None
    for i in ids:
        b = idx.get(i)
        if b is not None and has_stat(block_text(b)) and nums <= numbers(block_text(b)):
            return i
    return None


# G7-12 overclaim phrases (deterministic, before the judge): strong evidential wording is hedged.
OVERCLAIM = [(re.compile(r"直接证据"), "初步证据"), (re.compile(r"充分证明|证明了|确证了?"), "提示"),
             (re.compile(r"泛化优势"), "可能的泛化潜力"), (re.compile(r"(?:均|全面|一致)优于"), "多数比较中数值优于")]
_NONSIG = re.compile(r"不显著|无显著|未达(?:到)?显著|\bns\b|n\.s\.|[pP]\s*[=＝>]\s*0?\.(?:0[5-9]|[1-9])", re.I)
_GENERAL = re.compile(r"泛化|普遍|推广|适用于所有|各类人群")
SINGLE = "（基于单项研究）"
NONSIG = "（部分比较未达显著）"


def hedge_overclaims(v2, blocks, cross=None) -> int:
    """Rewrite 直接证据 / 泛化优势 / 均优于 … in statements and vision claims unless the paper uses the very phrase in the
    cited text; append a hedge when the cited text has non-significant results or when a generalisation rests on this
    single study. Every change is logged in v2.wording. Returns the number of changes."""
    idx = {block_id(b): b for b in blocks}
    n = 0
    for kind, parent, key, o in _collect(v2.data, cross):
        field = "text" if kind == "stmt" else "claim"
        text = o.get(field) or ""
        ids = o.get("basis_block_ids") if kind == "stmt" else [o.get("block_id")]
        basis = clean("\n".join(block_text(idx[i]) for i in (ids or []) if i in idx))
        new = text
        for rx, rep in OVERCLAIM:
            new = rx.sub(lambda m: m.group(0) if (o.get("label") == "PAPER" and m.group(0) in basis) else rep, new)
        if new != text:
            if _NONSIG.search(basis) and NONSIG not in new:
                new += NONSIG
            if _GENERAL.search(new) and SINGLE not in new and o.get("label", "PAPER") == "INFERENCE":
                new += SINGLE
        if new != text:
            o[field] = new
            v2.wording.append({"where": f"wording_judge.overclaim.{kind}", "original": text, "result": new,
                               "rule": "overclaim phrase hedged (直接证据/泛化优势/均优于…)", "gate": "wording_judge.overclaim"})
            n += 1
    return n


def apply(v2, blocks, cross, chain, transport, env) -> dict:
    idx = {block_id(b): b for b in blocks}
    hedged = hedge_overclaims(v2, blocks, cross)
    cands = candidates(v2.data, cross)
    info = {"candidates": len(cands), "overclaims_hedged": hedged}
    if not cands:
        info["status"] = "NO_CANDIDATES"
        return info
    items = [{"id": c["id"], "label": c["label"], "text": clean(c["text"]),
              "basis": {i: clean(block_text(idx[i]))[:1500] for i in c["ids"] if i in idx}} for c in cands]
    verdicts = {}
    try:
        r = run_chain(chain, [{"role": "system", "content": PROMPT},
                              {"role": "user", "content": json.dumps(items, ensure_ascii=False)}], transport, env)
        info.update(model=r.model_used, provider=r.provider_used, usage=r.usage, latency_s=round(r.latency_s, 2))
        for it in loads_lenient(r.text).get("items") or []:
            if isinstance(it, dict) and it.get("id"):
                verdicts[it["id"]] = it
        info["status"] = "OK"
    except (AllProvidersFailed, ValueError, AttributeError, TypeError) as e:
        info["status"] = f"JUDGE_FAILED: {type(e).__name__}"
    removed = []
    for c in cands:
        j = verdicts.get(c["id"], {})
        v, q, bid = j.get("verdict"), j.get("quote") or "", j.get("block_id")
        gate = None
        if v in ("TESTED", "AUTHOR_STATEMENT_UNTESTED"):
            b = idx.get(bid) if bid in c["ids"] else None
            src = block_text(b) if b else ""
            if not b or not quote_in(q, src):
                v, gate = "UNSUPPORTED", "quote not verbatim in a basis block"
            elif v == "TESTED" and not has_test(clean(q)):
                v, gate = "UNSUPPORTED", "TESTED quote has no test statistic"
            elif v == "AUTHOR_STATEMENT_UNTESTED" and (c["label"] != "PAPER" or not COMPARATIVE.search(clean(q))):
                v, gate = "UNSUPPORTED", "not an author comparative statement"
        elif v != "UNSUPPORTED":
            v = "UNSUPPORTED"
        if v == "UNSUPPORTED":
            hit = paired_test_in_basis(c["text"], c["ids"], idx)
            if hit:   # the judge (or its quote) failed, but the code can see the test in the cited block itself
                v, gate, bid = "TESTED", "wording_judge.deterministic_rescue: values + test statistic in one cited block", hit
        field = "text" if c["kind"] == "stmt" else "claim"
        entry = {"where": f"wording_judge.{c['kind']}", "original": c["text"], "verdict": v, "reason": j.get("reason"),
                 "quote": q or None, "block_id": bid, "judge_verdict": j.get("verdict"),
                 "gate": gate or ("wording_judge.fail_closed" if info.get("status") != "OK" else "wording_judge.verdict")}
        if v == "TESTED":
            if gate:
                info.setdefault("rescued", []).append({"text": c["text"], "block_id": bid})
            continue
        if v == "AUTHOR_STATEMENT_UNTESTED":
            c["obj"][field] = c["text"] + "（作者表述，无对应检验）"
            entry.update(result=c["obj"][field], rule="judge: author statement without matching test -> annotated")
        else:
            basis = "\n".join(block_text(idx[i]) for i in c["ids"] if i in idx)
            new, refused = _rewrite(c["text"], basis)
            if not new and c["label"] == "PAPER" and verbatim_comparative(c["text"], basis):
                c["obj"][field] = c["text"] + ANNOT_PAPER
                entry.update(result=c["obj"][field], gate="wording_judge.verbatim_comparative",
                             rule="judge: unsupported, but the comparative is the paper's own wording -> annotated")
                v2.wording.append(entry)
                continue
            if new:
                c["obj"][field] = new
                entry.update(result=new, rule="judge: unsupported comparative -> neutral rewrite")
            else:
                entry.update(result=None, rule="judge: unsupported comparative, no safe rewrite -> rejected"
                             + (f" ({refused})" if refused else ""))
                removed.append(c)
        v2.wording.append(entry)
    for c in removed:
        if c["kind"] == "vision":
            c["obj"].update(verdict="UNVERIFIABLE", gate="unsupported comparative (wording judge)")
        elif isinstance(c["parent"], list):
            c["parent"][c["key"]] = None
        else:
            c["parent"][c["key"]] = None
        v2.rejected.append({"where": "wording_judge", "item": c["obj"], "reason": "unsupported comparative, no safe rewrite"})
    # drop None entries from statement lists
    def prune(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, list):
                    o[k] = [prune(x) for x in v if x is not None]
                else:
                    prune(v)
        return o
    prune(v2.data)
    info["counts"] = {k: sum(1 for w in v2.wording if w.get("verdict") == k)
                      for k in ("UNSUPPORTED", "AUTHOR_STATEMENT_UNTESTED")}
    info["tested_kept"] = len(cands) - sum(1 for w in v2.wording if w.get("where", "").startswith("wording_judge"))
    refresh_stats(v2)
    return info
