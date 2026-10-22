"""Rank UNKNOWN items by impact (deterministic keywords): conclusion > clinical applicability > reproducibility.
Metadata gaps rank last. Main note shows the top N; the archive keeps all with their scores."""
from __future__ import annotations

import re

WEIGHTS = [
    (3, "conclusion", ("结论", "因果", "显著", "效应", "差异", "偏倚", "混杂", "样本量", "统计", "冲突", "分母", "不一致", "偏侧", "单侧")),
    (2, "clinical", ("临床", "推广", "适用", "外推", "人群", "诊断", "筛查", "部署", "阈值")),
    (1, "reproducibility", ("复现", "公式", "系数", "参数", "补充", "原版", "英文", "版本", "数据", "方法", "定义", "ROM", "肌力")),
]


_RANGE = re.compile(r"\d+(?:\.\d+)?\s*[–\-~～至到]\s*\d+(?:\.\d+)?\s*岁?")
_MEAN_SD = re.compile(r"\d+\.\d+\s*(?:±\s*\d+(?:\.\d+)?|[（(]\s*\d+\.\d+\s*[)）])")


def malformed(u: dict) -> str | None:
    """Items whose stated conflict compares incommensurable things (e.g. a range vs mean±SD)."""
    text = f"{u.get('item', '')} {u.get('why', '')}"
    if not str(u.get("item", "")).strip():
        return "empty item"
    if _RANGE.search(text) and _MEAN_SD.search(text) and re.search(r"不一致|矛盾|冲突|不符", text):
        return "compares a range with mean±SD (not a contradiction)"
    return None


def score(u: dict) -> tuple[int, list[str]]:
    text = f"{u.get('item', '')} {u.get('why', '')}"
    if str(u.get("item", "")).startswith("元数据"):
        return 0, ["metadata"]
    s, tags = 0, []
    for w, tag, kws in WEIGHTS:
        if any(k in text for k in kws):
            s += w; tags.append(tag)
    return s, tags


def rank(unknowns: list[dict]) -> list[dict]:
    scored = []
    for i, u in enumerate(unknowns):
        bad = malformed(u)
        sc, tags = (-1, ["malformed"]) if bad else score(u)
        scored.append({**u, "impact": sc, "impact_tags": tags, "malformed": bad, "_i": i})
    scored.sort(key=lambda x: (-x["impact"], x["_i"]))
    return [{k: v for k, v in x.items() if k != "_i"} for x in scored]
