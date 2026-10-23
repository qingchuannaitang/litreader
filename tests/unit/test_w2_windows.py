"""W2: Windows compatibility (runs on every OS; Windows-only behaviour is simulated where needed)."""
from __future__ import annotations

import tomllib

from litreader import configedit
from litreader.zotero import setup as zs


def test_backslash_windows_path_written_to_toml_still_parses():
    cfg = '[vault]\nroot = ""\n\n[zotero]\ndata_dir = ""\napi_base = "http://localhost:23119/api"\n'
    win = r"C:\Users\王\Zotero Data\x\u"
    new, ch = configedit.set_keys(cfg, "vault", {"root": win})
    d = tomllib.loads(new)
    assert d["vault"]["root"] == "C:/Users/王/Zotero Data/x/u" and ch
    new2, _ = zs.config_updates(new, win, "http://localhost:23119/api")
    assert tomllib.loads(new2)["zotero"]["data_dir"] == "C:/Users/王/Zotero Data/x/u"


def test_quotes_and_control_chars_escaped():
    new, _ = configedit.set_keys("[a]\n", "a", {"k": 'x"y\tz'})
    assert tomllib.loads(new)["a"]["k"] == 'x"y\tz'


def test_new_section_with_backslash_path_parses():
    new, _ = configedit.set_keys("[other]\nx = 1\n", "vault", {"root": r"D:\notes\new"})
    assert tomllib.loads(new)["vault"]["root"] == "D:/notes/new"


def test_builtin_template_crlf_copy_accepted_but_real_edit_rejected(tmp_path, monkeypatch):
    import pytest
    from litreader.errors import Stop
    from litreader.templates import builtin
    orig = (builtin.DIR / builtin.FILES["module.rct"]).read_bytes()
    assert b"\r\n" not in orig
    d = tmp_path / "b"; d.mkdir()
    (d / builtin.FILES["module.rct"]).write_bytes(orig.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(builtin, "DIR", d)
    assert builtin.raw("module.rct") == orig          # canonical LF bytes, same hash
    (d / builtin.FILES["module.rct"]).write_bytes(orig.replace(b"\n", b"\r\n") + b"x")
    with pytest.raises(Stop):
        builtin.raw("module.rct")


def test_identity_fs_key_has_no_windows_forbidden_chars():
    from litreader.publish.store import PaperIdentity
    i = PaperIdentity("user:0", "ABCD1234", "PDF00001", "f" * 64)
    assert i.fs_key == "user_0__ABCD1234__" + "f" * 16 and i.key.startswith("user:0")
    assert PaperIdentity("users/0", "A", "B", "f" * 64).fs_key == "users/0__A__" + "f" * 16   # unchanged paths


def test_pid_alive_never_uses_os_kill_on_windows(monkeypatch):
    from litreader.store import core
    monkeypatch.setattr(core.os, "name", "nt")
    monkeypatch.setattr(core.os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill on Windows")))
    seen = []
    monkeypatch.setattr(core, "_pid_alive_windows", lambda pid: seen.append(pid) or True)
    assert core._pid_alive(1234) and seen == [1234]


def test_pid_alive_windows_real():
    import os, subprocess, sys
    import pytest
    if os.name != "nt":
        pytest.skip("Windows only")
    from litreader.store import core
    assert core._pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"]); p.wait()
    assert not core._pid_alive(p.pid)


def test_move_and_unlink_readonly_files(tmp_path):
    import os, stat
    from litreader.store import core
    a = tmp_path / "a"; a.write_bytes(b"x"); os.chmod(a, 0o444)
    d = tmp_path / "q"; d.mkdir()
    core._move(a, d / "a")
    assert (d / "a").read_bytes() == b"x" and not a.exists()
    assert not os.stat(d / "a").st_mode & stat.S_IWUSR
    core.force_unlink(d / "a")
    assert not (d / "a").exists()


def test_store_object_bytes_written_binary(tmp_path):
    from litreader.store import core
    assert core._O_BINARY == getattr(__import__("os"), "O_BINARY", 0)


def test_pdftools_decode_utf8_not_locale(monkeypatch, tmp_path):
    import subprocess
    from litreader import estimate
    seen = []

    class R:
        returncode, stdout, stderr = 0, "Pages: 3\n", ""

    def fake(cmd, **kw):
        seen.append(kw); return R()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(estimate.subprocess, "run", fake, raising=False)
    f = tmp_path / "x.pdf"; f.write_bytes(b"%PDF")
    try:
        estimate.pdf_stats(f)
    except Exception:
        pass
    assert seen and all(k.get("encoding") == "utf-8" and k.get("errors") == "replace" for k in seen)


def test_zotero_file_url_to_windows_path():
    from litreader.zotero.client import _url2path
    assert _url2path("/C:/Users/%E7%8E%8B/Zotero/storage/AB/My%20Paper.pdf", True) == r"C:\Users\王\Zotero\storage\AB\My Paper.pdf"
    assert _url2path("/Users/me/My%20Paper.pdf", False) == "/Users/me/My Paper.pdf"
