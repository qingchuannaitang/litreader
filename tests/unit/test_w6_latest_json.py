"""W6: latest.json per-platform downloads, backward compatible with <=1.0.3 (which only reads FIELDS)."""
import importlib.util
import sys
from pathlib import Path

from litreader import update

ROOT = Path(__file__).resolve().parents[2]
D = {"version": "1.0.4", "notes": "n", "download_url": "https://github.com/x/releases/latest", "qq_group": "1126184965",
     "downloads": {"mac": "https://github.com/x/m.zip", "win": "https://github.com/x/w.zip"}}


def test_platform_link_preferred(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert update.validate(D)["download_url"] == "https://github.com/x/w.zip"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert update.validate(D)["download_url"] == "https://github.com/x/m.zip"
    monkeypatch.setattr(sys, "platform", "linux")
    assert update.validate(D)["download_url"] == D["download_url"]


def test_bad_or_missing_platform_link_falls_back(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert update.validate({**D, "downloads": {"win": "http://x"}})["download_url"] == D["download_url"]
    assert update.validate({**D, "downloads": "junk"})["download_url"] == D["download_url"]


def test_old_checker_contract_unchanged():
    # 1.0.3 validate(): version string + FIELDS only; extra keys are ignored
    assert set(update.FIELDS) == {"version", "notes", "download_url", "qq_group"}
    assert all(k in D for k in update.FIELDS)


def test_make_latest_json_downloads():
    spec = importlib.util.spec_from_file_location("mlj", ROOT / "scripts" / "make_latest_json.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    d = m.build("1.0.4", "n", D["download_url"], "1126184965", {"mac": "https://a", "win": ""})
    assert d["downloads"] == {"mac": "https://a"} and d["download_url"] == D["download_url"]
    assert "downloads" not in m.build("1.0.4", "n", "", "", {})
