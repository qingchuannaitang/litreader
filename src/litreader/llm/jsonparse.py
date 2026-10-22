"""Lenient JSON for vendors without JSON mode: accept a bare object, or one wrapped in ``` fences / prose."""
from __future__ import annotations

import json
import re


def loads_lenient(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    if not isinstance(text, str):
        raise ValueError("not text")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object found")
    return json.loads(m.group(1) if m.lastindex else m.group(0))
