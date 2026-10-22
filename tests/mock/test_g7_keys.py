"""G7-1: keychain errors are not "missing"; realrun preflight stops before any upload / model call."""
import pytest

from litreader import appconfig, realrun, secrets
from litreader.errors import Stop
from litreader.llm.client import ProviderError, chat
from litreader.llm.config import ProviderConfig
from tests.mock.test_realrun import MemKeyring, write_cfg


class BrokenKeyring(MemKeyring):
    def get_password(self, s, n):
        raise PermissionError("denied")


def _p(key="DEEPSEEK_API_KEY"):
    return ProviderConfig("writer1", "openai_compatible", "https://example.invalid", "m", key, None)


def no_net(*a, **k):
    raise AssertionError("network must not be called")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "MINERU_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)


def test_keyring_error_is_keychain_error_not_missing(monkeypatch):
    monkeypatch.setattr(secrets, "_keyring", lambda: BrokenKeyring())
    assert secrets.get("DEEPSEEK_API_KEY") is None          # status displays stay lenient
    with pytest.raises(secrets.KeychainError):
        secrets.SecretEnv().get("DEEPSEEK_API_KEY")
    with pytest.raises(ProviderError) as e:
        chat(_p(), [{"role": "user", "content": "x"}], no_net, secrets.SecretEnv())
    assert e.value.category == "KEYCHAIN_ERROR" and "PermissionError" in e.value.detail


def test_keyring_only_key_works(monkeypatch):
    k = MemKeyring()
    k.d[("litreader", "DEEPSEEK_API_KEY")] = "sk-test-not-real"
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    seen = {}

    def tx(url, headers, body, timeout):
        seen["auth"] = headers["Authorization"] == "Bearer sk-test-not-real"
        return 200, b'{"choices":[{"message":{"content":"ok"}}]}'
    assert chat(_p(), [{"role": "user", "content": "x"}], tx, secrets.SecretEnv()) == "ok" and seen["auth"]


def _cfg(tmp_path):
    (tmp_path / "v").mkdir()
    return appconfig.load(str(write_cfg(tmp_path, tmp_path / "v", vision=True)))


def test_writer_missing_vision_present_stops_before_anything(tmp_path):
    cfg = _cfg(tmp_path)
    env = {"MINIMAX_API_KEY": "x", "MINERU_API_TOKEN": "t"}
    with pytest.raises(Stop) as e:
        realrun._run(cfg, "精读 zotero 中的 Foo", realrun.ConsoleUI() if hasattr(realrun, "ConsoleUI") else None,
                     zotero=object(), llm_tx=no_net, env=env)
    msg = str(e.value)
    assert "主笔" in msg and "DEEPSEEK_API_KEY" in msg and "看图" not in msg and "x" not in msg.split("：", 1)[0]


def test_preflight_reports_keychain_error_and_mineru(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(secrets, "_keyring", lambda: BrokenKeyring())
    with pytest.raises(Stop) as e:
        realrun.preflight_keys(cfg, secrets.SecretEnv())
    m = str(e.value)
    assert "KEYCHAIN_ERROR: PermissionError" in m and "MinerU" in m and "交叉核对" in m


def test_preflight_passes_when_all_keys_present(tmp_path):
    cfg = _cfg(tmp_path)
    realrun.preflight_keys(cfg, {"DEEPSEEK_API_KEY": "a", "MINIMAX_API_KEY": "b", "MINERU_API_TOKEN": "c"})
