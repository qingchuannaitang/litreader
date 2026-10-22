"""Safe writer (R8): exclusive create, compare-hash atomic replace, post-write verify.

There is deliberately NO 'write if exists then overwrite' code path.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import AlreadyExists, HashMismatch, SandboxViolation
from ..hashing import sha256_bytes, sha256_file
from ..permissions import Sandbox


@dataclass(frozen=True)
class WriteResult:
    rel_path: str
    sha256: str
    op: str  # "create" | "replace"


class VaultWriter:
    def __init__(self, sandbox: Sandbox, replace_allowlist: set[str] | None = None):
        self.sb = sandbox
        # Relative paths that may be replaced (e.g. the single overview file).
        self.replace_allowlist = set(replace_allowlist or ())
        self.write_count = 0

    def _mkdirs(self, path: Path) -> None:
        # Create parents one level at a time, re-checking for symlinks.
        rel_parent = path.parent.relative_to(self.sb.root)
        cur = self.sb.root
        for p in rel_parent.parts:
            cur = cur / p
            if os.path.islink(cur):
                raise SandboxViolation(f"symlink in path: {cur}")
            if not cur.exists():
                os.mkdir(cur)

    def create_exclusive(self, rel: str, data: bytes) -> WriteResult:
        path = self.sb.resolve(rel)
        self._mkdirs(path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags, 0o644)
        except FileExistsError as e:
            raise AlreadyExists(rel) from e
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            # We created it; remove the partial file so no half-artifact remains.
            os.unlink(path)
            raise
        self.write_count += 1
        return WriteResult(rel, self._verify(path, data), "create")

    def replace_atomic(self, rel: str, data: bytes, expected_old_sha: str) -> WriteResult:
        if rel not in self.replace_allowlist:
            raise SandboxViolation(f"replace not authorized for: {rel}")
        path = self.sb.resolve(rel)
        if not path.is_file():
            raise HashMismatch(f"replace target missing: {rel}")
        if sha256_file(path) != expected_old_sha:
            raise HashMismatch(f"compare-hash failed (modified since read): {rel}")
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".lit-tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if sha256_file(path) != expected_old_sha:  # re-check just before swap
                raise HashMismatch(f"modified during write: {rel}")
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self.write_count += 1
        return WriteResult(rel, self._verify(path, data), "replace")

    @staticmethod
    def _verify(path: Path, data: bytes) -> str:
        expected = sha256_bytes(data)
        actual = sha256_file(path)
        if actual != expected:
            raise HashMismatch(f"post-write verify failed: {path}")
        return actual
