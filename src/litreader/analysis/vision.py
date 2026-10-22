"""Figure observation with a configured vision provider (station "vision"; must have supports_vision=true).

Output is labelled PAPER（图像观察）: it is what the model read off the real crop, not verified by a human.
Any failure returns None so the renderer falls back to the caption+text finding, explicitly labelled.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from ..llm.client import AllProvidersFailed, run_chain

PROMPT = ("你在核读一篇论文的原图裁剪（可能有多个分图）。图注：{caption}\n"
          "只描述图中实际可见的内容：图类型、面板、坐标轴/单位、能读出的全部数字（如 n=…、均值、p 值）。"
          "看不清或图中没有的写入 unreadable，不要猜，不要用外部知识。"
          "全部用中文描述；图中的英文标签、图例、坐标轴名译成中文并在括号里保留英文原文，例如：地面行走（Overground walking）、"
          "运动学均方根差（Kinematics RMSD）、双相机（2 Cams）、标志点模板（Landmark template）。"
          "不得出现括号外的英文词组；只有缩写和专有名（如 RMSD、ACLR、OpenCap、Theia3D）、单个字母（面板 A、p、N）可以直接写。"
          "缩写与图注/正文保持一致（如 ACLR 不要写成 ACL）。"
          "只返回 JSON：{{\"title\": 概括此图内容的中文短标题(≤20字，不写图号), \"finding\": 中文主要发现(≤180字), \"numbers\": [图中读到的数字字符串], \"unreadable\": 中文}}")

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def observe(fig: dict, assets_root: Path, chain, transport, env, max_bytes=10 * 1024 * 1024) -> tuple[dict | None, dict]:
    """Return (observation | None, run_info)."""
    content = [{"type": "text", "text": PROMPT.format(caption=fig.get("caption") or "（无图注）")}]
    for p in fig["parts"]:
        f = assets_root / p["img_path"]
        if not f.is_file() or f.stat().st_size > max_bytes or f.suffix.lower() not in _MIME:
            return None, {"id": fig["id"], "status": "SKIPPED", "reason": f"image unusable: {p['img_path']}"}
        b64 = base64.b64encode(f.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{_MIME[f.suffix.lower()]};base64,{b64}"}})
    try:
        r = run_chain(chain, [{"role": "user", "content": content}], transport, env)
    except AllProvidersFailed as e:
        return None, {"id": fig["id"], "status": "FAILED", "attempts": e.attempts}
    obs = _json(r.text)
    info = {"id": fig["id"], "status": "OK" if obs and obs.get("finding") else "BAD_OUTPUT", "model": r.model_used, "provider": r.provider_used,
            "usage": r.usage, "latency_s": round(r.latency_s, 2), "images": len(fig["parts"])}
    if not obs or not obs.get("finding"):
        return None, info
    return {"title": str(obs.get("title") or "").strip()[:30], "finding": str(obs["finding"]).strip(), "numbers": [str(n) for n in obs.get("numbers") or []],
            "unreadable": str(obs.get("unreadable") or "").strip(), "model": r.model_used}, info


def figure_hash(fig: dict, assets_root: Path) -> str:
    """sha256 over caption + every part image's bytes (missing parts hash as their path)."""
    import hashlib
    h = hashlib.sha256((fig.get("caption") or "").encode())
    for p in fig["parts"]:
        f = assets_root / p["img_path"]
        h.update(f.read_bytes() if f.is_file() else p["img_path"].encode())
    return h.hexdigest()[:24]


def cached_observe(fig: dict, assets_root: Path, chain, transport, env, cache_dir: Path | None, item_key: str = ""):
    """observe() with a per-figure disk cache keyed by item + figure hash + primary model. Only OK results are
    cached, so a rerun after a failure re-pays nothing for figures already read. Returns (obs, info)."""
    if cache_dir is None or not chain:
        return observe(fig, assets_root, chain, transport, env)
    import re as _re
    model = _re.sub(r"[^A-Za-z0-9._-]+", "_", chain[0].model)
    key = f"{_re.sub(r'[^A-Za-z0-9]+', '_', item_key)}_{_re.sub(r'[^A-Za-z0-9]+', '_', fig['id'])}_{figure_hash(fig, assets_root)}_{model}"
    f = Path(cache_dir) / f"{key}.json"
    if f.is_file():
        try:
            d = json.loads(f.read_text("utf-8"))
            info = dict(d["info"], cached=True, usage={})
            # G10-2: entries cached before G8-7 have no "title". For a figure without caption the title is the only
            # source of a specific heading, so that one figure is read again (a few cents); others reuse the cache.
            if "title" in d["obs"] or (fig.get("caption") or "").strip():
                return d["obs"], info
        except (ValueError, KeyError, TypeError):
            pass
    obs, info = observe(fig, assets_root, chain, transport, env)
    if obs and info.get("status") == "OK":
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"obs": obs, "info": info}, ensure_ascii=False), "utf-8")
    return obs, info
