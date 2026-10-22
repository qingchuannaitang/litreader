"""G12-3: 「与主笔共用」 — 看图 uses the 主笔 主用 slot, only if the user marked it supports_vision. Fakes only."""
import os
import sys
import tomllib
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))
from test_g11_keys import CountingKeyring  # noqa: E402
from test_realrun import setup_run  # noqa: E402

from litreader import appconfig, realrun, secrets  # noqa: E402
from litreader.llm import models as M  # noqa: E402
from litreader.llm.config import ConfigError  # noqa: E402

W = dict(vendor="DeepSeek", model="user-model", url="https://api.deepseek.com", key_ref="DEEPSEEK_API_KEY")


def _ms(sv=True):
    ms = M.ModelSettings()
    ms.roles["writer"].append(M.Slot(**W, supports_vision=sv))
    ms.roles["vision"].append(M.Slot("MiniMax", "vm", "https://api.minimaxi.com/v1", "MINIMAX_API_KEY"))
    ms.vision_share = "writer"
    return ms


def test_shared_vision_uses_writer_primary():
    llm = _ms().to_llm_config()
    (p,) = llm.chain("vision", need_vision=True)
    w = llm.chain("extract")[0]
    assert (p.base_url, p.model, p.key_env) == (w.base_url, w.model, w.key_env) and p.supports_vision is True
    assert p.json_mode is False and p.max_tokens == 2048


def test_share_refused_unless_marked():
    for sv in (None, False):
        with pytest.raises(ConfigError, match="支持看图"):
            _ms(sv).to_llm_config()
    ms = _ms()
    ms.vision_share = "judge"
    with pytest.raises(ConfigError, match="share"):
        ms.to_llm_config()


def test_roundtrip_and_backward_compatible(tmp_path):
    p = tmp_path / "models.toml"
    M.save(_ms(), p)
    d = tomllib.loads(p.read_text("utf-8"))
    assert d["share"] == {"vision": "writer"} and d["writer"][0]["supports_vision"] is True
    assert d["vision"][0]["model"] == "vm"                       # own vision slot kept for when sharing is off
    ms = M.load(p)
    assert ms.vision_share == "writer" and ms.roles["writer"][0].supports_vision is True
    assert ms.find(M.SHARED_VISION_ID) is ms.roles["writer"][0]   # price / label of the shared slot
    # an older file (no [share], no supports_vision) loads exactly as before
    ms.vision_share = None
    ms.roles["writer"][0].supports_vision = None
    M.save(ms, p)
    assert "share" not in tomllib.loads(p.read_text("utf-8"))
    assert M.load(p).to_llm_config().chain("vision")[0].model == "vm"


def test_shared_key_read_once_per_session(tmp_path, monkeypatch):
    for n in ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINERU_API_TOKEN"):
        monkeypatch.delenv(n, raising=False)
    k = CountingKeyring()
    k.set_password("litreader", "DEEPSEEK_API_KEY", "k")
    k.set_password("litreader", "MINERU_API_TOKEN", "t")
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    vault, pdf, cfg = setup_run(tmp_path)
    M.save(_ms(), cfg.models_path)
    cfg = appconfig.load(str(cfg.path))
    assert cfg.llm.stations["vision"] == [M.SHARED_VISION_ID]
    env = secrets.SecretEnv()
    realrun.preflight_keys(cfg, env)
    realrun.preflight_keys(cfg, env)
    assert k.reads.count("DEEPSEEK_API_KEY") <= 1 and "MINIMAX_API_KEY" not in k.reads


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_gui_share_toggle(app, tmp_path, monkeypatch):
    k = CountingKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    vault, pdf, cfg = setup_run(tmp_path, vision=True)
    from litreader.gui.models_page import ModelsPage
    page = ModelsPage(cfg, transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    vs = page.vision_share
    vs.share.setChecked(True)                                  # writer not marked -> refused, clear message
    assert not vs.share.isChecked() and page.ms.vision_share is None and "厂商文档" in vs.msg.text()
    assert not vs.confirm.isHidden() and "user-model" in vs.confirm.text()
    vs.confirm.setChecked(True)
    vs.share.setChecked(True)
    assert vs.share.isChecked() and page.editors["vision"].isHidden() and "看图使用主笔主用" in vs.msg.text()
    d = tomllib.loads(cfg.models_path.read_text("utf-8"))
    assert d["share"]["vision"] == "writer" and d["writer"][0]["supports_vision"] is True
    c2 = appconfig.load(str(cfg.path))
    assert c2.llm.chain("vision", need_vision=True)[0].key_env == c2.llm.chain("extract")[0].key_env
    vs.confirm.setChecked(False)                               # un-marking switches sharing off
    assert page.ms.vision_share is None and not page.editors["vision"].isHidden()
    assert "share" not in tomllib.loads(cfg.models_path.read_text("utf-8"))
    assert k.reads == []                                       # the toggle itself never reads the keychain
