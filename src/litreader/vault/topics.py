"""Topic folder choice under 论文库/: reuse the most similar existing folder, or propose a new one (user confirms)."""
from __future__ import annotations

import json
from pathlib import Path

from ..llm.client import AllProvidersFailed, run_chain
from ..llm.jsonparse import loads_lenient
from . import naming


def list_topics(papers_root: Path) -> list[str]:
    """Existing topic folders: direct subdirectories, excluding system folders (_阅读版本/_证据档案/_图表/…, ., _)."""
    if not papers_root.is_dir():
        return []
    return sorted(p.name for p in papers_root.iterdir()
                  if p.is_dir() and not p.is_symlink() and not p.name.startswith(("_", ".")))


PROMPT = """你为论文选择 Obsidian 主题文件夹。已有文件夹列表给出；若有主题足够相近的已有文件夹，必须复用（choice=existing，folder 原样照抄列表中的名字）；
只有都不相近时才提出新名字（choice=new，2–12 个汉字的简洁主题名，不含标点和斜杠）。
拿不准时 confident=false，并在 alternatives 里再给最多 2 个候选（已有文件夹原样照抄，或新名字）。只输出 JSON：
{"choice": "existing"|"new", "folder": str, "reason": 中文≤40字, "confident": true|false, "alternatives": [str]}"""

MAX_NAME = 40
RESERVED = {"论文库", "模板库", "课题档案"}


def clean_name(raw: str, existing: list[str]) -> tuple[str | None, str]:
    """User/model folder name -> (name, problem). Same sanitizer as file names; a name matching an existing folder up to
    case (macOS file systems ignore case) is that existing folder."""
    if (raw or "").strip().startswith(("_", ".")):
        return None, "不能以 _ 或 . 开头（这些是系统文件夹）"
    s = naming.sanitize((raw or "").replace("/", " ").replace("\\", " ").strip())
    if not s or not s.stem.strip():
        return None, "名称为空或只含非法字符"
    name = s.stem.strip()
    if name.startswith(("_", ".")):
        return None, "不能以 _ 或 . 开头（这些是系统文件夹）"
    if len(name) > MAX_NAME:
        return None, f"名称过长（最多 {MAX_NAME} 个字符）"
    if name in RESERVED:
        return None, "这是保留名称"
    for e in existing:
        if e.casefold() == name.casefold():
            return e, ""
    return name, ""


def suggest(existing: list[str], title: str, summary: str, keywords: list[str], chain, transport, env) -> dict:
    """Returns {choice, folder, reason, usage, provider, status}. Invalid answers fall back to a safe proposal."""
    info: dict = {"status": "OK"}
    user = json.dumps({"已有文件夹": existing, "论文题名": title, "要点": summary[:600], "关键词": keywords[:12]},
                      ensure_ascii=False)
    try:
        r = run_chain(chain, [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}], transport, env)
        info.update(usage=r.usage, provider=r.provider_used, model=r.model_used)
        d = loads_lenient(r.text)
        choice, folder, reason = d.get("choice"), str(d.get("folder") or "").strip(), str(d.get("reason") or "")
        info["confident"] = d.get("confident") is not False
        alts = []
        for x in (d.get("alternatives") or [])[:2] if isinstance(d.get("alternatives"), list) else []:
            n, _ = clean_name(str(x), existing)
            if n and n not in alts:
                alts.append(n)
        info["alternatives"] = alts
    except (AllProvidersFailed, ValueError, AttributeError) as e:
        info.update(status=f"LLM_FAILED: {type(e).__name__}", choice="new", folder="未分类", reason="模型未给出有效建议")
        return info
    if choice == "existing" and folder in existing:
        info.update(choice="existing", folder=folder, reason=reason)
        info["alternatives"] = [x for x in info.get("alternatives", []) if x != folder]
        return info
    if choice == "existing":   # named a folder that does not exist -> treat as a new proposal, user must confirm
        info["status"] = "EXISTING_NOT_FOUND"
    s = naming.sanitize(folder.replace("/", " ").replace("\\", " "))
    name = s.stem if s else "未分类"
    if name in existing:
        info.update(choice="existing", folder=name, reason=reason)
    else:
        info.update(choice="new", folder=name, reason=reason)
    info["alternatives"] = [x for x in info.get("alternatives", []) if x != name]
    return info
