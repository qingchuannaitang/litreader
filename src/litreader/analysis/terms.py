"""Deterministic display-term fixes for model-written prose (review fix 19).

Only spelling/term-consistency rewrites that cannot change a fact:
- "密度 26 个标志点" → "密集 26 个标志点" (dense ≠ density when it modifies a count of landmarks/points);
- an abbreviation the paper defines with a trailing R (ACLR) written without it before a person noun
  ("ACL 患者") → the defined form, only when the bare form is not itself a defined abbreviation.
"""
from __future__ import annotations

import re

_DENSE = re.compile(r"密度\s*(?=\d+\s*个\s*(?:[\u4e00-\u9fff]{0,4})(?:标志点|关键点|标记点|点))")
_PERSON = r"(?=\s*(?:患者|个体|组|人群|参与者|受试者|者))"


def normalize(text: str, abbrs: list[dict] | None = None) -> str:
    if not text:
        return text
    t = _DENSE.sub("密集 ", text)
    names = {a.get("abbr") for a in abbrs or [] if a.get("abbr")}
    for a in names:
        base = a[:-1]
        if a.endswith("R") and len(base) >= 2 and base not in names:
            t = re.sub(rf"(?<![A-Za-z]){re.escape(base)}(?![A-Za-z]){_PERSON}", a, t)
    return t
