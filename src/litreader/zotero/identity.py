"""PaperIdentity construction + translation-version detection."""
from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import Stop
from ..hashing import sha256_file
from ..publish.store import PaperIdentity
from .client import Attachment, Candidate

_ZH_PATTERNS = [r"[_\-.\s](zh|cn|chs|zh[-_]?cn)(?=\.pdf$|[_\-.\s])", r"中文|中译|译文|翻译|译版", r"translat"]


@dataclass(frozen=True)
class SourceVersion:
    flag: str  # ORIGINAL_UNVERIFIED | TRANSLATION_SUSPECTED
    reasons: tuple[str, ...]


def detect_source_version(filename: str | None, cjk_ratio: float | None = None) -> SourceVersion:
    """Heuristic only: never claims 'verified original'. cjk_ratio from parsed text (optional)."""
    reasons = []
    fn = (filename or "").lower()
    for p in _ZH_PATTERNS:
        if re.search(p, fn, flags=re.I):
            reasons.append("文件名含中文/译本标记")
            break
    if cjk_ratio is not None and cjk_ratio >= 0.3:
        reasons.append(f"解析正文的中文字符占比 {cjk_ratio:.0%}")
    return SourceVersion("TRANSLATION_SUSPECTED" if reasons else "ORIGINAL_UNVERIFIED", tuple(reasons))


def isolate_copy(pdf: Path, work_dir: Path) -> tuple[Path, str]:
    """Copy the PDF to an isolated work dir; verify the copy equals the source. Source is never opened for write."""
    if not pdf.is_file():
        raise Stop(f"PDF not found: {pdf}")
    src_sha = sha256_file(pdf)
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=work_dir, suffix=".pdf")
    import os; os.close(fd)
    shutil.copyfile(pdf, tmp)
    if sha256_file(Path(tmp)) != src_sha or sha256_file(pdf) != src_sha:
        raise Stop("isolated copy hash mismatch")
    return Path(tmp), src_sha


def build_identity(library: str, item: Candidate, att: Attachment, pdf_sha: str) -> PaperIdentity:
    if att.parent_key != item.parent_key:
        raise Stop("attachment/parent mismatch")
    return PaperIdentity(library=library, parent_key=item.parent_key, attachment_key=att.key,
                         pdf_sha256=pdf_sha, doi=item.doi)
