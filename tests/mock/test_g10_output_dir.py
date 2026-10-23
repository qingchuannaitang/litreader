"""G10-1: default write folder <vault>/litreader/ (notes in litreader/论文库/<主题>/), user-changeable in 基础设置 →
Obsidian; an old config with dry_run_dir = "_litreader_试运行" keeps working; nothing is moved or deleted."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_realrun import write_cfg  # noqa: E402

from litreader import appconfig, configedit  # noqa: E402
from litreader.errors import Stop  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _cfg(tmp_path, extra=None):
    v = tmp_path / "v"
    v.mkdir(exist_ok=True)
    p = write_cfg(tmp_path, v)
    if extra is not None:
        s = p.read_text("utf-8").replace('output_dir = "litreader"', extra)
        p.write_text(s, "utf-8")
    return appconfig.load(str(p)), v


def test_default_is_litreader(tmp_path):
    cfg, v = _cfg(tmp_path)
    assert cfg.dry_run_dir == "litreader" and cfg.dry_run_root == v / "litreader"
    assert "_litreader_试运行" not in (Path(__file__).parents[2] / "config.example.toml").read_text("utf-8").split(
        "旧版配置")[0]


def test_legacy_dry_run_dir_kept_and_output_dir_wins(tmp_path):
    cfg, v = _cfg(tmp_path, 'dry_run_dir = "_litreader_试运行"')
    assert cfg.dry_run_root == v / "_litreader_试运行"
    cfg, v = _cfg(tmp_path, 'dry_run_dir = "_litreader_试运行"\noutput_dir = "阅读/litreader"')
    assert cfg.dry_run_dir == "阅读/litreader" and cfg.dry_run_root == v / "阅读" / "litreader"


@pytest.mark.parametrize("bad", ["/abs", "../x", "a/../b", ".", "C:/x", "\\\\abs"])
def test_bad_output_dir_refused(tmp_path, bad):
    with pytest.raises(Stop):
        _cfg(tmp_path, f'output_dir = "{bad}"')


def test_vault_updates_output_dir_only_when_changed(tmp_path):
    text = '[vault]\nroot = "/x"\ndry_run_dir = "_litreader_试运行"\n'
    new, ch = configedit.vault_updates(text, "/x", "_litreader_试运行", "_litreader_试运行")
    assert ch == [] and new == text
    new, ch = configedit.vault_updates(text, "/x", "litreader", "_litreader_试运行")
    assert ch == ['新增 [vault] output_dir = "litreader"'] and 'dry_run_dir = "_litreader_试运行"' in new
    assert configedit.rel_in_vault(tmp_path, tmp_path / "a" / "b") == "a/b"
    assert configedit.rel_in_vault(tmp_path / "v", tmp_path / "w") is None
    assert configedit.rel_in_vault(tmp_path, tmp_path) is None


def test_card_field_resolved_path_picker_and_save(app, tmp_path, monkeypatch):
    from litreader.gui.setup_panels import ObsidianCard
    cfg, v = _cfg(tmp_path, 'dry_run_dir = "_litreader_试运行"')
    (v / ".obsidian").mkdir()
    old_note = v / "_litreader_试运行" / "论文库" / "主题" / "旧笔记.md"
    old_note.parent.mkdir(parents=True)
    old_note.write_text("旧", "utf-8")
    picked = {"p": str(tmp_path / "elsewhere")}
    card = ObsidianCard(cfg, detect=lambda: [], folder_picker=lambda start: picked["p"])
    assert card.out.text() == "_litreader_试运行"
    assert card.papers.text() == f"{v}/_litreader_试运行/论文库/"
    assert card.pending is None                                  # unchanged -> nothing to save
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    card._pick_out()                                             # outside the vault -> refused
    assert warned and card.out.text() == "_litreader_试运行"
    picked["p"] = str(v / "litreader")
    card._pick_out()
    assert card.out.text() == "litreader" and card.papers.text() == f"{v}/litreader/论文库/"
    assert card.pending and any("output_dir" in c for c in card.pending[1])
    card._save(confirm=lambda: True)
    assert appconfig.load(str(cfg.path)).dry_run_root == v / "litreader"
    assert old_note.read_text("utf-8") == "旧"                   # existing notes never moved
    card.out.setText("../bad")
    assert card.pending is None and card.papers.text() == "—"
