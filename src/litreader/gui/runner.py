"""What one GUI run does — Qt-free so it is unit-testable. Same rules as `litreader "<指令>"` in the terminal:
one paper per run, dry-run writes only, Zotero read-only, models.toml / calibration.json shared with the CLI."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import appconfig, realrun
from ..events import BusUI


def run_text(text: str, ui: BusUI, config: str | None = None, cfg=None, **kw) -> dict:
    """Run one natural-language command through the event bus. Returns {"kind": "paper", "receipt": …} or
    {"kind": "other", "code": int} for template-refresh / project commands (they never run a paper)."""
    from ..cli import REFRESH_RE
    if re.search(REFRESH_RE, text):
        from types import SimpleNamespace
        from ..cli_templates import cmd_templates
        return {"kind": "other", "code": cmd_templates(SimpleNamespace(action="refresh", config=config, ai=False))}
    cfg = cfg or appconfig.load(config)
    from ..cli_project import nl_match, run_nl
    if nl_match(text):
        return {"kind": "other", "code": run_nl(cfg, text, ui, transport=kw.get("llm_tx"), env=kw.get("env"))}
    return {"kind": "paper", "receipt": realrun.run(cfg, text, ui, **kw)}


STATUS = {"DRY_RUN_COMPLETE": ("完成", "ok"), "STOPPED": ("已停止", "stop"), "CANCELLED": ("已取消", "gray")}
WHERE = {"zotero": "选论文时", "project": "关联课题时", "estimate": "估算后", "parse": "解析时", "template": "选模板时",
         "vision": "精读中", "writer": "精读中", "judge": "精读中", "lens": "精读中", "author": "作者核对时",
         "topic": "选文件夹时", "write": "写入前"}
_FM_KEYS = ("title_zh", "title_en", "authors", "year", "journal", "parent_item_key")
_FM_ZH = {"中文标题": "title_zh", "英文标题": "title_en", "作者": "authors", "年份": "year", "期刊": "journal"}


def _front_matter(note: str | None) -> dict:
    """Older receipts have no `paper` block: read the few metadata keys from the note's YAML front matter."""
    out: dict = {}
    try:
        head = Path(note).read_text("utf-8")[:6000] if note else ""
    except OSError:
        return out
    m = FM_RE.match(head)
    for line in (m.group(0).splitlines() if m else []):
        k, _, v = line.partition(":")
        k = _FM_ZH.get(k.strip(), k.strip())   # G10-7 Chinese names (and `  parent_item_key:` inside litreader:)
        if k in _FM_KEYS:
            v = v.strip().strip('"')
            if v and not v.startswith("UNKNOWN") and k not in out:
                out[k] = v
    return out


def paper_row(r: dict) -> dict:
    """Display fields of one receipt for 最近精读: 论文 (bold title + grey meta line) / 状态 / 文件夹 / 日期 / 完整度."""
    p = dict(r.get("paper") or {})
    fm = _front_matter(r.get("note")) if not p.get("title_zh") else {}
    p = {k: v for k, v in p.items() if v not in ("UNKNOWN", None)}
    fm = {k: v for k, v in fm.items() if v not in ("UNKNOWN", None, "")}
    title = p.get("title_zh") or fm.get("title_zh") or p.get("title_en") or fm.get("title_en")
    if not title and r.get("note"):
        title = Path(r["note"]).stem.split("——")[0]
    title = title or (r.get("query") and f"「{r['query']}」") or "（未知论文）"
    author = p.get("author_last") or ""
    if not author and fm.get("authors"):
        first = re.split(r"[,，;；]| 等", fm["authors"])[0].strip()
        author = first.split()[-1] if " " in first else first
    key = p.get("item_key") or fm.get("parent_item_key") or ((r.get("identity") or {}).get("parent_key"))
    meta = " · ".join(x for x in (" ".join(x for x in (author, p.get("year") or fm.get("year") or "") if x),
                                    p.get("journal") or fm.get("journal") or "", f"条目 {key}" if key else "") if x)
    st = r.get("status") or ""
    text, kind = STATUS.get(st, (st or "?", "gray"))
    el = (r.get("extraction") or {}).get("level")
    if st == "STOPPED" and el in ("E0", "E1"):
        text = f"已停止：{el}"
    elif st == "CANCELLED" and WHERE.get(r.get("stopped_at") or ""):
        text = f"已取消（{WHERE[r['stopped_at']]}）"
    return {"title": title, "meta": meta, "status": text, "status_kind": kind,
            "topic": (r.get("topic") or {}).get("folder") if isinstance(r.get("topic"), dict) else r.get("topic"),
            "date": (r.get("finished") or r.get("started") or "")[:10], "e_level": el,
            "e_kind": "stop" if el in ("E0", "E1") else "acc"}


def recent_receipts(data_dir: Path, limit: int = 8) -> list[dict]:
    """Recent runs, newest first, from receipt-*.json in the job folders (finished, stopped and cancelled; a receipt
    never contains a key or paper text)."""
    out = []
    jobs = Path(data_dir) / "jobs"
    if not jobs.is_dir():
        return out
    for p in sorted(jobs.glob("*/receipt-*.json"), key=lambda p: p.name.split("receipt-", 1)[1], reverse=True):
        try:
            r = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(r, dict) or r.get("status") not in STATUS:
            continue
        row = {"receipt": str(p), "status_code": r["status"], "note": r.get("note"), "evidence": r.get("evidence"),
               "query": r.get("query"), "topic": (r.get("topic") or {}).get("folder"), "finished": r.get("finished"),
               "e_level": (r.get("extraction") or {}).get("level"), "actual": r.get("actual") or {},
               "estimate": r.get("estimate") or {}, "paper": r.get("paper") or {}, "reason": r.get("reason"),
               "identity": r.get("identity") or {}, "stopped_at": r.get("stopped_at")}
        row["row"] = paper_row(r)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def paper_key(r: dict) -> str:
    """One paper = one Zotero parent item (fallback: note path, then the query)."""
    p = r.get("paper") or {}
    k = p.get("item_key") or (r.get("identity") or {}).get("parent_key") or (r.get("row") or {}).get("item_key")
    return f"item:{k}" if k else f"note:{r.get('note')}" if r.get("note") else f"q:{r.get('query')}"


def dedup_papers(rows: list[dict], exclude: str | None = None) -> list[dict]:
    """Newest-first rows -> one row per paper (the latest run wins); optionally drop one paper (the just-read one)."""
    seen, out = set(), []
    for r in rows:
        k = paper_key(r)
        if k in seen or (exclude and k == exclude):
            continue
        seen.add(k)
        out.append(r)
    return out


FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)


def preview_markdown(md: str, max_chars: int = 20000) -> str:
    """Simple preview only (decision 5): drop the YAML front matter and Obsidian-only syntax that Qt's Markdown
    renderer cannot show; the full rendering is in Obsidian."""
    s = FM_RE.sub("", md, count=1)
    s = re.sub(r"!\[\[([^\]|]+)(\|[^\]]*)?\]\]", lambda m: f"〔图：{Path(m.group(1)).name}〕", s)
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", lambda m: Path(m.group(1)).name, s)
    s = re.sub(r"^(>\s*)\[!(\w+)\][+-]?\s*", r"\1**\2** ", s, flags=re.M)
    s = re.sub(r"%%.*?%%", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n\n……（预览到此为止，完整内容请在 Obsidian 中查看）"
    return s
