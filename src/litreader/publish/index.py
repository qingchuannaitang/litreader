"""Chinese overview index (R13). Built only from verified publication records."""
from __future__ import annotations

from ..hashing import sha256_file
from ..render.protected_zone import machine_sha
from ..permissions import Sandbox
from .state_machine import State
from .store import PublicationRecord

MANAGED_BEGIN = "<!-- LIT:INDEX:BEGIN 受管区，由程序维护 -->"
MANAGED_END = "<!-- LIT:INDEX:END -->"
INDEXABLE = {State.ASSETS_VERIFIED.value, State.INDEX_PENDING.value,
             State.INDEX_UPDATED.value, State.COMPLETE.value}


def verified_entries(records: list[PublicationRecord], sb: Sandbox) -> list[PublicationRecord]:
    """Keep only records whose saved note still matches its post-write machine hash."""
    out = []
    for r in records:
        if r.state not in INDEXABLE or not r.note_path:
            continue
        try:
            p = sb.resolve(r.note_path)
            if p.is_file() and machine_sha(p.read_text("utf-8")) == r.note_machine_sha:
                out.append(r)
        except Exception:
            continue  # unverifiable => not indexed (fail-closed)
    return out


def render_index(entries: list[PublicationRecord]) -> str:
    seen, lines = set(), []
    for r in sorted(entries, key=lambda r: r.identity["parent_key"]):
        k = (r.identity["library"], r.identity["parent_key"])
        if k in seen:  # dedupe by library + Parent Key
            continue
        seen.add(k)
        title = r.identity.get("title_display") or "UNKNOWN"
        link = r.note_path[:-3] if r.note_path.endswith(".md") else r.note_path
        lines.append(f"- [[{link}|{title}]]")
    body = "\n".join(lines)
    return (f"# 00-精读论文总览\n\n## 精读统计（真实已核验，按独立论文去重）\n\n共 {len(seen)} 篇\n\n"
            f"{MANAGED_BEGIN}\n{body}\n{MANAGED_END}\n")


def merge_into_existing(existing: str, fresh: str) -> str:
    """Replace only the managed region of an existing overview; keep user text outside it."""
    if existing.count(MANAGED_BEGIN) != 1 or existing.count(MANAGED_END) != 1:
        from ..errors import Stop
        raise Stop("overview managed-region markers missing/duplicated; refusing to merge")
    fb = fresh.index(MANAGED_BEGIN); fe = fresh.index(MANAGED_END) + len(MANAGED_END)
    eb = existing.index(MANAGED_BEGIN); ee = existing.index(MANAGED_END) + len(MANAGED_END)
    return existing[:eb] + fresh[fb:fe] + existing[ee:]
