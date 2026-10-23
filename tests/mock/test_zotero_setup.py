"""One-click Zotero setup (2026-10-18): read-only detection on a fake profile dir, fake local API, confirmed config save."""
import io
import os
import time
from pathlib import Path
import urllib.error

from litreader import cli
from litreader.zotero import setup as zs

PREFS = '''// Mozilla User Preferences
user_pref("extensions.zotero.dataDir", "{dd}");
user_pref("extensions.zotero.useDataDir", {use});
user_pref("extensions.zotero.httpServer.localAPI.enabled", {api});
user_pref("extensions.zotero.httpServer.port", {port});
user_pref("extensions.zotero.lastViewedFolder", "C\\\\a \\"q\\"");
'''


def mac_home(tmp_path, dd=None, use="true", api="true", port=23119, data=True):
    home = tmp_path / "home"
    prof = home / "Library" / "Application Support" / "Zotero" / "Profiles" / "abcd.default"
    prof.mkdir(parents=True)
    dd = dd or tmp_path / "ZoteroData"
    (prof / "prefs.js").write_text(PREFS.format(dd=dd, use=use, api=api, port=port), "utf-8")
    if data:
        (dd / "storage").mkdir(parents=True); (dd / "zotero.sqlite").write_bytes(b"x")
    return home, prof / "prefs.js", dd


class R:
    def __init__(self, status=200): self.status, self.headers = status, {"Zotero-API-Version": "3"}
    def __enter__(self): return self
    def __exit__(self, *a): return False


def op_ok(req, t):
    assert req.full_url == "http://localhost:23119/api/" and req.get_method() == "GET"
    return R()


def op_403(req, t): raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"Request not allowed"))
def op_down(req, t): raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))


def test_parse_prefs_types_and_escapes():
    p = zs.parse_prefs(PREFS.format(dd="/x/Z", use="true", api="false", port=23120))
    assert p["extensions.zotero.dataDir"] == "/x/Z" and p["extensions.zotero.useDataDir"] is True
    assert p["extensions.zotero.httpServer.localAPI.enabled"] is False and p["extensions.zotero.httpServer.port"] == 23120
    assert p["extensions.zotero.lastViewedFolder"] == 'C\\a "q"'


def test_detect_custom_data_dir_on_macos_profile_read_only(tmp_path):
    home, prefs, dd = mac_home(tmp_path)
    before = (prefs.read_bytes(), prefs.stat().st_mtime_ns)
    d = zs.detect("darwin", home)
    assert d["data_dir"] == dd and d["valid"] and d["source"].startswith("prefs.js（自定义") and d["local_api_pref"] is True
    assert (prefs.read_bytes(), prefs.stat().st_mtime_ns) == before                      # never written


def test_default_data_dir_when_use_data_dir_false_or_no_profile(tmp_path):
    home, _, _ = mac_home(tmp_path, use="false", data=False)
    (home / "Zotero" / "storage").mkdir(parents=True); (home / "Zotero" / "zotero.sqlite").write_bytes(b"x")
    d = zs.detect("darwin", home)
    assert d["data_dir"] == home / "Zotero" and d["valid"] and "默认位置" in d["source"]
    d2 = zs.detect("darwin", tmp_path / "nohome")
    assert d2["prefs"] is None and not d2["valid"] and d2["checks"] == {"zotero.sqlite": False, "storage/": False}


def test_windows_profile_root_and_newest_profile_wins(tmp_path):
    appdata = tmp_path / "Roaming"
    for name, dd, age in (("old.default", "C:/Old", 100), ("new.default", "D:/Zot", 0)):
        p = appdata / "Zotero" / "Zotero" / "Profiles" / name; p.mkdir(parents=True)
        f = p / "prefs.js"; f.write_text(PREFS.format(dd=dd, use="true", api="false", port=23119), "utf-8")
        os.utime(f, (time.time() - age, time.time() - age))
    d = zs.detect("win32", tmp_path, {"APPDATA": str(appdata)})
    assert str(d["data_dir"]).replace("\\", "/").endswith("D:/Zot") and d["profiles"] == 2


def test_probe_states_and_instructions():
    assert zs.probe(23119, op_ok)["status"] == "OK"
    off = zs.probe(23119, op_403)
    assert off["status"] == "DISABLED" and off["http"] == 403
    assert zs.probe(23119, op_down)["status"] == "NOT_RUNNING"
    d = {"valid": True, "data_dir": "/z", "source": "s", "checks": {}, "profiles": 1, "local_api_pref": False}
    txt = "\n".join(zs.report(d, off))
    assert "允许此计算机上的其他应用程序与 Zotero 通讯" in txt and "高级" in txt and "不会替你改 Zotero 设置" in txt


def test_config_updates_only_touch_zotero_section():
    cfg = '[vault]\nroot = "/v"\ndata_dir = "keep"\n\n[zotero]\napi_base = "http://localhost:23119/api"   # 注释\ndata_dir = "~/Zotero"\n\n[app]\ndata_dir = ""\n'
    new, ch = zs.config_updates(cfg, __import__("pathlib").Path("/Users/h/ZoteroData"), "http://localhost:23119/api")
    assert ch == ['[zotero] data_dir: "~/Zotero" → "/Users/h/ZoteroData"']
    assert 'data_dir = "keep"' in new and '[app]\ndata_dir = ""' in new and "# 注释" in new
    assert zs.config_updates(new, __import__("pathlib").Path("/Users/h/ZoteroData"), "http://localhost:23119/api")[1] == []


def test_cli_setup_saves_only_after_yes_with_backup(tmp_path, monkeypatch, capsys):
    home, prefs, dd = mac_home(tmp_path)
    real_detect, real_probe = zs.detect, zs.probe
    monkeypatch.setattr(zs, "detect", lambda *a, **k: real_detect("darwin", home))
    monkeypatch.setattr(zs, "probe", lambda port, opener=None, timeout=3.0: real_probe(port, op_ok))
    cfg = tmp_path / "config.local.toml"
    cfg.write_text('[vault]\nroot = "/v"\n\n[zotero]\napi_base = "http://localhost:23119/api"\ndata_dir = "~/Zotero"\n', "utf-8")
    monkeypatch.setattr("builtins.input", lambda q="": "n")
    assert cli.main(["--config", str(cfg), "setup", "zotero"]) == 0
    out = capsys.readouterr().out
    assert "只读检测，不修改 Zotero" in out and f"Zotero 数据目录：{dd}" in out and "本地接口可用" in out
    assert "未保存" in out and 'data_dir = "~/Zotero"' in cfg.read_text("utf-8") and not list(tmp_path.glob("*.bak-*"))
    monkeypatch.setattr("builtins.input", lambda q="": "y")
    assert cli.main(["--config", str(cfg), "setup", "zotero"]) == 0
    assert f'data_dir = "{Path(dd).as_posix()}"' in cfg.read_text("utf-8")
    baks = list(tmp_path.glob("config.local.toml.bak-*"))
    assert len(baks) == 1 and 'data_dir = "~/Zotero"' in baks[0].read_text("utf-8")
    assert prefs.read_text("utf-8").count("user_pref") == 5                                 # Zotero untouched
    monkeypatch.setattr(zs, "probe", lambda port, opener=None, timeout=3.0: real_probe(port, op_403))
    assert cli.main(["--config", str(cfg), "setup", "zotero"]) == 1
    out = capsys.readouterr().out
    assert "无需修改" in out and "返回 403" in out
