"""W5: fresh install (Windows zip) has no config.local.toml -> GUI creates one from the bundled example."""
import os
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from litreader import appconfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_bundled_example_matches_repo_example_and_has_no_personal_values():
    txt = appconfig.example_config_text()
    assert txt == (ROOT / "config.example.toml").read_text("utf-8")
    d = tomllib.loads(txt)
    assert d["vault"]["root"] == ""
    assert "/Users/doctor" not in txt and "qq.com" not in txt.lower()


def test_ensure_creates_once_and_never_overwrites(_hermetic_default_config, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITREADER_CONFIG", raising=False)
    p = _hermetic_default_config
    assert appconfig.ensure_default_config() == p
    assert p.read_text("utf-8") == appconfig.example_config_text()
    p.write_text("# mine\n", "utf-8")
    assert appconfig.ensure_default_config() is None
    assert p.read_text("utf-8") == "# mine\n"
    assert appconfig.find_config(None) == p.resolve()


def test_fresh_gui_creates_config_and_obsidian_save_fills_root(app, _hermetic_default_config, monkeypatch, tmp_path):
    from litreader.gui.app import MainWindow
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITREADER_CONFIG", raising=False)
    p = _hermetic_default_config
    win = MainWindow(data_dir=tmp_path / "guidata")
    assert p.is_file() and win.cfg is None and "root" in win.cfg_error
    assert "Mac 运行指南" not in win.cfg_error
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    card = win.settings.obsidian
    assert card.cfg_file == p.resolve()
    card.path.setText(str(vault))
    card.check()
    assert card.pending
    card._save(confirm=lambda: True)
    cfg = appconfig.load(None)
    assert cfg.vault_root == vault.resolve() or Path(cfg.vault_root) == vault
    assert cfg.llm_error  # no models.toml yet -> models page can start empty
    from litreader.gui.models_page import ModelsPage
    mp = ModelsPage(cfg)
    assert mp.ms is not None and not mp.path.exists()
    win.close()


def test_no_mac_only_wording_in_gui():
    for f in (ROOT / "src" / "litreader" / "gui").glob("*.py"):
        assert "Mac 运行指南" not in f.read_text("utf-8"), f
