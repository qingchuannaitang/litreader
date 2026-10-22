import os

import pytest

from litreader.errors import SandboxViolation
from litreader.permissions import Sandbox

BAD = ["../escape.md", "a/../../escape.md", "/etc/passwd", "C:\\x.md", "\\\\server\\share\\x.md",
       "a/./b.md", "", "a\x00b.md", "..", "a\\..\\..\\x.md"]


@pytest.mark.parametrize("rel", BAD)
def test_attack_paths_rejected(vault, rel):
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve(rel)


def test_symlink_dir_escape_rejected(vault, tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    os.symlink(outside, vault / "link")
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve("link/x.md")


def test_symlink_file_rejected(vault, tmp_path):
    target = tmp_path / "secret.md"; target.write_text("s")
    os.symlink(target, vault / "n.md")
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve("n.md")


def test_dangling_symlink_rejected(vault, tmp_path):
    os.symlink(tmp_path / "nope.md", vault / "d.md")
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve("d.md")


def test_hardlink_rejected(vault, tmp_path):
    outside = tmp_path / "o.md"; outside.write_text("x")
    os.link(outside, vault / "h.md")
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve("h.md")


def test_root_symlink_rejected(tmp_path):
    real = tmp_path / "real"; real.mkdir()
    os.symlink(real, tmp_path / "rootlink")
    with pytest.raises(SandboxViolation):
        Sandbox(tmp_path / "rootlink")


def test_fifo_rejected(vault):
    os.mkfifo(vault / "p")
    with pytest.raises(SandboxViolation):
        Sandbox(vault).resolve("p")


def test_good_path_ok(vault):
    p = Sandbox(vault).resolve("步态研究/ABCD.md")
    assert str(p).startswith(str(vault.resolve()))
