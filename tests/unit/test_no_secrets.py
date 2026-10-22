"""Release guard: the shipped package must not contain any API key (user requirement 2026-10-18)."""
import importlib.util
import io
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_no_secrets", ROOT / "scripts" / "check_no_secrets.py")
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)


def test_tracked_files_have_no_keys():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout (unpacked zip): the build script checks the package")
    assert chk.scan_files(chk.tracked()) == []


def test_detector_catches_key_shapes_and_local_files(monkeypatch):
    fake = "sk-" + "Q" * 8 + "w3rty" * 4          # assembled at runtime so this file itself stays clean
    jwt = "eyJ" + "h" * 20 + "." + "p" * 12
    assert chk.scan_blob("a.py", f'x = "{fake}"'.encode(), {})
    assert chk.scan_blob("b.md", jwt.encode(), {})
    assert chk.scan_blob("c.toml", ('api_key = "' + "Z" * 24 + '"').encode(), {})
    for bad in ("litreader/config.local.toml", "litreader/.env", "x/calibration.json", "jobs/a/receipt-1.json",
                "litreader/models.toml", "a/run.log"):
        assert chk.scan_blob(bad, b"", {}), bad
    assert chk.scan_blob("ok.py", b"sk-SECRET-AAAA sk-abcdef1234567890 key_ref = \"DEEPSEEK_API_KEY\"", {}) == []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "value-only-in-env-123")
    hits = chk.scan_blob("d.txt", b"...value-only-in-env-123...", chk.env_values())
    assert hits == ["d.txt: contains the value of $DEEPSEEK_API_KEY"] and "value-only" not in hits[0]


def test_zip_scan(tmp_path):
    p = tmp_path / "p.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("litreader/README.md", "hi")
        z.writestr("litreader/config.local.toml", "x")
    assert chk.main([str(p)]) == 1


def test_example_configs_name_keys_but_hold_no_values():
    m = tomllib.loads((ROOT / "models.example.toml").read_text("utf-8"))
    for role, slots in m.items():
        for s in slots if isinstance(slots, list) else []:
            assert set(s) & {"key", "api_key", "token", "secret"} == set(), role
            assert s.get("key_ref", "").isupper()
    c = tomllib.loads((ROOT / "config.example.toml").read_text("utf-8"))
    flat = str(c)
    assert "api_key" not in flat and "sk-" not in flat
