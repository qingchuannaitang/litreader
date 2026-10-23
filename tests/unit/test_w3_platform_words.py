"""W3: platform-aware wording + reveal-in-file-manager (subprocess mocked)."""
import sys

import pytest

from litreader import platform_words as W


@pytest.mark.parametrize("plat,name,short,fm,hint", [
    ("darwin", "钥匙串（Keychain）", "钥匙串", "访达", True),
    ("win32", "凭据管理器（Credential Manager）", "凭据管理器", "资源管理器", False),
    ("linux", "系统密钥环（keyring）", "密钥环", "文件管理器", False),
])
def test_wording_per_platform(monkeypatch, plat, name, short, fm, hint):
    monkeypatch.setattr(sys, "platform", plat)
    assert W.keystore_name() == name and W.keystore_short() == short and W.file_manager_name() == fm
    assert ("始终允许" in W.keystore_prompt_hint()) is hint


def test_preflight_hint_only_on_mac(monkeypatch):
    import inspect
    from litreader import realrun
    assert "始终允许" not in inspect.getsource(realrun)   # hint comes only from the helper
    monkeypatch.setattr(sys, "platform", "win32")
    assert W.keystore_prompt_hint() == ""


def test_no_hardcoded_keychain_wording_in_user_strings():
    import pathlib, re
    root = pathlib.Path(W.__file__).parent
    bad = []
    for p in root.rglob("*.py"):
        if p.name in ("platform_words.py", "sanitize.py"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or '"""' in s:
                continue
            if re.search(r'["\'][^"\']*(钥匙串|Keychain）)', line):
                bad.append(f"{p.name}:{i}")
    assert bad == []


def _reveal_calls(monkeypatch, tmp_path, plat, target):
    pytest.importorskip("PySide6")
    from litreader.gui import result
    monkeypatch.setattr(sys, "platform", plat)
    calls, opened = [], []
    result.reveal(str(target), runner=calls.append)
    return calls


def test_reveal_windows_selects_file(monkeypatch, tmp_path):
    f = tmp_path / "笔记.md"; f.write_text("x", encoding="utf-8")
    assert _reveal_calls(monkeypatch, tmp_path, "win32", f) == [["explorer", f"/select,{f}"]]


def test_reveal_windows_folder(monkeypatch, tmp_path):
    assert _reveal_calls(monkeypatch, tmp_path, "win32", tmp_path) == [["explorer", str(tmp_path)]]


def test_reveal_mac_open_R(monkeypatch, tmp_path):
    f = tmp_path / "n.md"; f.write_text("x", encoding="utf-8")
    assert _reveal_calls(monkeypatch, tmp_path, "darwin", f) == [["open", "-R", str(f)]]


def test_reveal_linux_opens_folder(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    from litreader.gui import result
    f = tmp_path / "n.md"; f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "linux")
    calls, urls = [], []
    result.reveal(str(f), opener=urls.append, runner=calls.append)
    assert calls == [] and urls[0].toLocalFile().rstrip("/") == str(tmp_path).replace("\\", "/")
