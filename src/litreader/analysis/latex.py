"""Display-only cleanup of MinerU inline LaTeX. Raw values are kept unchanged in the evidence archive."""
from __future__ import annotations

import re

_SYM = [(r"\\phantom\s*\{[^{}]*\}", ""), (r"\\left\b|\\right\b", ""), (r"\\q?quad\b", " "), (r"\^\s*\{\s*\\circ\s*\}", "°"), (r"\^\s*\\circ", "°"), (r"_\s*\{\s*\\circ\s*\}", "。"),
        (r"\\pm", "±"), (r"\\times", "×"), (r"\\leq?\b", "≤"), (r"\\geq?\b", "≥"), (r"\\%", "%"),
        (r"\\cdot", "·"), (r"\\sim", "~"), (r"\\approx", "≈"), (r"\\alpha", "α"), (r"\\beta", "β"),
        (r"\\chi", "χ"), (r"\\mu", "μ"), (r"\\circ", "°"), (r"\\left|\\right", ""), (r"\\[:;,!]", " "),
        (r"\\Delta", "Δ"), (r"\\delta", "δ"), (r"\\sigma", "σ"), (r"\\gamma", "γ"), (r"\\lambda", "λ"),
        (r"\\pi\b", "π"), (r"\\rho", "ρ"), (r"\\tau", "τ"), (r"\\omega", "ω"), (r"\\theta", "θ"),
        (r"\\(?:var)?epsilon", "ε"), (r"\\kappa", "κ"), (r"\\eta\b", "η"), (r"\\nu\b", "ν"), (r"\\phi", "φ"),
        (r"\\(?:mathrm|textrm|text|mathbf|boldsymbol|mathit)\s*", "")]


_SPACED = re.compile(r"(?<![A-Za-z0-9])((?:[A-Za-z0-9]\s+){2,}[A-Za-z0-9])(?![A-Za-z0-9])")


def _join_spaced(m: re.Match) -> str:
    run = m.group(1)
    return re.sub(r"\s+", "", run) if sum(c.isalpha() for c in run) >= 2 else run


def _math(m: re.Match) -> str:
    s = re.sub(r"(?<!\\)~", " ", m.group(1))                # '~' is a LaTeX non-breaking space
    for pat, rep in _SYM:
        s = re.sub(pat, rep, s)
    s = re.sub(r"\^\s*\{\s*([^{}]*)\s*\}", r"^\1", s)
    s = re.sub(r"_\s*\{\s*([^{}]*)\s*\}", r"_\1", s)
    s = re.sub(r"\\[A-Za-z]+\s*", "", s)                     # unknown commands (\vec, \scriptscriptstyle, \AA) are layout noise
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    s = re.sub(r"(?<=[\d.])\s+(?=[\d.])", "", s)          # "5 . 9 1" -> "5.91"
    s = _SPACED.sub(_join_spaced, s)                          # "O p e n C a p" -> "OpenCap"
    s = re.sub(r"(?<![A-Za-z])([vV])\s*([sS])\s*\.\s*", r" \1\2. ", s)   # "v s ." -> " vs. "
    s = re.sub(r"\s*([°%±×≤≥<>=。,，])\s*", r"\1", s)
    s = re.sub(r"\s*([<>=≤≥])\s*", r" \1 ", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def clean(text: str | None) -> str:
    if not text:
        return text or ""
    t = re.sub(r"\$\$(.+?)\$\$", _math, text, flags=re.S)
    t = re.sub(r"\$([^$]+)\$", _math, t)
    t = re.sub(r"\$([^$]*)$", _math, t)                    # unterminated trailing math (truncated quote)
    t = re.sub(r"<sup>\s*(\[[^\]]*\])\s*</sup>", r"\1", t)    # citation superscript <sup>[47]</sup> -> [47]
    t = re.sub(r"<sup>(.*?)</sup>", r"^\1", t)
    t = re.sub(r"\^\s*\[", "[", t)                                  # '^[' is Obsidian inline-footnote syntax
    t = re.sub(r"<sub>(.*?)</sub>", r"_\1", t)
    t = t.replace("\\*", "*")
    return t.strip()
