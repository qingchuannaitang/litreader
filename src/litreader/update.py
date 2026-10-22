"""G8-9: optional update check. Reads a small public latest.json (GET only; nothing about the user is sent).
Any network / parse failure is silent (returns None). The URLs below are PLACEHOLDERS — TODO-configurable:
neither is a real, published address yet. Override with prefs["update_urls"]."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timedelta

# TODO-configurable placeholders (not real yet): the GitHub repo is not created and the VPS has no domain yet.
DEFAULT_URLS = [
    "https://raw.githubusercontent.com/qingchuannaitang/litreader/main/latest.json",   # TODO placeholder
    "https://example.invalid/litreader/latest.json",                                   # TODO placeholder (VPS)
]
DEFAULT_QQ_GROUP = "1126184965"
DEFAULT_FEEDBACK_URL = "https://github.com/qingchuannaitang/litreader/issues"          # TODO: repo not created yet
SNOOZE_DAYS = 3
FIELDS = ("version", "notes", "download_url", "qq_group")


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(v or "").split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def newer(remote: str, local: str) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def validate(d) -> dict | None:
    if not isinstance(d, dict) or not isinstance(d.get("version"), str) or not re.match(r"^\d+(\.\d+){0,3}", d["version"]):
        return None
    out = {k: str(d.get(k) or "").strip() for k in FIELDS}
    if out["download_url"] and not out["download_url"].startswith("https://"):
        out["download_url"] = ""
    if out["qq_group"] and not re.fullmatch(r"\d{5,12}", out["qq_group"]):
        out["qq_group"] = ""
    return out


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "litreader-update-check"})   # no cookies, no ids
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (https only, enforced by caller)
        return r.read(64 * 1024)


def fetch_latest(urls=None, timeout: float = 5.0, getter=None) -> dict | None:
    """First URL that answers with a valid latest.json wins. Never raises."""
    getter = getter or _get
    for u in urls or DEFAULT_URLS:
        if not str(u).startswith("https://") or ".invalid/" in str(u):
            continue
        try:
            d = validate(json.loads(getter(u, timeout).decode("utf-8")))
        except Exception:   # noqa: BLE001 — silent by design
            continue
        if d:
            return d
    return None


def due(prefs, today: date | None = None) -> bool:
    """Automatic check: only when enabled and at most once per day."""
    today = today or date.today()
    return bool(prefs.get("auto_update")) and prefs.get("last_update_check") != today.isoformat()


def should_announce(info: dict | None, local: str, prefs, now: datetime | None = None) -> bool:
    if not info or not newer(info["version"], local):
        return False
    if prefs.get("skipped_version") == info["version"]:
        return False
    until = prefs.get("remind_after") or ""
    return not until or (now or datetime.now()).isoformat() >= until


def snooze_until(now: datetime | None = None) -> str:
    return ((now or datetime.now()) + timedelta(days=SNOOZE_DAYS)).isoformat(timespec="seconds")
