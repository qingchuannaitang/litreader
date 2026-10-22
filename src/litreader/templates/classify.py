"""Study-type classification for template selection (design §5.3-2; decision 9: judge call with verbatim evidence,
keyword cross-check, Zotero tag first). The result only chooses a presentation template; it never changes facts."""
from __future__ import annotations

import json
import re

from ..analysis.chunking import block_id, block_text
from ..llm.client import run_chain
from ..llm.jsonparse import loads_lenient
from .vocab import STUDY_TYPES

CTX_CHARS = 3000
EST_IN, EST_OUT = 1500, 150     # for the pre-run estimate

KEYWORDS = {
    "rct": [r"\brandomi[sz]ed\b", r"随机对照", r"随机分组", r"随机分配", r"\bRCT\b"],
    "non_randomized_intervention": [r"non-?randomi[sz]ed", r"quasi-experiment", r"非随机", r"类实验"],
    "cohort": [r"\bcohort\b", r"队列", r"prospective(ly)? follow", r"随访\s*\d+\s*年"],
    "case_control": [r"case-control", r"病例对照"],
    "cross_sectional": [r"cross-sectional", r"横断面"],
    "diagnostic_accuracy": [r"\bsensitivity\b", r"\bspecificity\b", r"敏感度|灵敏度", r"特异度", r"诊断准确", r"\bROC\b"],
    "prediction_model": [r"nomogram", r"列线图", r"prediction model", r"预测模型", r"risk score", r"\bAUC\b"],
    "systematic_review": [r"systematic review", r"meta-analys", r"系统综述|系统评价", r"荟萃分析|Meta\s*分析", r"PRISMA"],
    "narrative_review": [r"narrative review", r"综述"],
    "methods_technical": [r"we propose", r"deep learning", r"neural network", r"algorithm", r"深度学习", r"神经网络", r"算法", r"框架"],
    "qualitative": [r"qualitative", r"semi-structured interview", r"质性研究", r"访谈"],
    "case_report": [r"case report", r"病例报告", r"个案报道"],
}
TAG_MAP = {  # Zotero tags (exact, case-insensitive) that name a study type
    "rct": "rct", "随机对照试验": "rct", "randomized controlled trial": "rct", "cohort": "cohort", "队列研究": "cohort",
    "case-control": "case_control", "病例对照研究": "case_control", "cross-sectional": "cross_sectional",
    "横断面研究": "cross_sectional", "diagnostic accuracy": "diagnostic_accuracy", "诊断准确性": "diagnostic_accuracy",
    "prediction model": "prediction_model", "预测模型": "prediction_model", "systematic review": "systematic_review",
    "meta-analysis": "systematic_review", "系统综述": "systematic_review", "meta分析": "systematic_review",
    "review": "narrative_review", "综述": "narrative_review", "qualitative": "qualitative", "质性研究": "qualitative",
    "case report": "case_report", "病例报告": "case_report", "方法学": "methods_technical", "ai": "methods_technical",
}
RELATED = [{"diagnostic_accuracy", "prediction_model"}, {"prediction_model", "methods_technical"},
           {"systematic_review", "narrative_review"}, {"rct", "non_randomized_intervention"}]

PROMPT = """你判断一篇医学/科研论文的研究设计类型，只用于选择笔记排版模板。只依据给出的原文块。
类型只能从以下代码中选（JSON 里写代码）：""" + json.dumps(STUDY_TYPES, ensure_ascii=False) + """
quote 必须是 block_id 对应原文块中逐字连续出现的一句话（≤80字），用作判断依据；找不到依据就 confidence ≤0.3。
只输出 JSON：{"study_type": 代码, "secondary": [≤2 个代码], "confidence": 0-1, "reason": 中文≤40字, "quote": 原文逐字, "block_id": "bN"}"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def zotero_tag_type(tags: list[str]) -> str | None:
    hits = {TAG_MAP[t.strip().lower()] for t in tags or [] if t and t.strip().lower() in TAG_MAP}
    if not hits:
        hits = {t.split(":", 1)[1].strip() for t in tags or [] if t and t.lower().startswith(("type:", "研究类型:"))
                and t.split(":", 1)[1].strip() in STUDY_TYPES}
    return hits.pop() if len(hits) == 1 else None


def context_blocks(blocks, limit: int = CTX_CHARS):
    """Title, abstract and the start of the methods (first blocks until the budget is used)."""
    body = [b for b in blocks if b.kind in ("text", "title") and block_text(b).strip()]
    out, n = [], 0
    meth = next((i for i, b in enumerate(body) if b.kind == "title" and re.search(r"方法|Methods?|对象|Participants", block_text(b), re.I)), None)
    order = body[:12] + (body[meth:meth + 6] if meth and meth >= 12 else [])
    for b in order:
        t = block_text(b)
        if n + len(t) > limit and out:
            break
        out.append(b)
        n += len(t)
    return out


def keyword_scores(text: str) -> dict[str, int]:
    out = {}
    for k, pats in KEYWORDS.items():
        c = sum(len(re.findall(p, text, re.I)) for p in pats)
        if c:
            out[k] = c
    return out


def _related(a, b) -> bool:
    return a == b or any(a in g and b in g for g in RELATED)


def classify(blocks, *, title: str = "", zotero_tags: list[str] | None = None, chain=None, transport=None, env=None) -> dict:
    res = {"study_type": "other", "secondary": [], "confidence": 0.0, "reason": "", "quote": None, "block_id": None,
           "page": None, "source": "none", "keyword_check": "none", "ambiguous": True, "run": None, "keywords": {}}
    ctx = context_blocks(blocks)
    text = title + "\n" + "\n".join(block_text(b) for b in ctx)
    kw = keyword_scores(text)
    res["keywords"] = kw
    top_kw = sorted(kw.items(), key=lambda x: -x[1])
    tag = zotero_tag_type(zotero_tags or [])
    if tag:   # decision 9: the user's own Zotero type tag wins, no model call
        res.update(study_type=tag, confidence=1.0, source="zotero_tag", reason="Zotero 中已有研究类型标签", ambiguous=False)
        res["keyword_check"] = "agree" if any(_related(tag, k) for k, _ in top_kw[:2]) else ("conflict" if top_kw else "none")
        return res
    if chain:
        idx = {block_id(b): b for b in blocks}
        user = "\n".join(f"[{block_id(b)}|p{b.physical_page}] {block_text(b)}" for b in ctx)
        try:
            r = run_chain(chain, [{"role": "system", "content": PROMPT}, {"role": "user", "content": f"题名：{title}\n{user}"}],
                          transport, env)
            res["run"] = {"model": r.model_used, "provider": r.provider_used, "usage": r.usage, "purpose": "study_type"}
            j = loads_lenient(r.text)
        except Exception as e:  # noqa: BLE001 - classification failure must not stop the run; we fall back + ask
            j = None
            res["reason"] = f"模型判定失败（{e.__class__.__name__}）"
        if isinstance(j, dict) and j.get("study_type") in STUDY_TYPES:
            st = j["study_type"]
            try:
                conf = max(0.0, min(1.0, float(j.get("confidence") or 0)))
            except (TypeError, ValueError):
                conf = 0.0
            q, bid = str(j.get("quote") or ""), str(j.get("block_id") or "")
            ok_quote = bool(q) and bid in idx and _norm(q) in _norm(block_text(idx[bid]))
            res.update(study_type=st, secondary=[s for s in (j.get("secondary") or []) if s in STUDY_TYPES and s != st][:2],
                       reason=str(j.get("reason") or "")[:60], source="llm")
            if ok_quote:
                res.update(quote=q, block_id=bid, page=idx[bid].physical_page, confidence=conf)
            else:
                res.update(confidence=0.0, reason=(res["reason"] + "；依据引文未逐字见于原文，视为无依据").lstrip("；"))
            if top_kw and top_kw[0][1] >= 2 and not any(_related(st, k) for k, n in top_kw if n >= 2):
                res["keyword_check"] = "conflict"
                res["confidence"] = min(res["confidence"], 0.5)
            elif top_kw:
                res["keyword_check"] = "agree" if any(_related(st, k) for k, _ in top_kw[:2]) else "weak"
            res["ambiguous"] = res["confidence"] < 0.6 or res["keyword_check"] == "conflict"
            return res
    # no model / model failed: keywords only, always confirmed by the user
    if top_kw and top_kw[0][1] >= 2 and (len(top_kw) == 1 or top_kw[0][1] > top_kw[1][1]):
        res.update(study_type=top_kw[0][0], confidence=0.4, source="keywords",
                   reason=(res["reason"] + "；" if res["reason"] else "") + "仅按关键词推测")
    return res


def describe(c: dict) -> str:
    name = STUDY_TYPES.get(c["study_type"], c["study_type"])
    src = {"zotero_tag": "Zotero 标签", "llm": "模型判定", "keywords": "关键词推测", "none": "未能判定"}[c["source"]]
    ev = f"依据：「{c['quote'][:40]}」p{c['page']}；" if c.get("quote") else ""
    kc = {"agree": "关键词交叉验证一致", "conflict": "⚠️ 与关键词线索不一致", "weak": "关键词线索弱", "none": "无关键词线索"}[c["keyword_check"]]
    why = f"  说明：{c['reason']}" if c.get("reason") else ""
    return f"{name}（{src}；{ev}置信度 {c['confidence']:.2f}；{kc}）{why}"
