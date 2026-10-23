"""G11-1: lazy keychain reads — no read at GUI startup / settings render; one read per key per process; a denied
read is not retried in a loop; 测试连接 reads only its own key. Fakes only."""
from litreader.platform_words import keystore_name, keystore_short
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import MemKeyring, write_cfg  # noqa: E402

from litreader import appconfig, realrun, secrets  # noqa: E402
from litreader.errors import Stop  # noqa: E402

KEYS = ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINERU_API_TOKEN", "PADDLE_API_KEY")


class CountingKeyring(MemKeyring):
    def __init__(self, deny=()):
        super().__init__()
        self.reads, self.deny = [], set(deny)

    def get_password(self, s, n):
        self.reads.append(n)
        if n in self.deny:
            raise PermissionError("user clicked 拒绝")
        return super().get_password(s, n)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def kr(monkeypatch):
    k = CountingKeyring()
    for n in KEYS:
        k.d[("litreader", n)] = f"fake-{n.lower()}-0000000000"
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


def test_successful_read_cached_for_process(kr):
    assert secrets.lookup("DEEPSEEK_API_KEY").startswith("fake-")
    for _ in range(5):
        secrets.get("DEEPSEEK_API_KEY")
        secrets.SecretEnv().get("DEEPSEEK_API_KEY")
    assert kr.reads == ["DEEPSEEK_API_KEY"]


def test_denied_read_not_retried(monkeypatch):
    k = CountingKeyring(deny={"DEEPSEEK_API_KEY"})
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    for _ in range(4):
        with pytest.raises(secrets.KeychainError):
            secrets.lookup("DEEPSEEK_API_KEY")
        assert secrets.get("DEEPSEEK_API_KEY") is None
    assert k.reads == ["DEEPSEEK_API_KEY"] and secrets.status("DEEPSEEK_API_KEY") == "denied"
    secrets.forget_denied("DEEPSEEK_API_KEY")        # explicit user retry → exactly one more ask
    with pytest.raises(secrets.KeychainError):
        secrets.lookup("DEEPSEEK_API_KEY")
    assert len(k.reads) == 2


def test_status_never_reads_and_uses_name_index(kr):
    assert secrets.status("DEEPSEEK_API_KEY") == "unknown"
    secrets.set_secret("MINIMAX_API_KEY", "fake-new-value-000000")
    assert secrets.status("MINIMAX_API_KEY") == "saved"
    secrets.reset_session()                          # new process
    assert secrets.status("MINIMAX_API_KEY") == "indexed" and kr.reads == []
    idx = Path(os.environ["LITREADER_KEY_INDEX"]).read_text("utf-8")
    assert "MINIMAX_API_KEY" in idx and "fake" not in idx       # names only, never values


def test_preflight_reads_only_needed_keys_once(kr, tmp_path):
    (tmp_path / "v").mkdir()
    cfg = appconfig.load(str(write_cfg(tmp_path, tmp_path / "v", vision=True)))
    env = secrets.SecretEnv()
    realrun.preflight_keys(cfg, env, need_mineru=False)
    first = list(kr.reads)
    assert "MINERU_API_TOKEN" not in first and "PADDLE_API_KEY" not in first
    realrun.preflight_keys(cfg, env, need_mineru=False)
    for st in cfg.llm.stations:                      # the run itself reads again → served from memory
        env.get(cfg.llm.chain(st)[0].key_env)
    assert kr.reads == first and len(first) == len(set(first))


def test_preflight_denied_stops_without_loop(tmp_path, monkeypatch):
    k = CountingKeyring(deny={"DEEPSEEK_API_KEY"})
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    (tmp_path / "v").mkdir()
    cfg = appconfig.load(str(write_cfg(tmp_path, tmp_path / "v", vision=True)))
    for _ in range(3):
        with pytest.raises(Stop):
            realrun.preflight_keys(cfg, secrets.SecretEnv())
    assert k.reads.count("DEEPSEEK_API_KEY") == 1


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_gui_startup_and_settings_render_read_nothing(app, tmp_path, kr):
    import gui_fakes
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    from litreader.gui.models_page import PARSER_CARDS, ModelsPage, ParserCard, ParserPanel
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.show()
    app.processEvents()
    ModelsPage(cfg, transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    ParserPanel(cfg)
    app.processEvents()
    assert kr.reads == []
    req = lambda *a, **k: (200, b'{"code": -60012, "msg": "x"}')  # noqa: E731
    c = ParserCard(*PARSER_CARDS[0], req=req)
    assert c.status.text() == "未读取（用到时再读）" and c.test_btn.isEnabled()
    c.test()                                          # 测试连接 reads only this card's token
    assert kr.reads == ["MINERU_API_TOKEN"] and c.status.text() == f"{keystore_short()}已保存"
