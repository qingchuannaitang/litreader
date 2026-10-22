import os

import pytest

from litreader.errors import AlreadyExists, HashMismatch, SandboxViolation
from litreader.hashing import sha256_bytes, sha256_file
from litreader.permissions import Sandbox
from litreader.vault.writer import VaultWriter


def test_exclusive_create_and_verify(vault):
    w = VaultWriter(Sandbox(vault))
    r = w.create_exclusive("t/a.md", b"hello")
    assert r.sha256 == sha256_bytes(b"hello") == sha256_file(vault / "t/a.md")


def test_exclusive_create_refuses_existing_bytes_unchanged(vault):
    (vault / "a.md").write_bytes(b"original")
    w = VaultWriter(Sandbox(vault))
    with pytest.raises(AlreadyExists):
        w.create_exclusive("a.md", b"new")
    assert (vault / "a.md").read_bytes() == b"original"
    assert w.write_count == 0


def test_replace_requires_allowlist(vault):
    (vault / "a.md").write_bytes(b"x")
    with pytest.raises(SandboxViolation):
        VaultWriter(Sandbox(vault)).replace_atomic("a.md", b"y", sha256_bytes(b"x"))
    assert (vault / "a.md").read_bytes() == b"x"


def test_replace_compare_hash_mismatch_stops(vault):
    (vault / "i.md").write_bytes(b"user edited")
    w = VaultWriter(Sandbox(vault), {"i.md"})
    with pytest.raises(HashMismatch):
        w.replace_atomic("i.md", b"new", sha256_bytes(b"what we read earlier"))
    assert (vault / "i.md").read_bytes() == b"user edited"
    assert not [p for p in os.listdir(vault) if p.startswith(".lit-tmp-")]


def test_replace_ok(vault):
    (vault / "i.md").write_bytes(b"old")
    r = VaultWriter(Sandbox(vault), {"i.md"}).replace_atomic("i.md", b"new", sha256_bytes(b"old"))
    assert (vault / "i.md").read_bytes() == b"new" and r.op == "replace"


def test_mkdirs_refuses_symlinked_parent_created_late(vault, tmp_path):
    out = tmp_path / "out"; out.mkdir()
    os.symlink(out, vault / "evil")
    with pytest.raises(SandboxViolation):
        VaultWriter(Sandbox(vault)).create_exclusive("evil/x.md", b"x")
    assert not (out / "x.md").exists()
