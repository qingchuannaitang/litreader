"""G8-11 / G11-3: LICENSE = the official AGPL-3.0 text, byte for byte (so GitHub detects AGPL-3.0); the copyright
line lives in NOTICE and README."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGPL_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"   # gnu.org/licenses/agpl-3.0.txt


def test_license_text_is_official_and_has_copyright():
    raw = (ROOT / "LICENSE").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == AGPL_SHA256                      # nothing prepended or changed
    for f in ("NOTICE", "README.md"):
        assert "Copyright (C) 2026 王鸿涛 (qingchuannaitang)" in (ROOT / f).read_text("utf-8")


def test_pyproject_contributing_and_third_party():
    assert "AGPL-3.0" in (ROOT / "pyproject.toml").read_text("utf-8")
    assert "任何许可证" in (ROOT / "CONTRIBUTING.md").read_text("utf-8")
    assert "ISC" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text("utf-8")
    assert (ROOT / "src/litreader/gui/icons/LICENSE.txt").is_file()
