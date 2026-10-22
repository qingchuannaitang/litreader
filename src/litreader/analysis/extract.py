"""Run extraction over chunks with the configured fallback chain; merge chunk outputs."""
from __future__ import annotations

import json

from ..llm.jsonparse import loads_lenient
from ..llm.client import run_chain
from .chunking import chunk
from .schema import REQUIRED_FIELDS, SCHEMA_DOC

SYSTEM = ("你是严谨的医学文献信息抽取器。只依据给定的原文块抽取，不得使用外部知识，不得编造。"
          "输出 JSON。" + SCHEMA_DOC + "\nREQUIRED_FIELDS = " + json.dumps(REQUIRED_FIELDS))


def extract(blocks, chain, transport, env, max_chars=60000):
    results, runs = [], []
    chunks = chunk(blocks, max_chars)
    for c in chunks:
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"原文块（第 {c.index+1}/{len(chunks)} 段，章节：{'、'.join(c.sections)}）：\n{c.render()}"}]
        r = run_chain(chain, msgs, transport, env)
        runs.append({"chunk": c.index, "model": r.model_used, "provider": r.provider_used,
                     "usage": r.usage, "latency_s": round(r.latency_s, 2), "attempts": r.attempts})
        try:
            results.append(json.loads(r.text))
        except ValueError:
            results.append({"facts": [], "claims": [], "_parse_error": True})
    merged = {"title_zh": None, "title_en": None, "facts": [], "claims": []}
    for r in results:
        for k in ("title_zh", "title_en"):
            if merged[k] is None or (merged[k] or {}).get("label") != "PAPER":
                merged[k] = r.get(k) or merged[k]
        merged["facts"] += r.get("facts") or []
        merged["claims"] += r.get("claims") or []
    return merged, runs, len(chunks)


def extract_v2(blocks, manifest, chain, transport, env, vision_obs: dict | None = None, max_chars=200000,
               template_suffix: str | None = None):
    """Single-pass v2 extraction (Zhong-size papers fit one chunk; larger papers: chunk then merge is Stage 5)."""
    from .schema_v2 import DOC, META_FIELDS
    chunks = chunk(blocks, max_chars)
    if len(chunks) != 1:
        raise ValueError(f"v2 extraction currently needs 1 chunk, got {len(chunks)} (raise max_chars or implement merge)")
    figs = []
    for m in manifest:
        line = {"id": m["id"], "kind": m["kind"], "caption": m["caption"], "pages": sorted({p["physical_page"] for p in m["parts"]})}
        if vision_obs and m["id"] in vision_obs:
            line["vision_observation_not_a_source_block"] = vision_obs[m["id"]]["finding"]
        figs.append(line)
    system = "输出 JSON。" + DOC + "\nMETA_FIELDS = " + json.dumps(META_FIELDS)
    if template_suffix:   # sandboxed, cleaned template data AFTER the program rules (templates/prompt.py)
        system += template_suffix
    user = (f"图表清单（视觉观察仅供参考，不能作为 basis_block_ids）：\n{json.dumps(figs, ensure_ascii=False)}\n\n"
            f"原文块：\n{chunks[0].render()}")
    r = run_chain(chain, [{"role": "system", "content": system}, {"role": "user", "content": user}], transport, env)
    run = {"model": r.model_used, "provider": r.provider_used, "usage": r.usage, "latency_s": round(r.latency_s, 2),
           "attempts": r.attempts}
    try:
        return loads_lenient(r.text), run
    except ValueError:
        return {"_parse_error": True}, run
