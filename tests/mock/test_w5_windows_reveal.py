"""W5 round 2: 显示文件位置 on Windows selects the note; platform-specific wording; display paths."""
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from litreader import platform_words as pw  # noqa: E402
from litreader.gui import result  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOTE = r"D:\A\vasa/litreader/论文库/神经步态与OpenCap分析/Biomechanical Gait Analysis Using a Smartphone-Based Motion Capture System (OpenCap) in Patients with Neurological Disorders.md"


def test_windows_select_command_exact_string():
    assert result.windows_select_command(NOTE) == (
        r'explorer /select,"D:\A\vasa\litreader\论文库\神经步态与OpenCap分析\Biomechanical Gait Analysis Using a '
        r'Smartphone-Based Motion Capture System (OpenCap) in Patients with Neurological Disorders.md"')


def test_reveal_windows_passes_one_string(tmp_path):
    f = tmp_path / "a b (c) 论文.md"
    f.write_text("x", "utf-8")
    calls = []
    result.reveal(str(f), runner=calls.append, platform="win32")
    assert calls == [result.windows_select_command(f)] and isinstance(calls[0], str)


def test_reveal_windows_missing_file_opens_folder(tmp_path):
    calls = []
    result.reveal(str(tmp_path / "gone.md"), runner=calls.append, platform="win32")
    assert len(calls) == 1 and calls[0][0] == "explorer" and calls[0][1].endswith(tmp_path.name)
    calls.clear()
    result.reveal(str(tmp_path / "nodir" / "gone.md"), runner=calls.append, platform="win32")
    assert calls == []


def test_reveal_mac_unchanged(tmp_path):
    f = tmp_path / "n.md"
    f.write_text("x", "utf-8")
    calls = []
    result.reveal(str(f), runner=calls.append, platform="darwin")
    assert calls == [["open", "-R", str(f)]]


def test_display_path_and_wording():
    assert pw.display_path(r"D:\A\vasa/litreader/论文库/", "win32") == "D:\\A\\vasa\\litreader\\论文库\\"
    assert pw.display_path("/Users/x/v/", "darwin") == "/Users/x/v/"
    assert "设置 → 系统 → 通知" in pw.notification_hint("win32") and "macOS" not in pw.notification_hint("win32")
    assert "macOS" in pw.notification_hint("darwin")
    assert pw.shortcut("O", "win32") == "Ctrl+O" and pw.shortcut("O", "darwin") == "⌘O"


def test_guard_no_hardcoded_mac_wording_in_gui_strings():
    """macOS-only words in GUI string literals must come from platform_words (comments/docstrings are fine)."""
    bad = re.compile(r"""["'][^"'\n]*(macOS|系统设置|访达|Finder|⌘)[^"'\n]*["']""")
    hits = []
    for f in (ROOT / "src" / "litreader" / "gui").glob("*.py"):
        if f.name == "macos.py":
            continue
        for n, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if bad.search(code) and '"""' not in line:
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert not hits, hits
