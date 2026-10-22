#!/bin/zsh
# litreader 一键安装（只在你自己的 Mac 上运行；不需要 sudo；可重复运行）
# 做的事：检查 Homebrew Python 3.12 → 在本文件夹建 .venv → 安装 litreader → 生成 config.local.toml（已存在则不动）
set -e
cd "$(dirname "$0")/.."
echo "== litreader 安装 =="

PY=""
for c in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 python3.12 python3.13 python3.11; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "❌ 没找到 Python 3.11+。请先按 MAC_RUN_GUIDE.md 第 1 步安装 Homebrew 和 python@3.12，然后重新运行本脚本。"
  exit 1
fi
echo "✅ 使用 Python：$PY（$($PY --version)）"

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
./.venv/bin/python -m pip install --upgrade pip >/dev/null
./.venv/bin/python -m pip install -e ".[mac]"
echo "✅ litreader 已安装到 $(pwd)/.venv"

if [ -f config.local.toml ]; then
  echo "ℹ️ 已有 config.local.toml，保持不变。"
else
  echo ""
  echo "请把你的 Obsidian 库文件夹从访达拖进这个窗口（会自动填入路径），然后按回车："
  read -r VAULT
  # 只写入库路径；模型设置在 models.toml
  VAULT="$VAULT" ./.venv/bin/python - <<'PYEOF'
import os, re, sys
raw = os.environ["VAULT"].strip().strip("'\"").replace("\\ ", " ")
vault = raw.rstrip("/") or raw
if not os.path.isdir(vault):
    sys.exit(f"❌ 文件夹不存在：{vault}（请重新运行本脚本）")
s = open("config.example.toml", encoding="utf-8").read()
v = vault.replace("\\", "\\\\").replace('"', '\\"')
s = s.replace('root = ""', f'root = "{v}"', 1)
open("config.local.toml", "x", encoding="utf-8").write(s)
PYEOF
  echo "✅ 已生成 config.local.toml"; grep "^root" config.local.toml
fi
if [ -f models.toml ]; then
  echo "ℹ️ 已有 models.toml，保持不变。"
elif grep -q '^\[providers' config.local.toml 2>/dev/null; then
  ./.venv/bin/litreader models migrate
else
  # 你已验证可用的模型（写进你自己的 models.toml，可随时用 litreader models set 修改）
  ./.venv/bin/python - <<'PYEOF'
import re
s = open("models.example.toml", encoding="utf-8").read()
s = re.sub(r'model = ""(\s+# TEXT_MODEL)', r'model = "deepseek-flash"\1', s)
s = re.sub(r'model = ""(\s+# VISION_MODEL)', r'model = "MiniMax-M3"\1', s)
open("models.toml", "x", encoding="utf-8").write(s)
PYEOF
  echo "✅ 已生成 models.toml（主笔/交叉核对：DeepSeek，看图：MiniMax 中国站）"
fi
echo ""
echo "下一步：运行  ./.venv/bin/litreader doctor"
