"""G12-2: the user can delete every 看图 model and save; models.toml then has no vision station, preflight does not
ask for a vision key and the cost estimate has no vision row. 主笔 stays required. Fakes only."""
import os
import sys
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import MemKeyring, setup_run  # noqa: E402

from litreader import appconfig, estimate as est_mod, realrun, secrets  # noqa: E402
from litreader.errors import Stop  # noqa: E402
from litreader.llm import models as M  # noqa: E402
from litreader.llm.config import ConfigError  # noqa: E402


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    for n in ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINERU_API_TOKEN"):
        monkeypatch.delenv(n, raising=False)
    return k


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_gui_delete_vision_primary_and_save(app, tmp_path, kr, monkeypatch):
    vault, pdf, cfg = setup_run(tmp_path, vision=True, prices=(2, 8))
    assert "vision" in cfg.llm.stations
    from PySide6.QtWidgets import QMessageBox
    from litreader.gui.models_page import ModelsPage
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    page = ModelsPage(cfg, transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    ed = page.editors["vision"]
    assert ed.cards[0].idx == 0
    ed.cards[0]._delete()
    assert page.ms.roles["vision"] == []
    d = tomllib.loads(cfg.models_path.read_text("utf-8"))
    assert not d.get("vision") and d["writer"] and d["judge"]
    assert ed.cards and ed.cards[0].idx is None          # an empty, unsaved card to add one again
    cfg2 = appconfig.load(str(cfg.path))
    assert cfg2.llm_error is None and "vision" not in cfg2.llm.stations and "extract" in cfg2.llm.stations


def test_preflight_and_estimate_without_vision(tmp_path, kr):
    vault, pdf, cfg = setup_run(tmp_path, vision=False, prices=(2, 8))
    env = {"DEEPSEEK_API_KEY": "k", "MINERU_API_TOKEN": "t"}          # no MINIMAX_API_KEY at all
    realrun.preflight_keys(cfg, env)
    present = {r for r, st in M.STATION.items() if st in cfg.llm.stations}
    est = est_mod.estimate({"pages": 10, "chars": 30000, "figures": 6}, present, cached_parse=False)
    assert set(est["roles"]) == {"writer", "judge"}
    cost = realrun.estimate_cost(cfg, est)
    assert set(cost["roles"]) == {"writer", "judge"} and cost["priced"]
    with_vis = est_mod.estimate({"pages": 10, "chars": 30000, "figures": 6}, present | {"vision"}, cached_parse=False)
    assert with_vis["roles"]["judge"]["in"] > est["roles"]["judge"]["in"]   # no per-figure judge cost without vision


def test_preflight_still_requires_vision_key_when_configured(tmp_path, kr):
    vault, pdf, cfg = setup_run(tmp_path, vision=True)
    with pytest.raises(Stop, match="看图"):
        realrun.preflight_keys(cfg, {"DEEPSEEK_API_KEY": "k", "MINERU_API_TOKEN": "t"})


def test_writer_still_required():
    ms = M.ModelSettings()
    ms.roles["judge"].append(M.Slot("DeepSeek", "m", "https://api.deepseek.com", "DEEPSEEK_API_KEY"))
    with pytest.raises(ConfigError, match="主笔"):
        ms.to_llm_config()
