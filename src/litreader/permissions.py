"""Path sandbox (R8).

A Sandbox wraps one permitted root directory. Callers pass *relative* paths;
the sandbox rejects absolute paths, '..' components, NUL bytes, any symlink in
the chain (inside root, including the root itself), and existing targets that
are hard-linked (st_nlink > 1) or not regular files.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import SandboxViolation


class Sandbox:
    def __init__(self, root: Path | str):
        root = Path(root)
        if root.is_symlink():
            raise SandboxViolation(f"root is a symlink: {root}")
        if not root.is_dir():
            raise SandboxViolation(f"root is not an existing directory: {root}")
        self.root = Path(os.path.realpath(root))

    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str) or rel == "" or "\x00" in rel:
            raise SandboxViolation(f"invalid relative path: {rel!r}")
        # Reject absolute paths in both POSIX and Windows syntax (drive, UNC).
        if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute() \
                or PureWindowsPath(rel).drive or rel.startswith(("\\", "/")):
            raise SandboxViolation(f"absolute path not allowed: {rel!r}")
        parts = tuple(rel.replace("\\", "/").split("/"))
        if any(p in ("..", ".", "") for p in parts):
            raise SandboxViolation(f"traversal component not allowed: {rel!r}")
        cur = self.root
        for p in parts:
            cur = cur / p
            if os.path.lexists(cur) and os.path.islink(cur):
                raise SandboxViolation(f"symlink in path: {cur}")
        real_parent = Path(os.path.realpath(cur.parent))
        if real_parent != self.root and self.root not in real_parent.parents:
            raise SandboxViolation(f"escapes root: {rel!r}")
        if os.path.lexists(cur):
            st = os.lstat(cur)
            if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
                raise SandboxViolation(f"hard-linked file refused: {cur}")
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise SandboxViolation(f"special file refused: {cur}")
        return cur
