# PyInstaller spec for Litreader on Windows. Built by scripts/build_win.ps1 (or CI build-windows.yml).
# onedir (EXE with exclude_binaries + COLLECT), windowed (console=False) -> dist\Litreader\Litreader.exe
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICO = os.path.join(ROOT, "assets", "litreader.ico")

from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: E402

a = Analysis([os.path.join(ROOT, "packaging", "litreader_app.py")],
             pathex=[os.path.join(ROOT, "src")],
             datas=collect_data_files("litreader"),          # gui/icons/*.svg, built-in templates (*.md), etc.
             hiddenimports=collect_submodules("litreader")
             + ["keyring.backends.Windows", "win32ctypes", "win32ctypes.core", "win32ctypes.pywin32"],
             excludes=["tkinter", "keyring.backends.macOS", "AppKit", "Foundation", "objc"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Litreader", console=False, icon=ICO,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Litreader")
