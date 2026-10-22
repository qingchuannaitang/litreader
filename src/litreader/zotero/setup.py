"""One-click Zotero setup (一键设置), READ-ONLY.

Finds the Zotero data directory and checks the local API. Nothing in Zotero is ever written: prefs.js is only read, and
enabling the local API is left to the user (instructions below).

Verified against Zotero source (github.com/zotero/zotero, main, 2026-10-18):
  defaults/preferences/zotero.js: extensions.zotero.useDataDir=false, extensions.zotero.dataDir="",
    extensions.zotero.httpServer.enabled=true, extensions.zotero.httpServer.port=23119,
    extensions.zotero.httpServer.localAPI.enabled=false
  zh-CN preferences.ftl: preferences-advanced-data-dir “数据目录：”.
  preferences_advanced.xhtml: the checkbox data-l10n-id=preferences-advanced-enable-local-api binds
    extensions.zotero.httpServer.localAPI.enabled; zh-CN label “允许此计算机上的其他应用程序与 Zotero 通讯”.
  zotero.org/support/dev/web_api/v3/local_api: base URL http://localhost:23119/api/; requests return 403 Forbidden when
    the local API is not enabled.
Profiles: macOS ~/Library/Application Support/Zotero/Profiles/*/prefs.js; Windows %APPDATA%\\Zotero\\Zotero\\Profiles;
Linux ~/.zotero/zotero/*/prefs.js. Default data dir when useDataDir is false: ~/Zotero.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENABLE_STEPS = [
    "打开 Zotero（Zotero 7 或更新版本）。",
    "macOS：菜单栏 Zotero → 设置…（Windows：编辑 → 设置）。",
    "点左侧“高级”（Advanced）。",
    "在“高级”页面里勾选「允许此计算机上的其他应用程序与 Zotero 通讯」"
    "（英文界面：Allow other applications on this computer to communicate with Zotero）。",
    "勾选后下方会显示“可用于 http://localhost:23119/api/”；然后回到 litreader 重新检测。",
]
NOT_RUNNING_STEPS = [
    "先打开 Zotero，并保持它在运行（本地接口只在 Zotero 打开时可用）。",
    "若 Zotero 已打开仍连不上：设置 → 高级 → 设置编辑器（Config Editor），确认 extensions.zotero.httpServer.enabled 为 true、"
    "extensions.zotero.httpServer.port 为 23119（只看不改也可以，把看到的值告诉我们）。",
]

_PREF = re.compile(r'^\s*user_pref\(\s*"([^"]+)"\s*,\s*(.+?)\s*\)\s*;\s*$', re.M)


def parse_prefs(text: str) -> dict:
    """user_pref("k", v); lines -> {k: str|bool|int}. JS string escapes \\\\ and \\" are undone."""
    out = {}
    for k, v in _PREF.findall(text or ""):
        if v in ("true", "false"):
            out[k] = v == "true"
        elif re.fullmatch(r"-?\d+", v):
            out[k] = int(v)
        elif len(v) >= 2 and v[0] == v[-1] == '"':
            out[k] = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return out


def profile_roots(platform: str | None = None, home: Path | None = None, env: dict | None = None) -> list[Path]:
    platform, home, env = platform or sys.platform, Path(home or Path.home()), env if env is not None else os.environ
    if platform == "darwin":
        return [home / "Library" / "Application Support" / "Zotero" / "Profiles"]
    if platform.startswith("win"):
        base = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        return [base / "Zotero" / "Zotero" / "Profiles"]
    return [home / ".zotero" / "zotero"]


def find_prefs(roots: list[Path]) -> list[Path]:
    """All prefs.js under the profile roots, most recently modified first (the profile Zotero used last)."""
    found = []
    for r in roots:
        if r.is_dir():
            found += [p for p in r.glob("*/prefs.js") if p.is_file()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def check_data_dir(d: Path) -> dict:
    return {"zotero.sqlite": (d / "zotero.sqlite").is_file(), "storage/": (d / "storage").is_dir()}


def detect(platform: str | None = None, home: Path | None = None, env: dict | None = None) -> dict:
    home = Path(home or Path.home())
    prefs = find_prefs(profile_roots(platform, home, env))
    p = parse_prefs(prefs[0].read_text("utf-8", errors="replace")) if prefs else {}
    if p.get("extensions.zotero.useDataDir") and p.get("extensions.zotero.dataDir"):
        data_dir, source = Path(str(p["extensions.zotero.dataDir"])).expanduser(), "prefs.js（自定义数据目录）"
    else:
        data_dir, source = home / "Zotero", ("prefs.js（使用默认位置）" if prefs else "默认位置（未找到 Zotero 配置文件）")
    checks = check_data_dir(data_dir)
    port = p.get("extensions.zotero.httpServer.port")
    return {"prefs": str(prefs[0]) if prefs else None, "profiles": len(prefs), "data_dir": data_dir, "source": source,
            "checks": checks, "valid": all(checks.values()),
            "port": port if isinstance(port, int) and 0 < port < 65536 else 23119,
            "http_server_pref": p.get("extensions.zotero.httpServer.enabled"),
            "local_api_pref": p.get("extensions.zotero.httpServer.localAPI.enabled")}


def probe(port: int = 23119, opener=None, timeout: float = 3.0) -> dict:
    """GET http://localhost:<port>/api/ : 200 = local API on; 403 = Zotero running, local API off; refused = not running."""
    url = f"http://localhost:{port}/api/"
    op = opener or (lambda req, t: urllib.request.urlopen(req, timeout=t))
    try:
        with op(urllib.request.Request(url, headers={"Zotero-API-Version": "3"}), timeout) as r:
            return {"status": "OK", "url": url, "http": getattr(r, "status", 200),
                    "api_version": (r.headers.get("Zotero-API-Version") if getattr(r, "headers", None) else None)}
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return {"status": "DISABLED", "url": url, "http": 403}
        return {"status": "ERROR", "url": url, "http": e.code}
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        return {"status": "NOT_RUNNING", "url": url, "http": None, "error": type(e).__name__}


def report(d: dict, pr: dict) -> list[str]:
    ok = lambda b: "✅" if b else "❌"
    L = [f"{ok(d['valid'])} Zotero 数据目录：{d['data_dir']}（来源：{d['source']}）"]
    L += [f"   {ok(v)} {k}" for k, v in d["checks"].items()]
    if d["profiles"] > 1:
        L.append(f"   ℹ️ 找到 {d['profiles']} 个 Zotero 配置，用的是最近修改的：{d['prefs']}")
    if not d["valid"]:
        L.append("   → 没找到 zotero.sqlite 或 storage/：请在 Zotero 设置 → 高级 查看“数据目录：”一行，"
                 "再用 litreader setup zotero --data-dir 〈路径〉 指定")
    if pr["status"] == "OK":
        L.append(f"✅ 本地接口可用：{pr['url']}（只读）")
    elif pr["status"] == "DISABLED":
        L.append(f"❌ Zotero 正在运行，但本地接口未开启（{pr['url']} 返回 403）。请按以下步骤开启（litreader 不会替你改 Zotero 设置）：")
        L += [f"   {i}. {s}" for i, s in enumerate(ENABLE_STEPS, 1)]
    elif pr["status"] == "NOT_RUNNING":
        L.append(f"❌ 连不上 {pr['url']}：")
        L += [f"   {i}. {s}" for i, s in enumerate(NOT_RUNNING_STEPS, 1)]
        if d.get("local_api_pref") is False or d.get("local_api_pref") is None:
            L.append("   另外：Zotero 配置里本地接口尚未开启，打开 Zotero 后还需：")
            L += [f"      {i}. {s}" for i, s in enumerate(ENABLE_STEPS[1:], 1)]
    else:
        L.append(f"⚠️ 本地接口返回 HTTP {pr.get('http')}：{pr['url']}")
    return L


def config_updates(cfg_text: str, data_dir: Path, api_base: str) -> tuple[str, list[str]]:
    """Set [zotero] data_dir / api_base in config.local.toml text, other lines untouched. Returns (new_text, changes).
    Paths are compared normalised ("~/Zotero" == "/Users/<you>/Zotero"), URLs without a trailing slash: an
    equivalent spelling is not a change."""
    from ..configedit import norm_url, same_path, set_keys
    return set_keys(cfg_text, "zotero", {"data_dir": str(data_dir).replace("\\", "/"), "api_base": api_base},
                    {"data_dir": same_path, "api_base": lambda a, b: norm_url(a) == norm_url(b)})


def save_config(cfg_path: Path, new_text: str) -> Path:
    """Back up config.local.toml as .bak-<time>, validate the new TOML, then replace atomically. Returns the backup."""
    import shutil
    import tomllib
    from datetime import datetime
    cfg_path = Path(cfg_path)
    tomllib.loads(new_text)   # never write an unreadable config
    bak = cfg_path.with_name(cfg_path.name + f".bak-{datetime.now().strftime('%Y%m%dT%H%M%S')}")
    shutil.copy2(cfg_path, bak)
    tmp = cfg_path.with_name(cfg_path.name + ".tmp")
    tmp.write_text(new_text, "utf-8")
    tmp.replace(cfg_path)
    return bak


def check(data_dir: Path | None = None, opener=None, detect_fn=None) -> tuple[dict, dict]:
    """detect (+ optional user-chosen data dir) and probe the local API — the read-only part of `setup zotero`."""
    d = (detect_fn or detect)()
    if data_dir:
        dd = Path(data_dir).expanduser()
        d.update(data_dir=dd, source="你指定的路径", checks=check_data_dir(dd))
        d["valid"] = all(d["checks"].values())
    return d, probe(d["port"], opener=opener)
