"""Pre-run estimate (labelled ESTIMATE). Local only: PDF page count / text length via poppler if available.
Ratios recalibrated on the first real Mac run of DeepGaitLab (2026-10-17; ≈38 458 non-space chars, 15 judge calls):
  主笔  input ≈ 0.57 tokens/char (actual 22 054), output ≈ 0.44 × input (actual 9 713)
  看图  per figure ≈ 1 900 in / 330 out
  核对  per figure ≈ 0.091 tokens/char (capped at 40 000 chars) ≈ 3 500 in / 500 out; wording check 8 450 / 700
  选文件夹 ≈ 345 / 40
  论文类型判定（选模板）≈ 1 500 / 150 (title + abstract + methods start ≤ 3 000 chars; skipped if a Zotero type tag exists)
Earlier Zhong 2021 ratios (0.454 / 0.60; vision 1 450/250; judge 0.256/600; wording 4 540/640) over-estimated the judge
and under-estimated vision on DeepGaitLab. Two papers are still a small sample: the ±40 % range stays.
Prices are never built in: cost is shown only for slots where the user filled price_in/price_out (元/百万 tokens).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

# review 4: judge output barely tracks figure count (15 calls → 8,288 out; 9 calls → 8,382 out), so most of it is a fixed per-paper cost carried on wording_out
RATIO = {"writer_in_per_char": 0.57, "writer_out_per_in": 0.44, "vision_in": 1900, "vision_out": 330,
         "judge_in_per_char": 0.091, "judge_ctx_cap": 40000, "judge_out": 120, "wording_in": 8450, "wording_out": 6400,
         "topic_in": 345, "topic_out": 40, "classify_in": 1500, "classify_out": 150, "chars_per_page": 2900, "spread": 0.4}


def pdf_stats(pdf: Path) -> dict:
    out = {"pages": None, "chars": None, "figures": None, "source": []}
    try:
        r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
        if m:
            out["pages"] = int(m.group(1)); out["source"].append("pdfinfo")
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(["pdftotext", "-q", str(pdf), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            t = r.stdout
            out["chars"] = len("".join(t.split())); out["source"].append("pdftotext")
            figs = {m.group(1) for m in re.finditer(r"(?:图|Fig(?:ure|\.)?)\s*(\d{1,2})\b", t)}
            out["figures"] = len(figs)
    except (OSError, subprocess.SubprocessError):
        pass
    return out


def estimate(stats: dict, roles_present: set[str], cached_parse: bool) -> dict:
    pages = stats.get("pages")
    chars = stats.get("chars") or ((pages or 0) * RATIO["chars_per_page"]) or None
    figs = stats.get("figures")
    if figs is None:
        figs = max(1, round((pages or 8) / 5))
    est = {"pages": pages, "chars": chars, "figures": figs, "chars_measured": bool(stats.get("chars")),
           "mineru_pages": 0 if cached_parse else pages, "roles": {}}
    if chars:
        w_in = int(chars * RATIO["writer_in_per_char"])
        est["roles"]["writer"] = {"in": w_in, "out": int(w_in * RATIO["writer_out_per_in"])}
        jc = min(chars, RATIO["judge_ctx_cap"])
        vis = "vision" in roles_present
        j_in = (int(jc * RATIO["judge_in_per_char"]) * figs if vis else 0) + RATIO["wording_in"] + RATIO["topic_in"] + RATIO["classify_in"]
        j_out = (RATIO["judge_out"] * figs if vis else 0) + RATIO["wording_out"] + RATIO["topic_out"] + RATIO["classify_out"]
        est["roles"]["judge"] = {"in": j_in, "out": j_out}
        if vis:
            est["roles"]["vision"] = {"in": RATIO["vision_in"] * figs, "out": RATIO["vision_out"] * figs}
    return est


def cost(tokens_in: int, tokens_out: int, price_in, price_out) -> float | None:
    if price_in is None or price_out is None:
        return None
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def fmt_range(n: int, spread=RATIO["spread"]) -> str:
    return f"约 {n:,}（{int(n * (1 - spread)):,}–{int(n * (1 + spread)):,}）"
