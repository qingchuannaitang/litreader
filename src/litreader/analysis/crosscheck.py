"""Vision cross-check: a vision finding never enters the note as PAPER until its claims are tied to parsed text/tables.

Steps
 1. Deterministic: numbers in the vision finding vs numbers anywhere in the parsed text/tables.
 2. LLM judge (text-only, JSON mode): split the finding into atomic claims; per claim give verdict
    CONSISTENT | CONTRADICTED | UNVERIFIABLE with a verbatim quote + block_id from the text/tables.
 3. Gate: a quote that is not verbatim in its block (or wrong block) downgrades the claim to UNVERIFIABLE;
    a CONSISTENT claim whose numbers are not in the quoted block also downgrades to UNVERIFIABLE.
Judge failure => every claim UNVERIFIABLE (未核对). CONTRADICTED claims are rendered as conflicts, never PAPER.
"""
from __future__ import annotations

import json
import re

from ..llm.jsonparse import loads_lenient
from ..llm.client import AllProvidersFailed, run_chain
from .chunking import block_id, block_text, sections
from .latex import clean
from .validator import norm, quote_in
from .validator_v2 import numbers

VERDICTS = {"CONSISTENT", "CONTRADICTED", "UNVERIFIABLE"}

CONTEXT_RULES = """
核对规则（重要）：
1. 显著性必须按“本文自己的显著性阈值”判断（见下方“本文阈值原句”，如 Bonferroni 校正后 p<0.002）。原文 p=0.012 而阈值为 p<0.002 时，原文结论是“不显著/趋势”，读图说“无显著差异”应判 CONSISTENT。
2. 人数分母要区分阶段：招募/筛选、分配/签署同意（assigned）、完成测试（completed）、最终分析（analysed）。读图数字与原文某一阶段一致即 CONSISTENT；只有同一阶段数字不同才是 CONTRADICTED。例如分配 23/34/25、分析 22/33/24 不矛盾。
3. 分组明细之和等于原文总数（如“各组各 1 人失败”与“3 名未完成”）判 CONSISTENT（若原文未给分组明细，可判 UNVERIFIABLE），不得判 CONTRADICTED。
4. 只有原文明确给出相反结论时才判 CONTRADICTED。
5. 判 CONTRADICTED 前必须核对比较对象完全一致：同一面板（A/B/C…）、同一相机数/设备配置、同一组别与同一指标。原文比较的是“两台相机的 A 对十台相机的 B”，而读图说的是“十相机下 A 与 B”时，不是矛盾，应判 UNVERIFIABLE。
"""

JUDGE = """你是论文核对员。下面是视觉模型对一张论文图的读图描述，以及论文正文/表格的原文块。
任务：把读图描述拆成原子陈述（每条只含一个判断：显著性/方向、数字、组间大小顺序、图的结构等），逐条与原文块比较：
- CONSISTENT：原文块明确支持；
- CONTRADICTED：原文块明确给出相反结论（如原文报告显著 p<0.0001，而读图说无显著差异；或数字/大小顺序不同）；
- UNVERIFIABLE：原文块没有足够信息。
对 CONSISTENT/CONTRADICTED 必须给出 block_id 和该块中的逐字原文片段 quote（≤150字，不得改写）。
claim 用中文；英文术语写成“中文（English）”，如 双相机（2 Cams）；缩写和专有名可直接写；quote 保持原文逐字。
只返回 JSON：{"claims":[{"claim": 中文, "verdict": "...", "block_id": str|null, "quote": str|null, "reason": 中文≤60字}]}""" + CONTEXT_RULES

_SENT = re.compile(r"[^。；;！!？?\n]+[。；;！!？?]?")
_THR = re.compile(r"[pP\ufffd]\s*[<≤]\s*0?\.\d+")   # MinerU sometimes renders italic p as U+FFFD
_THR_KW = re.compile(r"显著|统计学意义|Bonferroni|校正|significan|α|alpha", re.I)
_RULE = re.compile(r"认为|水平|设为|设定|定义|阈值|threshold|level|considered", re.I)
_DEN_KW = re.compile(r"招募|筛选|符合|签署|知情同意|纳入|分配|完成|未能完成|失败|排除|最终|分析")


def paper_context(blocks) -> dict:
    """Verbatim threshold and denominator sentences (deterministic) handed to the judge."""
    thr, den = [], []
    for s in sections(blocks):
        for b in s.blocks:
            if b.kind not in ("text", "footnote"):
                continue
            for sent in _SENT.findall(clean(block_text(b))):
                sent = sent.strip()
                if _THR.search(sent) and _THR_KW.search(sent):
                    thr.append({"block_id": block_id(b), "page": b.physical_page, "text": sent,
                                "is_rule": bool(_RULE.search(sent))})
                if _DEN_KW.search(sent) and re.search(r"\d+\s*(名|人|例|位)|n\s*=\s*\d+", sent) and len(den) < 12:
                    den.append({"block_id": block_id(b), "page": b.physical_page, "text": sent})
    thr.sort(key=lambda t: not t["is_rule"])           # threshold definitions before result p-values
    return {"thresholds": thr[:6], "denominators": den}


_NEG = re.compile(r"无显著|不显著|无统计学|无差异|未见差异|差异不显著|未达")
_PEQ = re.compile(r"[pP\ufffd]\s*[=＝]\s*(0?\.\d+)")
_RULE_P = re.compile(r"[pP\ufffd]\s*[<≤]\s*(0?\.\d+)")


def significance_override(claim: dict, thresholds: list[dict]) -> dict:
    """Deterministic guard against judge arithmetic errors on significance.
    A CONTRADICTED negative claim ("无显著差异") whose quoted p-values are all above the paper's strictest rule
    threshold cannot be a contradiction: if p is also above the loosest rule threshold -> CONSISTENT, otherwise the
    verdict depends on which threshold applies -> UNVERIFIABLE."""
    if claim.get("verdict") != "CONTRADICTED" or not _NEG.search(claim.get("claim", "")):
        return claim
    q = clean(claim.get("quote") or "")
    ps = [float(x) for x in _PEQ.findall(q)]
    if "|" in q:  # table row: "F (p)" / "d (p)" cells; any parenthesised value < 1 is a p-candidate.
        # Safe direction: an SD misread as p can only lower min(p), which blocks (never triggers) the override.
        ps += [float(x) for x in re.findall(r"\(\s*[<＜]?\s*(0?\.\d+)\s*\)", q)]
    rules = sorted({float(x) for t in thresholds if t.get("is_rule") for x in _RULE_P.findall(t["text"])})
    if not ps or not rules or min(ps) <= rules[0]:
        return claim
    if min(ps) > rules[-1]:
        return {**claim, "verdict": "CONSISTENT", "gate": f"significance override: p={min(ps)} > all paper thresholds {rules}"}
    return {**claim, "verdict": "UNVERIFIABLE",
            "gate": f"significance override: p={min(ps)} is non-significant under the paper's stricter threshold(s) {rules}; judge said contradiction"}


_CN_NUM = {"单": 1, "一": 1, "两": 2, "双": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_CAM = re.compile(r"(\d+|[单一两双二三四五六七八九十])\s*(?:台|个|部|路)?\s*(?:相机|摄像头|摄像机|机位)|(\d+)\s*-?\s*cams?\b", re.I)
_PANEL = re.compile(r"图\s*\d+\s*([A-H])(?![A-Za-z])|([A-H])\s*(?:面板|子图|图)|(?:面板|子图)\s*([A-H])(?![A-Za-z])")
_CAP_SEG = re.compile(r"[（(]\s*([A-H])\s*[)）]")


def cameras(text: str) -> set[int]:
    out = set()
    for m in _CAM.finditer(clean(text or "")):
        v = m.group(1) or m.group(2)
        out.add(int(v) if v.isdigit() else _CN_NUM[v])
    return out


def panels(text: str) -> set[str]:
    return {next(g for g in m.groups() if g) for m in _PANEL.finditer(clean(text or ""))}


def caption_segments(caption: str) -> dict[str, str]:
    """'(A) … (B) …' -> {'A': '…', 'B': '…'}"""
    parts = _CAP_SEG.split(clean(caption or ""))
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def contradiction_aligned(claim: str, quote: str, caption: str = "") -> str | None:
    """A CONTRADICTED verdict stands only if claim and quote talk about the same panel and the same camera
    configuration. Returns the misalignment reason (-> UNVERIFIABLE), or None when aligned."""
    cp, qp = panels(claim), panels(quote)
    if cp and qp and not (cp & qp):
        return f"panel not aligned: claim {sorted(cp)} vs quote {sorted(qp)}"
    seg = caption_segments(caption)
    cc = cameras(claim) | {n for p in cp for n in cameras(seg.get(p, ""))}
    qc = cameras(quote)
    if (cc or qc) and cc != qc:
        return f"camera configuration not aligned: claim {sorted(cc) or 'unspecified'} vs quote {sorted(qc) or 'unspecified'}"
    return None


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[\s，。、；：:（）()\[\]|]", "", clean(s or ""))
    return {s[i:i + 2] for i in range(len(s) - 1)}


_SIG_CLAIM = re.compile(r"显著|不显著|\bns\b|标\s*\*|\(\s*\*\s*\)")
_GLOSS = re.compile(r"[（(]\s*[A-Za-z][A-Za-z0-9 /&\-]*[）)]")


def vague_supported(claim: str, quote: str, source_text: str, block: str | None = None) -> str | None:
    """No-number claims: every Latin term must occur in the source, and the quote must share wording. None = OK.
    English glosses in brackets after a Chinese term (地面行走（Overground walking）) are not terms to verify.
    A significance claim backed by a quote that carries a test statistic may share its wording with the quoted
    block instead (the quote is then usually just '9.8±3.9° vs. 7.2±2.6°, p=0.0217')."""
    for w in re.findall(r"[A-Za-z][A-Za-z\-]{1,}", _GLOSS.sub("", claim)):
        if w.lower() not in source_text.lower():
            return f"term '{w}' not in source"
    cb, qb = _bigrams(_GLOSS.sub("", claim)), _bigrams(quote)
    if cb and len(cb & qb) / len(cb) >= 0.25:
        return None
    from .wording import has_stat
    if block and cb and _SIG_CLAIM.search(claim) and has_stat(quote) and len(cb & _bigrams(block)) / len(cb) >= 0.4:
        return None
    return "vague claim: quote does not share enough wording"


_LEGEND = re.compile(r"水平线|中位数线|箱体|四分位|须线|误差线|error ?bars?|图例|(?:红|蓝|绿|灰|紫|橙|黑)色(?:标记|圆点|线|箱)?(?:表示|代表|为)"
                     r"|配置示意|示意图|面板\s*[A-H]?\s*(?:展示|显示|为|对应)|对应(?:健康|验证)", re.I)
_COMPARE = re.compile(r"显著|高于|低于|优于|劣于|降低|升高|增加|减少|改善|一致性|差异|相当|更(?:低|高|好|差)|[<>≤≥]")


def caption_boilerplate(claim: str, quote: str | None, caption: str) -> str | None:
    """G7-12: a 'finding' that only restates the figure's own caption or legend (what panels show, colour keys, box-plot
    conventions, camera layouts) is not a result. Returns the reason to drop it from 主要发现, else None."""
    cl = clean(claim or "")
    if _LEGEND.search(cl) and not _COMPARE.search(cl):
        return "legend/caption boilerplate (no comparison)"
    if quote and caption and quote_in(quote, caption) and not _COMPARE.search(cl):
        return "restates the figure caption"
    return None


def page_matches(claim: str, block: str, min_share: float = 0.2) -> bool:
    """G7-12: the cited check page must actually contain matching wording, not just the same numbers."""
    cb = _bigrams(_GLOSS.sub("", claim))
    return not cb or len(cb & _bigrams(block)) / len(cb) >= min_share


def relevant_blocks(blocks, fig: dict, max_chars=40000):
    """Caption-referencing text, all tables, and results-section text (bounded)."""
    num = fig.get("number")
    ref = re.compile(rf"(图|Figure|Fig\.?)\s*{re.escape(num)}(?!\d)") if num else None
    pick, size = [], 0
    res_titles = ("结果", "Result", "讨论")
    for s in sections(blocks):
        in_res = any(t in s.title for t in res_titles)
        for b in s.blocks:
            t = block_text(b)
            if b.kind == "table" or in_res or (ref and ref.search(t)) or b.order in {p["order"] for p in fig["parts"] if "order" in p}:
                if size + len(t) > max_chars:
                    break
                pick.append(b); size += len(t)
    return pick


def deterministic(finding: str, blocks) -> dict:
    allnums = numbers(clean("\n".join(block_text(b) for b in blocks)))
    fn = numbers(finding)
    return {"found": sorted(fn & allnums), "not_found": sorted(fn - allnums)}


def judge(fig: dict, obs: dict, blocks, chain, transport, env):
    rel = relevant_blocks(blocks, fig)
    idx = {block_id(b): b for b in rel}
    src = "\n".join(f"[{block_id(b)}|p{b.physical_page}|{b.kind}] {clean(block_text(b))}" for b in rel)
    ctx = paper_context(blocks)
    ctx_txt = ("本文阈值原句：\n" + "\n".join(f"[{t['block_id']}|p{t['page']}] {t['text']}" for t in ctx["thresholds"]) +
               "\n\n人数/分母原句：\n" + "\n".join(f"[{t['block_id']}|p{t['page']}] {t['text']}" for t in ctx["denominators"]))
    user = f"图注：{fig.get('caption')}\n\n{ctx_txt}\n\n读图描述：{obs['finding']}\n\n原文块：\n{src}"
    det = deterministic(obs["finding"], blocks)
    info = {"id": fig["id"], "deterministic": det, "context": ctx}
    try:
        r = run_chain(chain, [{"role": "system", "content": JUDGE}, {"role": "user", "content": user}], transport, env)
        info.update(model=r.model_used, provider=r.provider_used, usage=r.usage, latency_s=round(r.latency_s, 2))
        data = loads_lenient(r.text)
        claims = data["claims"]
        if not isinstance(claims, list) or not claims:
            raise ValueError("no claims")
    except (AllProvidersFailed, ValueError, KeyError, TypeError) as e:
        info["status"] = f"JUDGE_FAILED: {type(e).__name__}"
        return [{"claim": obs["finding"], "verdict": "UNVERIFIABLE", "block_id": None, "quote": None,
                 "page": None, "reason": "核对模型失败，整段未核对", "gate": "judge_failed"}], info
    out, dropped = [], []
    for c in claims:
        if not isinstance(c, dict) or not c.get("claim"):
            continue
        v = c.get("verdict") if c.get("verdict") in VERDICTS else "UNVERIFIABLE"
        b = idx.get(c.get("block_id"))
        gate = None
        if v != "CONTRADICTED" and (why := caption_boilerplate(c["claim"], c.get("quote"), fig.get("caption") or "")):
            dropped.append({"claim": str(c["claim"]).strip(), "reason": why})
            continue
        if v in ("CONSISTENT", "CONTRADICTED"):
            q = c.get("quote") or ""
            if b is None or not quote_in(q, block_text(b)):
                v, gate = "UNVERIFIABLE", "quote not verbatim in cited block"
            elif v == "CONTRADICTED" and (mis := contradiction_aligned(c["claim"], q, fig.get("caption") or "")):
                v, gate = "UNVERIFIABLE", f"contradiction downgraded: {mis}"
            elif v == "CONSISTENT" and numbers(c["claim"]) - numbers(block_text(b)):
                v, gate = "UNVERIFIABLE", f"numbers not in cited block: {sorted(numbers(c['claim']) - numbers(block_text(b)))}"
            elif v == "CONSISTENT" and numbers(c["claim"]) and not page_matches(c["claim"], clean(block_text(b))):
                v, gate = "UNVERIFIABLE", "cited page has the numbers but not matching wording"
            elif v == "CONSISTENT" and not numbers(c["claim"]):
                why = vague_supported(c["claim"], q, (fig.get("caption") or "") + "\n" + src, clean(block_text(b)))
                if why:
                    v, gate = "UNVERIFIABLE", why
        out.append({"claim": str(c["claim"]).strip(), "verdict": v, "block_id": c.get("block_id") if b else None,
                    "quote": c.get("quote") if b else None, "page": b.physical_page if b else None,
                    "reason": str(c.get("reason") or "").strip(), "gate": gate})
    out = [significance_override(x, ctx["thresholds"]) for x in out]
    info["status"] = "OK"
    info["excluded_caption_boilerplate"] = dropped
    info["counts"] = {k: sum(x["verdict"] == k for x in out) for k in VERDICTS}
    return out, info
