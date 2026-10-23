"""Minimal, comment-preserving edits of config.local.toml (G6): set `key = "value"` lines inside one [section],
everything else untouched. Values that are already equal (paths compared after expanduser + resolve, so "~/Zotero"
and "/Users/<you>/Zotero" count as the same) are left exactly as written and reported as no change."""
from __future__ import annotations

import os
import re
from pathlib import Path


def norm_path(p: str | Path) -> str:
    """Canonical form for comparing two spellings of one path (never used to rewrite the file)."""
    s = str(p).strip()
    if not s:
        return ""
    try:
        r = str(Path(s).expanduser().resolve())
    except (OSError, RuntimeError):
        r = str(Path(s).expanduser())
    return os.path.normcase(r)   # Windows: case-insensitive, "/" == "\\"


def same_path(a: str | Path, b: str | Path) -> bool:
    return norm_path(a) == norm_path(b)


def norm_url(u: str) -> str:
    return (u or "").strip().rstrip("/").lower()


def _esc(v: str) -> str:
    """Value for a TOML basic string. Backslashes become "/" (these are paths; Windows accepts "/", and a raw
    "C:\\Users" would be read by TOML as the escape \\U and break the whole file). Quotes and control characters
    are escaped so the written file always parses."""
    s = str(v).replace("\\", "/")
    out = []
    for c in s:
        if c == '"':
            out.append('\\"')
        elif ord(c) < 0x20 or c == "\x7f":
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    return "".join(out)


def set_keys(cfg_text: str, section: str, want: dict[str, str], equal: dict | None = None) -> tuple[str, list[str]]:
    """Set string keys in [section]. equal: key -> fn(old, new) deciding "already the same" (default: ==).
    Returns (new_text, human-readable changes). No change -> the text is returned byte for byte."""
    equal = equal or {}
    lines = cfg_text.splitlines(keepends=True)
    sec, start, end = None, None, len(lines)
    for i, l in enumerate(lines):
        m = re.match(r"^\s*\[([^\]]+)\]\s*(#.*)?$", l)
        if m:
            if sec == section and end == len(lines):
                end = i
            sec = m.group(1).strip()
            if sec == section:
                start = i
    if start is None:
        new = cfg_text.rstrip("\n") + f"\n\n[{section}]\n" + "".join(f'{k} = "{_esc(v)}"\n' for k, v in want.items())
        return new, [f'新增 [{section}] {k} = "{v}"' for k, v in want.items()]
    changes, seen = [], set()
    keys = "|".join(re.escape(k) for k in want)
    for i in range(start + 1, end):
        m = re.match(rf'^(\s*)({keys})\s*=\s*"([^"]*)"(.*)$', lines[i].rstrip("\n"))
        if m:
            k, old = m.group(2), m.group(3)
            seen.add(k)
            same = equal.get(k, lambda a, b: a == b)
            if not same(old, want[k]):
                changes.append(f'[{section}] {k}: "{old}" → "{want[k]}"')
                lines[i] = f'{m.group(1)}{k} = "{_esc(want[k])}"{m.group(4)}\n'
    add = [f'{k} = "{_esc(v)}"\n' for k, v in want.items() if k not in seen]
    if add:
        lines[start + 1:start + 1] = add
        changes += [f"新增 [{section}] {a.strip()}" for a in add]
    return ("".join(lines), changes) if changes else (cfg_text, [])


def vault_updates(cfg_text: str, root: str | Path, output_dir: str | None = None,
                  current_output: str | None = None) -> tuple[str, list[str]]:
    """G10-1: also sets [vault] output_dir when it differs from the folder currently in effect (current_output, which
    may come from an old dry_run_dir line). An unchanged folder never adds a line."""
    want, eq = {"root": str(root)}, {"root": same_path}
    if output_dir is not None and output_dir != (current_output or ""):
        want["output_dir"] = output_dir
    return set_keys(cfg_text, "vault", want, eq)


def rel_in_vault(vault: str | Path, folder: str | Path) -> str | None:
    """A folder picked with 选择… -> its path relative to the vault (posix), or None when it is not inside the vault."""
    try:
        r = Path(norm_path(folder)).relative_to(norm_path(vault))
    except ValueError:
        return None
    s = r.as_posix()
    return None if s in ("", ".") else s


def obsidian_config_paths(home: str | Path | None = None) -> list[Path]:
    """Where Obsidian keeps its list of known vaults (macOS first; Linux/Windows for completeness)."""
    h = Path(home) if home else Path.home()
    return [h / "Library" / "Application Support" / "obsidian" / "obsidian.json",
            h / ".config" / "obsidian" / "obsidian.json",
            h / "AppData" / "Roaming" / "obsidian" / "obsidian.json"]


def detect_vaults(home: str | Path | None = None, files: list[Path] | None = None) -> list[dict]:
    """G7-7 read-only: Obsidian's obsidian.json -> known vaults, best first (currently open, then most recent ts).
    Only folders that still exist are returned. Never writes anything; any parse error -> []."""
    import json
    out: dict[str, dict] = {}
    for f in files if files is not None else obsidian_config_paths(home):
        try:
            data = json.loads(Path(f).read_text("utf-8"))
        except (OSError, ValueError):
            continue
        for vid, v in (data.get("vaults") or {}).items() if isinstance(data, dict) else []:
            if not isinstance(v, dict) or not v.get("path"):
                continue
            p = Path(str(v["path"])).expanduser()
            if not p.is_dir():
                continue
            ts = v.get("ts") if isinstance(v.get("ts"), (int, float)) else 0
            out[str(p)] = {"path": p, "ts": ts, "open": bool(v.get("open")), "name": p.name,
                           "is_vault": (p / ".obsidian").is_dir()}
    return sorted(out.values(), key=lambda d: (not d["open"], -d["ts"]))


def check_vault(root: str | Path, papers_dir: str = "论文库", dry_run_dir: str = "litreader") -> dict:
    """Read-only look at a folder the user picked as the Obsidian vault."""
    p = Path(str(root)).expanduser()
    return {"path": p, "exists": p.is_dir(), "is_vault": (p / ".obsidian").is_dir(),
            "papers": (p / papers_dir).is_dir(), "trial": (p / dry_run_dir).is_dir()}
