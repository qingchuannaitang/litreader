#!/usr/bin/env python3
"""Fail if a release package (or the tracked files) could carry an API key.

  python scripts/check_no_secrets.py                 # scan git-tracked files
  python scripts/check_no_secrets.py dist/litreader.zip

Checks: (1) forbidden files (local configs, .env, calibration.json, receipts, logs, caches, job folders);
(2) key-like strings (sk-…, JWT eyJ…, Bearer …, AWS/Google/GitHub/Anthropic style keys, key = "long literal");
(3) the actual values of key environment variables, if set on this machine (compared, never printed).
Only file names, line numbers and pattern names are printed — never a matched value. Exit 1 on any finding.
Allow-listed: obvious test fakes used by the unit tests (sk-SECRET-…, sk-abcdef1234567890).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_ENV = ("MINERU_API_TOKEN", "MINERU_TOKEN", "PADDLE_API_KEY", "PADDLE_TOKEN", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY",
           "MINIMAX_INTL_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")
PATTERNS = {
    "sk- key": re.compile(rb"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    "JWT": re.compile(rb"\beyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}"),
    "Bearer token": re.compile(rb"Bearer\s+[A-Za-z0-9._\-]{20,}"),
    "Google API key": re.compile(rb"\bAIza[0-9A-Za-z_\-]{30,}"),
    "AWS key id": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "key literal": re.compile(rb"(?i)\b(?:api_?key|token|secret|password)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-./+]{20,}[\"']"),
}
ALLOW = re.compile(rb"sk-SECRET-[A-Z0-9\-]+|sk-abcdef1234567890")
FORBIDDEN = re.compile(r"(^|/)(\.env(\..*)?|config\.local\.toml(\.bak-.*)?|models\.toml|calibration\.json|"
                       r"receipt-[^/]*\.json|[^/]*\.log|\.spike_data/.*|\.venv/.*|__pycache__/.*|\.pytest_cache/.*|"
                       r"jobs/.*|title_cache[^/]*\.json)$")


def env_values() -> dict[str, bytes]:
    return {n: os.environ[n].encode() for n in KEY_ENV if len(os.environ.get(n) or "") >= 8}


def scan_blob(name: str, data: bytes, secrets: dict[str, bytes]) -> list[str]:
    out = []
    if FORBIDDEN.search(name):
        out.append(f"{name}: forbidden file in package")
    for n, v in secrets.items():
        if v in data:
            out.append(f"{name}: contains the value of ${n}")
    clean = ALLOW.sub(b"", data)
    for label, rx in PATTERNS.items():
        for m in rx.finditer(clean):
            line = clean[:m.start()].count(b"\n") + 1
            out.append(f"{name}:{line}: {label}")
    return out


def scan_files(items) -> list[str]:
    secrets = env_values()
    found = []
    for name, data in items:
        found += scan_blob(name, data, secrets)
    return found


def tracked() -> list[tuple[str, bytes]]:
    names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    return [(n.decode(), (ROOT / n.decode()).read_bytes()) for n in names if n and (ROOT / n.decode()).is_file()]


def zip_items(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i)) for i in z.namelist() if not i.endswith("/")]
        items.append(("<zip comment>", z.comment))
    return items


def main(argv: list[str]) -> int:
    items = zip_items(Path(argv[0])) if argv else tracked()
    found = scan_files(items)
    where = argv[0] if argv else "git-tracked files"
    if found:
        print(f"❌ {len(found)} finding(s) in {where} (values not shown):")
        for f in found:
            print("   " + f)
        return 1
    print(f"✅ no keys or local files in {where} ({len(items)} files checked; {len(env_values())} key env values compared)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
