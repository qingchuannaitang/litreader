import os

import pytest

os.environ.setdefault("LITREADER_NO_UPDATE_CHECK", "1")   # G8-9: tests never touch the network
import tempfile  # noqa: E402

os.environ["LITREADER_KEY_INDEX"] = os.path.join(tempfile.mkdtemp(prefix="litreader-keyidx-"), "key_names.json")


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
