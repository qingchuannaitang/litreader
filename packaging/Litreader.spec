# PyInstaller spec for Litreader.app (macOS). Built by scripts/build_app.sh — do not run on Linux/Windows.
# onedir + BUNDLE (windowed): PyInstaller's recommended layout for PySide6 apps on macOS (code-sign friendly).
import os
import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VER = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "src/litreader/__init__.py")).read()).group(1)
BUNDLE_ID = os.environ.get("LITREADER_BUNDLE_ID", "io.github.litreader.app")
ICNS = os.environ.get("LITREADER_ICNS", os.path.join(ROOT, "build", "Litreader.icns"))

from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: E402

a = Analysis([os.path.join(ROOT, "packaging", "litreader_app.py")],
             pathex=[os.path.join(ROOT, "src")],
             datas=collect_data_files("litreader"),          # gui/icons/*.svg, built-in templates (*.md), etc.
             hiddenimports=collect_submodules("litreader") + ["keyring.backends.macOS"],
             excludes=["tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Litreader", console=False, target_arch=None,
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Litreader")
app = BUNDLE(coll, name="Litreader.app", icon=ICNS, bundle_identifier=BUNDLE_ID, version=VER,
             info_plist={"CFBundleName": "Litreader", "CFBundleDisplayName": "Litreader",
                         "CFBundleShortVersionString": VER, "CFBundleVersion": VER,
                         "NSPrincipalClass": "NSApplication", "NSHighResolutionCapable": True,
                         "LSMinimumSystemVersion": "11.0", "LSApplicationCategoryType": "public.app-category.education",
                         "NSUserNotificationAlertStyle": "banner"})
