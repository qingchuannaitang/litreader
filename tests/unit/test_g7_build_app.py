"""G7-9: Litreader.app packaging pieces that can be checked on Linux: the .icns writer (valid container with the
standard PNG sizes), the spec's identifiers, and the build script refusing to run off macOS. The PyInstaller build
itself can only run on a Mac."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))
import make_icns  # noqa: E402


def test_icns_container_from_fake_pngs():
    raw = make_icns.build_icns(png=lambda n: b"\x89PNG" + n.to_bytes(4, "big"))
    entries = make_icns.parse_icns(raw)
    assert [t for t, _ in entries] == [t for t, _ in make_icns.TYPES] and all(n == 16 for _, n in entries)


def test_icns_real_l_icon():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    raw = make_icns.build_icns()
    assert raw[:4] == b"icns" and len(make_icns.parse_icns(raw)) == len(make_icns.TYPES)
    try:
        from PIL import Image
    except ImportError:
        return
    import io
    im = Image.open(io.BytesIO(raw))
    assert im.format == "ICNS" and (512, 512, 2) in im.info["sizes"]


def test_spec_and_script():
    spec = (ROOT / "packaging" / "Litreader.spec").read_text("utf-8")
    assert 'bundle_identifier=BUNDLE_ID' in spec and '"io.github.litreader.app"' in spec and 'name="Litreader.app"' in spec
    assert "console=False" in spec and "CFBundleShortVersionString" in spec
    from litreader.gui import macos
    assert macos.BUNDLE_ID == "io.github.litreader.app"
    sh = ROOT / "scripts" / "build_app.sh"
    assert os.access(sh, os.X_OK) and "PyInstaller" in sh.read_text("utf-8")
    if sys.platform != "darwin":
        r = subprocess.run(["sh", str(sh)], capture_output=True, text=True)
        assert r.returncode == 2 and "只能在 macOS" in r.stdout


def test_bundle_notify_falls_back_outside_bundle_and_uses_center_inside():
    from litreader.gui import macos
    assert macos.bundle_id() is None and macos.bundle_notify("t", "x") is False   # not frozen -> tray fallback
    posted = []

    class _Content:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setTitle_(self, t):
            self.t = t

        def setBody_(self, b):
            self.b = b

    class _Center:
        def requestAuthorizationWithOptions_completionHandler_(self, o, h):
            posted.append("auth")

        def addNotificationRequest_withCompletionHandler_(self, req, h):
            posted.append(req)

    class UN:
        UNAuthorizationOptionAlert, UNAuthorizationOptionSound = 1, 2
        UNMutableNotificationContent = _Content

        class UNUserNotificationCenter:
            @staticmethod
            def currentNotificationCenter():
                return _Center()

        class UNNotificationRequest:
            @staticmethod
            def requestWithIdentifier_content_trigger_(i, c, t):
                return (c.t, c.b)

    macos._UN_STATE.clear()
    assert macos.bundle_notify("Litreader · 精读完成", "note.md", _un=UN)
    assert posted == ["auth", ("Litreader · 精读完成", "note.md")]
