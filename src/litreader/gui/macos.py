"""macOS niceties without a .app bundle (G5). All optional: without pyobjc (AppKit) or off macOS they do nothing.

What works when launched as `./.venv/bin/litreader gui` (a Python process, no bundle):
- Dock icon: NSApplication.applicationIconImage = the 'L' icon, while the app runs (Qt's setWindowIcon alone does not
  change the Dock icon on macOS). After quit the Dock shows Python's icon again.
- Menu-bar app name: patching NSBundle.mainBundle().infoDictionary()["CFBundleName"] BEFORE QApplication is created
  usually makes the bold first menu say "Litreader". The Dock tooltip/name and Activity Monitor still say "Python";
  permanent name + icon need a real .app bundle: scripts/build_app.sh (PyInstaller) builds dist/Litreader.app (G7-9).
- Notifications: inside Litreader.app (a real bundle id) they go through the system Notification Center
  (UserNotifications, pyobjc); outside a bundle the caller falls back to QSystemTrayIcon."""
from __future__ import annotations

import sys


def _appkit():
    if sys.platform != "darwin":
        return None
    try:
        import AppKit  # type: ignore  (pyobjc-framework-Cocoa)
        import Foundation  # type: ignore
        return AppKit, Foundation
    except ImportError:
        return None


def set_app_name_early(name: str = "Litreader") -> bool:
    """Call before QApplication(...). Returns True if the bundle info was patched."""
    m = _appkit()
    if m is None:
        return False
    _, Foundation = m
    try:
        b = Foundation.NSBundle.mainBundle()
        ok = False
        for info in (b.localizedInfoDictionary(), b.infoDictionary()):
            if info is not None:
                info["CFBundleName"] = name
                ok = True
        return ok
    except Exception:  # noqa: BLE001 — cosmetic only
        return False


def set_dock_icon(png_bytes: bytes) -> bool:
    """Set the running app's Dock icon from PNG bytes. Returns True on success."""
    m = _appkit()
    if m is None or not png_bytes:
        return False
    AppKit, Foundation = m
    try:
        data = Foundation.NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        img = AppKit.NSImage.alloc().initWithData_(data)
        if img is None:
            return False
        AppKit.NSApplication.sharedApplication().setApplicationIconImage_(img)
        return True
    except Exception:  # noqa: BLE001
        return False


BUNDLE_ID = "io.github.litreader.app"


def bundle_id() -> str | None:
    """CFBundleIdentifier of the running process when it is a real .app bundle (PyInstaller sets sys.frozen)."""
    if not getattr(sys, "frozen", False):
        return None
    m = _appkit()
    if m is None:
        return None
    try:
        return str(m[1].NSBundle.mainBundle().bundleIdentifier() or "") or None
    except Exception:  # noqa: BLE001
        return None


_UN_STATE: dict = {}


def bundle_notify(title: str, text: str, _un=None) -> bool:
    """Post through Notification Center when running as Litreader.app. Returns False (caller uses the tray) when not
    in a bundle, without pyobjc's UserNotifications, or on any error. Authorisation is asked once per launch."""
    if _un is None:
        if not bundle_id():
            return False
        try:
            import UserNotifications as _un  # type: ignore  (pyobjc-framework-UserNotifications)
        except ImportError:
            return False
    try:
        center = _un.UNUserNotificationCenter.currentNotificationCenter()
        if not _UN_STATE.get("asked"):
            opts = _un.UNAuthorizationOptionAlert | _un.UNAuthorizationOptionSound
            center.requestAuthorizationWithOptions_completionHandler_(opts, lambda ok, err: _UN_STATE.update(ok=ok))
            _UN_STATE["asked"] = True
        content = _un.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(text)
        import uuid
        req = _un.UNNotificationRequest.requestWithIdentifier_content_trigger_(str(uuid.uuid4()), content, None)
        center.addNotificationRequest_withCompletionHandler_(req, None)
        return True
    except Exception:  # noqa: BLE001
        return False
