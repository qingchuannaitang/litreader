"""G7-7: first-run auto-detect of the Obsidian vault from obsidian.json (read-only, best = open, then newest ts)."""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402

from litreader.configedit import detect_vaults  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _home(tmp_path, vaults):
    home = tmp_path / "home"
    cfgdir = home / "Library" / "Application Support" / "obsidian"
    cfgdir.mkdir(parents=True)
    out = {}
    for i, (name, ts, opn, real) in enumerate(vaults):
        p = home / name
        if real:
            (p / ".obsidian").mkdir(parents=True)
        out[f"id{i}"] = {"path": str(p), "ts": ts, **({"open": True} if opn else {})}
    f = cfgdir / "obsidian.json"
    f.write_text(json.dumps({"vaults": out}), "utf-8")
    return home, f


def test_detect_order_and_readonly(tmp_path):
    home, f = _home(tmp_path, [("Old", 100, False, True), ("New", 300, False, True), ("Open", 200, True, True),
                               ("Gone", 999, False, False)])
    before = f.read_bytes(), f.stat().st_mtime_ns
    got = detect_vaults(home)
    assert [d["name"] for d in got] == ["Open", "New", "Old"]          # missing folder skipped
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before
    (f).write_text("{not json", "utf-8")
    assert detect_vaults(home) == []
    assert detect_vaults(tmp_path / "nobody") == []


def test_card_prefills_only_when_unset(app, tmp_path):
    from litreader.gui.setup_panels import ObsidianCard
    cfg, _, _ = gui_fakes.environment(tmp_path)
    home, _ = _home(tmp_path, [("MyVault", 500, False, True)])
    found = lambda: detect_vaults(home)  # noqa: E731
    card = ObsidianCard(cfg, detect=found)
    if (Path(cfg.vault_root) / ".obsidian").is_dir():
        assert card.path.text() == str(cfg.vault_root) and card.detected == []   # configured vault is kept
    card2 = ObsidianCard(None, cfg_error="x", detect=found)
    assert card2.path.text() == str(home / "MyVault") and "自动检测" in card2.detect_note.text()
    assert card2.pending is None                                       # nothing saved / pending without config
