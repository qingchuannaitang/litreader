#!/bin/sh
# Build dist/litreader-<version>.zip (+ a dist/litreader.zip copy) from the committed tree only (git archive:
# untracked/ignored files such as config.local.toml, models.toml, .env, .spike_data/, logs, caches are never
# included), then refuse to keep the package if the secret check finds anything.
# The versioned name avoids macOS saving a second download as "litreader (1).zip" and `unzip` picking the old one.
set -e
cd "$(dirname "$0")/.."
python3 scripts/check_no_secrets.py
VER=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/litreader/__init__.py)
[ -n "$VER" ] || { echo "读不到 src/litreader/__init__.py 的 __version__"; exit 1; }
grep -q "^version = \"$VER\"" pyproject.toml || { echo "pyproject.toml 的 version 与 __version__ ($VER) 不一致"; exit 1; }
mkdir -p dist
OUT="dist/litreader-$VER.zip"
git archive --format=zip --prefix=litreader/ -o "$OUT" HEAD
if ! python3 scripts/check_no_secrets.py "$OUT"; then
  rm -f "$OUT"
  echo "已删除不安全的 $OUT"
  exit 1
fi
cp "$OUT" dist/litreader.zip
echo "$OUT (+ dist/litreader.zip) <- $(git rev-parse --short HEAD)"
