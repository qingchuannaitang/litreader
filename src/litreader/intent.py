"""Natural-language trigger -> intent. Deterministic regex first; LLM only as fallback, and its query must be a
verbatim substring of what the user typed (no invented titles). One paper at a time; batch is out of scope."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .llm.client import AllProvidersFailed, run_chain
from .llm.jsonparse import loads_lenient


@dataclass(frozen=True)
class Intent:
    action: str          # "read" | "batch" | "unknown"
    query: str | None
    method: str          # "regex" | "llm" | "none"
    run: dict | None = None   # usage/provider of the LLM fallback call, if any


_BATCH = re.compile(r"批量|全部|所有|这几篇|多篇|每一篇|逐篇")
_SUFFIX = re.compile(r"[，,。;；\s]*(?:并|然后|再|之后)?\s*(?:把|将)?\s*(?:精读|阅读)?(?:笔记|结果)?\s*"
                     r"(?:存入|存到|保存到|保存至|写入|放到|放进|存进|导入)\s*(?:到)?\s*(?:我的)?\s*obsidian.*$", re.I)
_LEAD = re.compile(r"^\s*(?:请|麻烦|帮我|帮忙|给我|你)*\s*(?:帮我|帮忙)?\s*")
_VERB = re.compile(r"^(?:精读|细读|阅读|读一下|读读|读)(?:一下)?\s*")
_SRC = re.compile(r"^(?:zotero|Zotero|ZOTERO)\s*(?:中|里|里面|库中|库里)?\s*(?:的)?\s*")
_QUOTES = "「」“”\"'《》『』‘’<>"
_TAIL = re.compile(r"\s*(?:这篇|那篇|这一篇)?\s*(?:论文|文献|文章|paper)?\s*$", re.I)


def parse_regex(text: str) -> Intent:
    t = (text or "").strip()
    if not t:
        return Intent("unknown", None, "none")
    if _BATCH.search(t):
        return Intent("batch", None, "regex")
    t = _SUFFIX.sub("", t)
    t = _LEAD.sub("", t)
    if not _VERB.match(t):
        return Intent("unknown", None, "none")
    t = _VERB.sub("", t)
    t = _SRC.sub("", t)
    t = re.sub(r"^(?:这篇|那篇|一篇)?\s*(?:论文|文献|文章)?\s*[:：]?\s*", "", t)
    t = _TAIL.sub("", t).strip().strip(_QUOTES).strip()
    t = _TAIL.sub("", t).strip().strip("，,。.;；").strip(_QUOTES).strip()
    if len(t) < 2:
        return Intent("unknown", None, "none")
    return Intent("read", t, "regex")


PROMPT = """把用户的一句话解析为指令，只输出 JSON：{"action": "read"|"batch"|"unknown", "query": str|null}
read=精读 Zotero 中的一篇论文，query 必须是用户原话中逐字出现的题名或关键词片段；batch=要求多篇；其他为 unknown。"""


def parse(text: str, chain=None, transport=None, env=None) -> Intent:
    it = parse_regex(text)
    if it.action != "unknown" or not chain:
        return it
    try:
        r = run_chain(chain, [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}], transport, env)
        d = loads_lenient(r.text)
    except (AllProvidersFailed, ValueError):
        return it
    run = {"provider": r.provider_used, "usage": r.usage}
    if not isinstance(d, dict):
        return Intent("unknown", None, "llm", run)
    act, q = d.get("action"), (d.get("query") or "").strip().strip(_QUOTES)
    if act == "batch":
        return Intent("batch", None, "llm", run)
    if act == "read" and len(q) >= 2 and q in text:
        return Intent("read", q, "llm", run)
    return Intent("unknown", None, "llm", run)
