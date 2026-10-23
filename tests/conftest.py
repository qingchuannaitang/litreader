import os

import pytest

os.environ.setdefault("LITREADER_NO_UPDATE_CHECK", "1")   # G8-9: tests never touch the network
import tempfile  # noqa: E402

os.environ["LITREADER_KEY_INDEX"] = os.path.join(tempfile.mkdtemp(prefix="litreader-keyidx-"), "key_names.json")


class _EmptyKeyring:
    """W2: tests never see the developer's / CI machine's real keychain."""
    def __init__(self):
        self.d = {}

    def get_password(self, s, n):
        return self.d.get((s, n))

    def set_password(self, s, n, v):
        self.d[(s, n)] = v

    def delete_password(self, s, n):
        self.d.pop((s, n))


@pytest.fixture(autouse=True)
def _hermetic_secrets(monkeypatch):
    """W2: hermetic keys. Real API keys/tokens in the environment are hidden from every test (no accidental paid
    call, and results don't depend on what the machine happens to have); the keyring is an empty in-memory one.
    Tests that need a key set a fake one themselves."""
    for k in list(os.environ):
        if k.endswith(("_API_KEY", "_API_TOKEN")):
            monkeypatch.delenv(k, raising=False)
    from litreader import secrets
    kr = _EmptyKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    yield kr


@pytest.fixture(autouse=True)
def _gc_on_main_thread():
    """W2: free each test's dead Qt objects here (main thread), never later inside some worker thread."""
    yield
    import gc
    gc.collect()


@pytest.fixture(autouse=True)
def _fresh_key_session():
    from litreader import secrets
    secrets.reset_session()
    try:
        os.remove(os.environ["LITREADER_KEY_INDEX"])
    except OSError:
        pass
    yield

from litreader.publish.store import PaperIdentity
from litreader.render.protected_zone import empty_zone


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault" / "论文库"
    v.mkdir(parents=True)
    return v


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "appdata"


@pytest.fixture
def ident():
    return PaperIdentity(library="user:0", parent_key="ABCD1234",
                         attachment_key="PDF00001", pdf_sha256="f" * 64, doi=None)


def fake_core(ident):
    return {"title_zh": "测试中文题名", "facts": [{"text": "n=48", "page": 5, "kind": "PAPER"}]}


def fake_render(ident, analysis):
    return (f"# {analysis['title_zh']}（Test Title）\n\n> 三分钟读懂本文\n\n"
            f"## 八、待解决问题与我的批注\n{empty_zone()}\n\n## 九、证据\n")


def fake_render_v2(ident, analysis):
    return fake_render(ident, analysis).replace("三分钟读懂本文", "三分钟读懂本文（新版模板）")


def pytest_sessionfinish(session, exitstatus):
    """W2: tidy Qt shutdown. Without this the interpreter could crash *after* all tests passed (top-level widgets
    from many tests destroyed in arbitrary order at exit) -> CI exit code 134/139."""
    import sys
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    import gc
    for w in QApplication.topLevelWidgets():
        for th in w.findChildren(QThread):
            th.quit(); th.wait(5000)
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture(autouse=True)
def _hermetic_default_config(monkeypatch, tmp_path_factory):
    """W5: the GUI creates ~/litreader/config.local.toml on a fresh install; tests never touch the real home."""
    from litreader import appconfig
    d = tmp_path_factory.mktemp("home") / "litreader" / "config.local.toml"
    monkeypatch.setattr(appconfig, "default_config_path", lambda: d)
    yield d
