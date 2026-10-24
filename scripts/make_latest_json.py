#!/usr/bin/env python3
"""Write latest.json for the update check (schema: docs/RELEASE.md).

    python scripts/make_latest_json.py --download-url https://…/litreader-0.6.0.zip --notes "…" [--qq-group 1126184965] [-o latest.json]

The version is read from src/litreader/__init__.py unless --version is given."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def current_version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "src/litreader/__init__.py").read_text("utf-8"))
    return m.group(1)


def build(version: str, notes: str, download_url: str, qq_group: str, downloads: dict | None = None) -> dict:
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        raise SystemExit(f"版本号格式不对：{version}")
    if download_url and not download_url.startswith("https://"):
        raise SystemExit("download_url 必须是 https:// 地址")
    if qq_group and not re.fullmatch(r"\d{5,12}", qq_group):
        raise SystemExit("qq_group 只能是数字")
    d = {"version": version, "notes": notes, "download_url": download_url, "qq_group": qq_group}
    downloads = {k: v for k, v in (downloads or {}).items() if v}
    for k, v in downloads.items():
        if not v.startswith("https://"):
            raise SystemExit(f"downloads.{k} 必须是 https:// 地址")
    if downloads:
        d["downloads"] = downloads   # W6: per-platform; download_url stays for apps <= 1.0.3
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--download-url", default="")
    ap.add_argument("--qq-group", default="1126184965")
    ap.add_argument("--mac-url", default="")
    ap.add_argument("--win-url", default="")
    ap.add_argument("-o", "--output", default="latest.json")
    a = ap.parse_args(argv)
    d = build(a.version or current_version(), a.notes, a.download_url, a.qq_group,
              {"mac": a.mac_url, "win": a.win_url})
    Path(a.output).write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"wrote {a.output}: v{d['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
