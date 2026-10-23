"""G7-4: parser token cards — 保存 grey until input, 「钥匙串已保存」 after save, 测试连接 with fakes (no network)."""
from litreader.platform_words import keystore_name, keystore_short
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_realrun import MemKeyring  # noqa: E402

from litreader import secrets  # noqa: E402
from litreader.parse.mineru_api import check_token  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def fake(code, status=200):
    seen = {}

    def req(method, url, token=None, json_body=None, timeout=120):
        seen.update(method=method, url=url, has_token=bool(token), body=json_body)
        return status, json.dumps({"code": code, "msg": "x"}).encode()
    return req, seen


def test_mineru_check_token_classifies_codes():
    req, seen = fake("A0202")
    assert check_token("t", req)[0] is False and seen["method"] == "GET" and seen["body"] is None
    assert "/extract/task/" in seen["url"]
    assert check_token("t", fake("A0211")[0])[0] is False
    assert check_token("t", fake(-60012)[0])[0] is True
    assert check_token("t", fake(-10001)[0])[0] is None
    assert check_token("", fake(0)[0])[0] is False


def test_parser_card_save_disabled_then_saved_and_test(app, monkeypatch):
    for k in ("MINERU_API_TOKEN", "PADDLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    kr = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: kr)
    from litreader.gui.models_page import PARSER_CARDS, ParserCard
    req, seen = fake(-60012)
    c = ParserCard(*PARSER_CARDS[0], req=req)
    assert not c.save_btn.isEnabled() and c.status.text() == "未读取（用到时再读）"   # G11: no read at render
    c.edit.setText("tok-123456789012345")
    assert c.save_btn.isEnabled()
    c.save()
    assert c.status.text() == f"{keystore_short()}已保存" and f"{keystore_name()}已保存" in c.msg.text()
    assert kr.d[("litreader", "MINERU_API_TOKEN")] == "tok-123456789012345"
    assert "tok-" not in c.msg.text() + c.status.text()
    c.test()
    assert c.tested.text() == "✅ 连接正常" and seen["has_token"]
    p = ParserCard(*PARSER_CARDS[1], req=req)
    p.edit.setText("short")
    p.save()
    p.test()
    assert p.tested.text() == "❌ 未通过"
