#!/bin/sh
# Build dist/Litreader.app on macOS with PyInstaller (onedir + BUNDLE; see docs/MAC_RUN_GUIDE.md §7).
# Why PyInstaller and not py2app: PyInstaller ships maintained hooks for PySide6 (Qt plugins/frameworks are relocated
# into Contents/Frameworks + Contents/Resources so the bundle can be code-signed) and sets CFBundleIdentifier /
# Info.plist via BUNDLE(); py2app needs manual Qt plugin recipes for PySide6. Neither can be verified on Linux.
# Builds only — nothing is installed, signed, notarised or uploaded. Your config.local.toml, models.toml and keychain
# entries are NOT copied into the app; the app reads ~/litreader/config.local.toml like `litreader gui`.
set -e
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != "Darwin" ]; then
  echo "build_app.sh 只能在 macOS 上运行（当前：$(uname -s)）。"; exit 2
fi
PY=./.venv/bin/python
[ -x "$PY" ] || { echo "找不到 .venv：先按 MAC_RUN_GUIDE 安装（./scripts/mac_install.sh）"; exit 1; }
"$PY" -m pip install -q --upgrade "pyinstaller>=6.6"          # build-time only, into this .venv
mkdir -p build
"$PY" packaging/make_icns.py build/Litreader.icns
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/Litreader.spec
APP=dist/Litreader.app
/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist"
# ad-hoc signature so Gatekeeper treats the local build consistently (no Apple ID involved)
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "（ad-hoc 签名失败，可忽略：仍可右键→打开）"
echo "✅ $APP"
echo "首次打开：在 Finder 里右键 Litreader.app → 打开（未公证的本地构建）。可拖进「应用程序」文件夹。"
