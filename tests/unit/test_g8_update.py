"""G8-9: version compare, latest.json validation, silent failure, once-a-day, skip/snooze."""
import json
from datetime import date, datetime

from litreader import update


class P(dict):
    def get(self, k, d=None):
        return super().get(k, d)

    def set(self, k, v):
        self[k] = v


def test_newer():
    assert update.newer("0.6.1", "0.6.0") and update.newer("1.0", "0.9.9") and not update.newer("0.6.0", "0.6")
    assert not update.newer("0.5.9", "0.6.0") and update.newer("0.10.0", "0.9.0")


def test_fetch_validates_and_is_silent():
    good = {"version": "0.7.0", "notes": "修复", "download_url": "https://x.example/a.zip", "qq_group": "123456"}
    calls = []

    def getter(u, t):
        calls.append(u)
        if "bad" in u:
            raise OSError("offline")
        return json.dumps(good).encode()
    assert update.fetch_latest(["https://bad/l.json", "https://ok/l.json"], getter=getter) == good
    assert update.fetch_latest(["https://bad/l.json"], getter=getter) is None
    assert update.fetch_latest(["http://plain/l.json", "https://example.invalid/x"], getter=getter) is None
    assert all(c.startswith("https://") and ".invalid" not in c for c in calls)
    assert update.validate({"version": "x"}) is None
    assert update.validate({"version": "1.0", "download_url": "http://x", "qq_group": "abc"})["download_url"] == ""


def test_once_a_day_and_skip_and_snooze():
    p = P(auto_update=True, last_update_check="2026-10-21")
    assert not update.due(p, date(2026, 10, 21)) and update.due(p, date(2026, 10, 22))
    p["auto_update"] = False
    assert not update.due(p, date(2026, 10, 22))
    info = {"version": "0.7.0"}
    q = P(skipped_version="", remind_after="")
    assert update.should_announce(info, "0.6.0", q)
    q["skipped_version"] = "0.7.0"
    assert not update.should_announce(info, "0.6.0", q) and update.should_announce({"version": "0.7.1"}, "0.6.0", q)
    q["remind_after"] = update.snooze_until(datetime(2026, 10, 21))
    assert not update.should_announce({"version": "0.7.1"}, "0.6.0", q, now=datetime(2026, 10, 22))
    assert update.should_announce({"version": "0.7.1"}, "0.6.0", q, now=datetime(2026, 10, 25))


def test_placeholders_are_marked_todo():
    src = open(update.__file__, encoding="utf-8").read()
    assert src.count("TODO") >= 3 and update.DEFAULT_QQ_GROUP == "1126184965"


def test_make_latest_json(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    out = tmp_path / "latest.json"
    subprocess.run([sys.executable, str(root / "scripts/make_latest_json.py"), "--version", "0.6.0", "--notes", "n",
                    "--download-url", "https://x.example/a.zip", "-o", str(out)], check=True, capture_output=True)
    d = json.loads(out.read_text("utf-8"))
    assert update.validate(d) == d and d["qq_group"] == "1126184965"
