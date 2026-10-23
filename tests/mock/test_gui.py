"""GUI v1 (Stage G2): worker/bus bridge, offscreen window smoke run with fakes, model settings, avatar, presets.
No network and no paid API: Zotero / MinerU / LLM are local fakes (gui_fakes.py)."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_realrun import MemKeyring  # noqa: E402

from litreader import events, realrun, secrets  # noqa: E402
from litreader.gui import bridge, runner  # noqa: E402

TEXT = "精读zotero中的 gait，并将精读笔记存入obsidian中"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


def spin(app, cond, timeout=15.0):
    t = time.time()
    while not cond():
        app.processEvents()
        if time.time() - t > timeout:
            raise AssertionError("timeout")
        time.sleep(0.005)


def test_worker_bridge_answers_decisions_through_future(app):
    seen, done = [], []

    def run(ui):
        events.stage(ui, "zotero")
        a = events.decide(ui, "candidate", "请输入序号（q 取消）：", [events.opt("1", "A"), events.opt("2", "B")])
        ui.say(f"选了 {a}")
        return {"kind": "other", "code": 0, "a": a}
    w = bridge.RunWorker(run)
    w.event.connect(lambda ev: (seen.append(ev), ev.type == "decision_request" and w.answer(ev["id"], "2")))
    w.finished.connect(done.append)
    th = bridge.start(w)
    spin(app, lambda: done)
    th.wait(2000)
    assert done[0] == {"status": "ok", "result": {"kind": "other", "code": 0, "a": "2"}}
    types = [e.type for e in seen]
    assert types == ["stage", "decision_request", "decision_response", "log"]
    assert seen[3]["text"] == "选了 2" and w.answer("nope", "x") is False


def test_worker_cancel_while_waiting_and_errors(app):
    done, errs = [], []

    def run(ui):
        a = events.decide(ui, "cost", "是否继续？(y/n)：", [events.opt("y", "继续"), events.opt("n", "取消")])
        if a == "q":
            raise realrun.Cancelled("已取消：未上传、未调用模型、未写入任何笔记")
        return {"kind": "other"}
    w = bridge.RunWorker(run)
    w.event.connect(lambda ev: ev.type == "error" and errs.append(ev))
    w.finished.connect(done.append)
    th = bridge.start(w)
    spin(app, lambda: w.pending())
    w.cancel()
    spin(app, lambda: done)
    th.wait(2000)
    assert done[0]["status"] == "cancelled" and errs[0]["recoverable"] and errs[0]["cancelled"]

    def boom(ui):
        raise ZeroDivisionError("x")
    done2 = []
    w2 = bridge.RunWorker(boom)
    w2.finished.connect(done2.append)
    th2 = bridge.start(w2)
    spin(app, lambda: done2)
    th2.wait(2000)
    assert done2[0]["status"] == "error" and "ZeroDivisionError" in done2[0]["message"]


def answer_like_user(win, kinds):
    """Press the same buttons a user would: candidate 1, cost y, template Enter, topic a/Enter."""
    req = win.flow.req
    if not req:
        return
    key = {"candidate": "1", "cost": "y", "template": "", "topic_folder": "", "confirm": "y"}.get(req["kind"], "")
    kinds.append(req["kind"])
    win.flow._answer(key)
    win.flow.req = None


def test_window_full_dry_run_with_fakes(app, tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok"); monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    cfg, kw, fake_mineru = gui_fakes.environment(tmp_path)
    from litreader.gui.app import MainWindow
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.show()
    before = set((tmp_path / "vault").rglob("*"))
    win.home.input.setText(TEXT)
    win.home._submit()
    assert win.stack.currentWidget() is win.flow   # home jumps straight into the flow
    kinds = []
    spin(app, lambda: (answer_like_user(win, kinds), not win.running and win.last_result is not None)[1], 30)
    assert kinds == ["candidate", "cost", "template", "topic_folder"]
    rc = win.last_result
    assert rc["status"] == "DRY_RUN_COMPLETE" and "论文库/老年步态力学/" in rc["note"]
    new = set((tmp_path / "vault").rglob("*")) - before
    assert new and all(cfg.dry_run_root in p.parents or p == cfg.dry_run_root for p in new)   # dry-run only
    log = win.flow.log.toPlainText()
    assert "运行前估算（ESTIMATE" in log and "实际用量" in log
    assert win.flow.result_btn.isEnabled() and win.flow.stepper.current == 8
    st = win.flow.tracker.state      # G6: 9 steps; no project linked in this run, no author conflict -> skipped
    assert st["done"] == "done" and st["select"] == st["estimate"] == st["parse"] == st["topic"] == "done"
    assert st["author"] == "skip" and not win.flow.nodes.animating()
    html_ = win.result.preview.toHtml()
    txt = win.result.preview.toPlainText()     # G7 drawer: only 论文信息 + 三分钟了解论文
    assert "论文信息" in txt and "三分钟了解论文" in txt and "阅读约定" not in txt and html_
    opened = []
    win.result.opener = opened.append
    win.result._open_obsidian(); win.result._open_zotero()
    assert opened[0].toString().startswith("obsidian://open?vault=vault&file=litreader%2F")
    assert opened[1].toString() == "zotero://select/library/items/AAAA1111"
    win.result.tabs.buttons["usage"].click()
    assert win.result.stack.currentIndex() == 2
    assert win.home.recent.count() == 1
    win.close()


def test_window_cancel_at_cost_writes_nothing(app, tmp_path, kr, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "tok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")   # fake (W2: env is hermetic)
    calls = []
    cfg, kw, f = gui_fakes.environment(tmp_path, n=1, llm={"calls": calls})
    from litreader.gui.app import MainWindow
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.start_run(TEXT)
    spin(app, lambda: win.flow.req and win.flow.req["kind"] == "candidate")
    assert win.flow.opts.count() == 2   # 1 candidate + [q] 取消精读
    win.flow._answer("1")
    spin(app, lambda: win.flow.req and win.flow.req["kind"] == "cost")
    assert "已有解析缓存" not in win.flow.prompt.text()
    win.flow._answer("q")
    spin(app, lambda: win.flow.title.text() == "已取消")
    assert calls == [] and f.calls == [] and not cfg.dry_run_root.exists()
    win.close()


def test_models_page_vendor_dropdown_fills_url_and_saves_key_to_keychain_only(app, tmp_path, kr):
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    from litreader.gui.models_page import ModelsPage
    from litreader.llm import models as M
    page = ModelsPage(cfg, transport=lambda *a: (_ for _ in ()).throw(AssertionError("no network")))
    ed = page.editors["judge"]
    n0 = len(ed.cards)
    ed = ed._add()                                                   # G6: a new stacked slot card
    assert page.editors["judge"]._add() is ed and len(page.editors["judge"].cards) == n0 + 1   # one unsaved card at a time
    for vid, url in [("openai", "https://api.openai.com/v1"), ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai"),
                     ("anthropic", "https://api.anthropic.com/v1"), ("minimax_cn", "https://api.minimaxi.com/v1"),
                     ("minimax_intl", "https://api.minimax.io/v1"), ("deepseek", "https://api.deepseek.com"), ("custom", "")]:
        ed.vendor.setCurrentIndex(ed.vendor.findData(vid))
        assert ed.url.text() == url, vid
    ed.vendor.setCurrentIndex(ed.vendor.findData("anthropic"))
    ed.url.setText("https://api.anthropic.com/v1/")   # editable
    ed.model.setText("claude-test-model")
    fake_key = "test-" + "k" * 12
    ed.key.setText(fake_key)
    ed.pin.setText("3"); ed.pout.setText("15")
    ed._save()
    role_ed = page.editors["judge"]
    ed = role_ed.cards[-1]                                           # cards are rebuilt after saving
    assert ed.status.text().startswith("✅"), ed.status.text()
    assert not ed.key.isEnabled()                                     # masked; 更换 unlocks it
    assert "已保存" in ed.key_ref.text() and fake_key not in ed.key.placeholderText()
    text = cfg.models_path.read_text("utf-8")
    assert "claude-test-model" in text and 'key_ref = "ANTHROPIC_API_KEY"' in text and fake_key not in text
    assert kr.d[("litreader", "ANTHROPIC_API_KEY")] == fake_key and ed.key.text() == ""
    ms = M.load(cfg.models_path)
    s = ms.roles["judge"][-1]
    assert s.vendor == "Anthropic Claude" and s.price_in == 3.0
    # CLI shares it: same file, same preset match
    from litreader.llm import presets
    assert presets.by_vendor(s.vendor)["id"] == "anthropic"
    ed.vendor.setCurrentIndex(ed.vendor.findData("custom"))
    ed.custom_name.setText("")
    ed._save()
    assert ed.status.text().startswith("❌")


def test_avatar_default_custom_crop_and_reset(app, tmp_path):
    from PySide6.QtGui import QColor, QImage
    from litreader.gui import avatar as av
    from litreader.gui.prefs import Prefs
    p = Prefs(tmp_path)
    assert p.get("avatar") == "default" and not av.default_avatar().isNull()
    img = QImage(400, 200, QImage.Format_RGB32)
    img.fill(QColor("red"))
    src = tmp_path / "me.png"
    img.save(str(src))
    before = src.read_bytes()
    loaded = av.load_image(src)
    sq = av.crop_square(loaded, zoom=2.0, cx=0.9, cy=0.1)
    assert (sq.width(), sq.height()) == (256, 256)
    av.save_custom(sq, p)
    assert p.avatar_path.is_file() and Prefs(tmp_path).get("avatar") == "custom" and src.read_bytes() == before
    assert av.current(p).width() == 256
    av.reset_default(p)
    assert not p.avatar_path.exists() and Prefs(tmp_path).get("avatar") == "default" and src.is_file()
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    assert av.load_image(tmp_path / "x.gif") is None


def test_shiba_not_used_by_default():
    root = Path(__file__).resolve().parents[2]
    for f in (root / "src" / "litreader" / "gui").glob("*.py"):
        assert "app_icon" not in f.read_text("utf-8"), f


def test_preview_and_recent(tmp_path):
    md = "---\ntitle: x\n---\n# 标题\n![[_litreader_试运行/论文库/_图表/K/F1-1.png]]\n[[a/b|证据]] [[c/d]]\n> [!note]- 折叠\n%%x%%正文"
    out = runner.preview_markdown(md)
    assert out.startswith("# 标题") and "〔图：F1-1.png〕" in out and "证据" in out and "d" in out
    assert "**note**" in out and "%%" not in out and "title:" not in out
    j = tmp_path / "jobs" / "users_0__A"
    j.mkdir(parents=True)
    (j / "receipt-20261018T1.json").write_text('{"status": "DRY_RUN_COMPLETE", "note": "/v/n.md", "topic": {"folder": "t"}}', "utf-8")
    (j / "receipt-20261018T2.json").write_text('{"status": "CANCELLED", "stopped_at": "estimate"}', "utf-8")
    (j / "receipt-20261018T3.json").write_text("{bad", "utf-8")
    (j / "receipt-20261018T4.json").write_text('{"status": "PLANNED"}', "utf-8")
    r = runner.recent_receipts(tmp_path)
    # G6: stopped / cancelled runs are listed too (newest first); unknown statuses and bad JSON are skipped
    assert [x["status_code"] for x in r] == ["CANCELLED", "DRY_RUN_COMPLETE"]
    assert r[1]["topic"] == "t" and r[1]["row"]["status_kind"] == "ok"
    assert r[0]["row"]["status"].startswith("已取消") and r[0]["row"]["status_kind"] == "gray"


def test_cli_has_gui_command(monkeypatch, capsys):
    from litreader import cli
    monkeypatch.setitem(sys.modules, "litreader.gui.app", None)   # = PySide6 not installed
    assert cli.main(["gui"]) == 1
    assert ".[mac,gui]" in capsys.readouterr().out


def test_default_build_excludes_shiba_artwork():
    import subprocess
    root = Path(__file__).resolve().parents[2]
    attrs = subprocess.run(["git", "check-attr", "export-ignore", "assets/app_icon.png", "assets/app_icon_128.png",
                            "docs/design/ui_prototype/litreader_ui_prototype.html", "assets/litreader_icon.png"],
                           cwd=root, capture_output=True, text=True).stdout.splitlines()
    assert [a.endswith("set") for a in attrs] == [True, True, True, False]


def test_theme_tokens_icons_and_qss(app):
    """G3: one theme module; every icon the GUI names is bundled (Lucide, ISC licence file present) and tints."""
    import re
    from litreader.gui import theme
    gui = Path(theme.__file__).parent
    assert set(theme.LIGHT) == set(theme.DARK)
    assert (gui / "icons" / "LICENSE.txt").read_text("utf-8").startswith("ISC License")
    names = set()
    for f in gui.glob("*.py"):
        src = f.read_text("utf-8")
        names |= set(re.findall(r'icon=\"([a-z0-9-]+)\"', src)) | set(re.findall(r'set_icon\([^,]+, \"([a-z0-9-]+)\"', src))
        names |= set(re.findall(r'empty_state\(\s*\"([a-z0-9-]+)\"', src))
    from litreader.gui import app as gui_app, flow
    names |= {ic for *_, ic in gui_app.NAV} | set(flow.NODE_ICON.values())
    assert len(names) >= 15
    for n in names:
        assert (gui / "icons" / f"{n}.svg").is_file(), n
    pm = theme.icon_pixmap("house", "#ff0000", 18)
    img = pm.toImage()
    assert pm.width() == 36 and any(img.pixelColor(x, y).red() > 200 and img.pixelColor(x, y).alpha() > 0
                                    for x in range(36) for y in range(36))
    for dark in (False, True):
        q = theme.qss(dark)
        assert theme.palette(dark)["accent"] in q and "{" in q and "QPushButton[role=\"nav\"]:checked" in q
    # no stray hard-coded colours in page modules (all come from theme tokens)
    for f in gui.glob("*.py"):
        if f.name not in ("theme.py", "avatar.py"):
            assert not re.search(r'#[0-9a-fA-F]{6}\b', f.read_text("utf-8").replace("#ffffff", "")), f.name


def _tree_digest(root: Path) -> dict:
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()} if root.exists() else {}


def test_library_backend_matches_cli_and_is_read_only(tmp_path, kr, capsys, monkeypatch):
    from litreader import cli
    from litreader.gui import library as L
    cfg, _, _ = gui_fakes.environment(tmp_path)
    t = L.template_rows(cfg)
    ids = [r["id"] for r in t["rows"]]
    assert "main.general" in ids and [r["id"] for r in t["rows"] if r["default"]] == ["main.general"]
    monkeypatch.setattr("litreader.appconfig.load", lambda *_a, **_k: cfg)
    assert cli.main(["templates", "list"]) == 0
    out = capsys.readouterr().out
    assert all(i in out for i in ids)
    d = L.template_detail(cfg, "main.general")
    assert len(d["sections"]) >= 10 and d["sections"][0]["title"] and d["history"]
    rec = gui_fakes.sample_project(cfg)
    proj_root, vault = Path(cfg.data_dir) / "projects", Path(cfg.vault_root)
    before = (_tree_digest(proj_root), _tree_digest(vault))
    rows = L.project_rows(cfg)["rows"]
    assert [(r["id"], r["default"], r["version"]) for r in rows] == [(rec["id"], True, 2)]
    pd = L.project_detail(cfg, rec["id"])
    flat = {i["label"]: (i["value"], i["state"]) for m in pd["modules"] for i in m["items"]}
    assert flat["学科"] == ("康复医学（示例）", "CONFIRMED") and flat["临床/科研动机"][1] == "PENDING"
    assert [h["version"] for h in pd["history"]] == [1, 2]
    assert (_tree_digest(proj_root), _tree_digest(vault)) == before      # listing/showing never writes
    tpl_lib_before = _tree_digest(vault)
    res = L.refresh_templates(cfg)
    assert res["snapshot"] >= 1 and _tree_digest(vault) == tpl_lib_before   # refresh only touches the app-data registry


def test_library_page_offscreen(app, tmp_path, kr):
    from litreader.gui.library_page import LibraryPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    page = LibraryPage(cfg)
    assert page.tabs.count() == 2 and [page.tabs.tabText(i) for i in range(2)] == ["模板库", "项目库"]
    tt = page.templates
    assert tt.list.count() == len(tt.rows) >= 3 and "★ 默认" in tt.list.item(0).text()
    from PySide6.QtWidgets import QLabel
    texts = [w.text() for w in tt.findChildren(QLabel)]
    assert any("章节预览" in x for x in texts)
    tt.refresh()
    assert tt.status.text().startswith("✅ 已刷新")
    assert not hasattr(page.projects, "list")          # no projects yet -> empty state
    gui_fakes.sample_project(cfg)
    page2 = LibraryPage(cfg)
    assert page2.projects.list.count() == 1 and page2.projects.list.item(0).text().startswith("★ 示例课题")
    page.close(); page2.close()


def test_library_page_without_config(app):
    from litreader.gui.library_page import LibraryPage
    p = LibraryPage(None, "没有配置")
    assert p.tabs is None


# ----- G5: Zotero 一键检测, parser tokens, app icon (no network: fake prefs dir + fake local-API opener) -----

def _labels(w):
    from PySide6.QtWidgets import QLabel, QPushButton
    return [x.text() for x in w.findChildren(QLabel) if not x.isHidden()] + \
           [b.text() for b in w.findChildren(QPushButton) if not b.isHidden()]   # cleared widgets are hidden first


def _zotero_fakes(tmp_path, api="true", data=True):
    from test_zotero_setup import mac_home
    from litreader.zotero import setup as zs
    home, prefs, dd = mac_home(tmp_path, api=api, data=data)
    return (lambda: zs.detect("darwin", home)), prefs, dd


@pytest.mark.parametrize("which,status,expect", [("op_403", "DISABLED", "允许此计算机上的其他应用程序与 Zotero 通讯"),
                                                 ("op_down", "NOT_RUNNING", "打开 Zotero"),
                                                 ("op_ok", "OK", "本地接口可用")])
def test_zotero_card_detect_states_and_guidance(app, tmp_path, kr, which, status, expect):
    import test_zotero_setup as T
    from litreader.gui.setup_panels import ZoteroSetupCard
    cfg, _, _ = gui_fakes.environment(tmp_path)
    det, prefs, dd = _zotero_fakes(tmp_path / "z")
    before = (prefs.read_bytes(), prefs.stat().st_mtime_ns)
    w = ZoteroSetupCard(cfg, detect_fn=det, opener=getattr(T, which))
    assert w.btn.text() == "一键检测 Zotero"
    w.run()
    spin(app, lambda: w.result is not None)
    d, pr = w.result
    assert pr["status"] == status and d["valid"] and d["data_dir"] == dd
    text = "\n".join(_labels(w))
    assert expect in text and "找到数据目录" in text and w.btn.text() == "重新检测"
    if status == "DISABLED":
        assert "Zotero 设置" in text and "高级" in text and "不会替你改 Zotero 设置" in text and "重新检测" in text
    assert (prefs.read_bytes(), prefs.stat().st_mtime_ns) == before          # Zotero never modified
    w.close()


def test_zotero_card_not_found_offers_no_save(app, tmp_path, kr):
    import test_zotero_setup as T
    from litreader.gui.setup_panels import ZoteroSetupCard
    cfg, _, _ = gui_fakes.environment(tmp_path)
    det, _, _ = _zotero_fakes(tmp_path / "z", data=False)
    w = ZoteroSetupCard(cfg, detect_fn=det, opener=T.op_down)
    w.run()
    spin(app, lambda: w.result is not None)
    text = "\n".join(_labels(w))
    assert "没找到数据目录" in text and "手动选择数据目录" in text and "暂不提供保存" in text
    assert not hasattr(w, "save_btn")


def test_zotero_card_saves_only_after_confirm_with_backup(app, tmp_path, kr):
    import test_zotero_setup as T
    from litreader.gui.setup_panels import ZoteroSetupCard
    cfg, _, _ = gui_fakes.environment(tmp_path)
    det, _, dd = _zotero_fakes(tmp_path / "z")
    cfgp = Path(cfg.path)
    orig = cfgp.read_bytes()
    w = ZoteroSetupCard(cfg, detect_fn=det, opener=T.op_ok)
    saved = []
    w.saved.connect(saved.append)
    w.run()
    spin(app, lambda: w.result is not None)
    assert w.pending[1] and any("data_dir" in c for c in w.pending[1])
    w._save(confirm=lambda: False)                                          # user said no
    assert cfgp.read_bytes() == orig and not list(cfgp.parent.glob("*.bak-*")) and not saved
    w._save(confirm=lambda: True)
    import tomllib
    assert tomllib.loads(cfgp.read_text("utf-8"))["zotero"]["data_dir"] == Path(dd).as_posix()
    baks = list(cfgp.parent.glob(cfgp.name + ".bak-*"))
    assert len(baks) == 1 and baks[0].read_bytes() == orig and saved and not w.save_btn.isEnabled()
    w2 = ZoteroSetupCard(cfg, detect_fn=det, opener=T.op_ok)            # already up to date -> nothing to save
    w2.run()
    spin(app, lambda: w2.result is not None)
    assert not w2.pending[1] and "设置已正确，无需保存" in "\n".join(_labels(w2))
    assert w.save_btn.text() == "保存检测结果" and "config.local.toml" not in w.save_btn.text()


def test_obsidian_card_checks_vault_and_saves_with_confirm(app, tmp_path, kr, monkeypatch):
    from litreader.gui.setup_panels import ObsidianCard
    cfg, _, _ = gui_fakes.environment(tmp_path)
    cfgp = Path(cfg.path)
    orig = cfgp.read_bytes()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    w = ObsidianCard(cfg)
    assert w.pending is None and "无需保存" in "\n".join(_labels(w))          # current vault, unchanged
    other = tmp_path / "OtherVault"
    other.mkdir()
    w.path.setText("~/OtherVault")
    assert "不像 Obsidian 库" in "\n".join(_labels(w)) and w.pending              # warn, but still allowed
    (other / ".obsidian").mkdir()
    w.check()
    assert "不像 Obsidian 库" not in "\n".join(_labels(w))
    w._save(confirm=lambda: False)
    assert cfgp.read_bytes() == orig
    w._save(confirm=lambda: True)
    import tomllib
    assert tomllib.loads(cfgp.read_text("utf-8"))["vault"]["root"] == "~/OtherVault"
    assert len(list(cfgp.parent.glob(cfgp.name + ".bak-*"))) == 1
    w.path.setText(str(other))                                     # same folder spelled absolutely → no change
    assert w.pending is None and "无需保存" in "\n".join(_labels(w))
    assert not list(other.iterdir()) == [] and [p.name for p in other.iterdir()] == [".obsidian"]   # nothing written


def test_zotero_card_without_config_detects_but_cannot_save(app, tmp_path):
    import test_zotero_setup as T
    from litreader.gui.setup_panels import ZoteroSetupCard
    det, _, _ = _zotero_fakes(tmp_path / "z")
    w = ZoteroSetupCard(None, "没有配置", detect_fn=det, opener=T.op_403)
    w.run()
    spin(app, lambda: w.result is not None)
    assert "先按《Mac 运行指南》" in "\n".join(_labels(w)) and not hasattr(w, "save_btn")


def test_parser_tokens_saved_to_keychain_never_displayed(app, tmp_path, kr, monkeypatch):
    from litreader.gui.models_page import ParserPanel
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    monkeypatch.delenv("PADDLE_API_KEY", raising=False)
    card = ParserPanel(None)                                          # G6: 模型设置 → 解析器
    mineru, paddle = card.rows
    assert (mineru.ref, paddle.ref) == ("MINERU_API_TOKEN", "PADDLE_API_KEY")
    assert mineru.token_url == "https://mineru.net/apiManage/token" and paddle.token_url == "https://aistudio.baidu.com/index/accessToken"
    assert mineru.status.text() == "未读取（用到时再读）" and mineru.edit.echoMode() == mineru.edit.EchoMode.Password
    texts = "\n".join(_labels(card))
    assert "当前使用" in texts and "尚未接入" in texts and "接口文档 ↗" in texts
    secret = "fake-mineru-" + "x" * 12                                   # fake value; nothing real
    mineru.edit.setText(secret)
    mineru.save()
    assert kr.get_password("litreader", "MINERU_API_TOKEN") == secret
    assert mineru.edit.text() == "" and mineru.status.text() == "钥匙串已保存" and paddle.status.text() == "未读取（用到时再读）"
    assert not mineru.edit.isEnabled()
    mineru._unlock()
    assert mineru.edit.isEnabled()
    assert all(secret not in t for t in _labels(card)) and secret not in mineru.edit.placeholderText()
    monkeypatch.setenv("PADDLE_API_KEY", "fake-env")
    paddle.refresh()
    assert paddle.status.text() == "来自环境变量"
    card.close()


def test_settings_page_has_detect_and_obsidian_not_appearance_or_tokens(app, tmp_path, kr):
    from litreader.gui.prefs import Prefs
    from litreader.gui.settings_page import SettingsPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    p = SettingsPage(cfg, Prefs(tmp_path / "prefs"))
    text = "\n".join(_labels(p))
    assert "一键检测 Zotero" in text and "库（vault）路径" in text and "笔记文件夹" in text and "论文写入位置" in text and "下一版" not in text
    # G6: 外观 → sidebar toggle; parser tokens → 模型设置 → 解析器
    assert "深浅色" not in text and "解析器 Token" not in text and not hasattr(p, "appearance")


def test_app_icon_and_macos_helpers_fallback(app, monkeypatch):
    import types
    from litreader.gui import app as gapp
    from litreader.gui import macos
    ic = gapp.brand_icon()
    assert not ic.isNull() and gapp.brand_png(64)[:8] == b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(macos.sys, "platform", "linux")
    assert macos.set_dock_icon(b"x") is False and macos.set_app_name_early() is False
    # fake AppKit/Foundation on "darwin": the helpers call the right Cocoa APIs
    calls, info = [], {}

    class Img:
        @staticmethod
        def alloc(): return Img()
        def initWithData_(self, d): calls.append(("img", d)); return self

    class NSApp:
        @staticmethod
        def sharedApplication(): return NSApp()
        def setApplicationIconImage_(self, img): calls.append(("dock", img))

    class Bundle:
        @staticmethod
        def mainBundle(): return Bundle()
        def localizedInfoDictionary(self): return None
        def infoDictionary(self): return info

    class Data:
        @staticmethod
        def dataWithBytes_length_(b, n): return ("data", n)
    monkeypatch.setattr(macos.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "AppKit", types.SimpleNamespace(NSImage=Img, NSApplication=NSApp))
    monkeypatch.setitem(sys.modules, "Foundation", types.SimpleNamespace(NSBundle=Bundle, NSData=Data))
    assert macos.set_app_name_early("Litreader") and info["CFBundleName"] == "Litreader"
    assert macos.set_dock_icon(b"png!") and calls[0] == ("img", ("data", 4)) and calls[1][0] == "dock"
    monkeypatch.setitem(sys.modules, "AppKit", None)                    # pyobjc missing -> silently no-op
    assert macos.set_dock_icon(b"png!") is False


def test_gui_extra_pulls_pyobjc_only_on_macos():
    import tomllib
    root = Path(__file__).resolve().parents[2]
    gui = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["optional-dependencies"]["gui"]
    assert any(x.startswith("pyobjc-framework-Cocoa") and "sys_platform == 'darwin'" in x for x in gui)


def test_sidebar_version_and_appearance_toggle_persist(app, tmp_path, kr):
    from litreader import __version__
    from litreader.gui.app import MainWindow
    from litreader.gui.prefs import Prefs
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    assert win.version_label.text() == f"Litreader v{__version__}" and __version__ == "1.0.3"
    assert list(win.appearance_seg.buttons) == ["light", "dark", "system"]
    assert [b.text() for b in win.appearance_seg.buttons.values()] == ["浅色", "深色", "跟随系统"]
    win.appearance_seg.buttons["dark"].click()
    from litreader.gui import theme
    assert theme.is_dark() and Prefs(tmp_path / "guidata").get("appearance") == "dark"
    win.appearance_seg.buttons["light"].click()
    assert not theme.is_dark() and win.appearance_actions["light"].isChecked()
    from PySide6.QtWidgets import QWidget
    assert "试运行模式" not in "\n".join(_labels(win.findChild(QWidget, "Sidebar")))   # trial badge left the sidebar
    win.close()


def test_recent_table_rows_fixed_columns_and_status_pills(app, tmp_path, kr):
    from litreader.gui.app import MainWindow
    from litreader.gui.home import COLS
    cfg, kw, _ = gui_fakes.environment(tmp_path)
    gui_fakes.seed_recent(cfg)
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp_path / "guidata")
    win.show()
    win.resize(1180, 820)
    for _ in range(10):
        app.processEvents()
    rl = win.home.recent
    assert rl.count() == 2 and [h for h, _ in COLS] == ["论文", "状态", "主题文件夹", "日期", "抽取完整度"]
    head = rl.v.itemAt(0).widget().layout()
    xs = lambda lay: [lay.itemAt(i).widget().x() for i in range(lay.count())]  # noqa: E731
    for row in rl.rows:                                        # every row lines up with the header, even long titles
        assert xs(row.layout()) == xs(head)
    texts = "\n".join(_labels(rl))
    assert "已停止：E0" in texts and "已取消（估算后）" in texts and "Chen 2019 · Sample Gait J · 条目 SAMPLE02" in texts
    assert "2026-10-16" in texts and "T09" not in texts and "指令：" not in texts
    win.close()


def test_library_new_template_and_project_dialogs(app, tmp_path, kr, monkeypatch):
    from litreader.gui import library_dialogs as D
    from litreader.gui.library_page import LibraryPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    vault = tmp_path / "vault"
    before = _tree_digest(vault)
    d = D.NewTemplateDialog(cfg)
    assert d.base.itemData(d.base.count() - 1) is None and d.base.currentData() is not None
    assert d.secs.count() >= 8                       # outline copied from the base
    d._save()
    assert d.result is None and "名称" in d.err.text()
    d.name.setText("我的模板")
    d.secs.setCurrentRow(0); d._del(); d._add()
    d._save()
    assert d.result and d.result["id"].startswith("user.main.")
    d.role.setCurrentIndex(1); d.base.setCurrentIndex(d.base.count() - 1)
    assert d.secs.count() == 1
    p = D.NewProjectDialog(cfg)
    p._save()
    assert p.result is None and "题目" in p.err.text()
    p.name.setText("示例新课题"); p.fields["population"].setText("社区老年人"); p.default.setChecked(True)
    p._save()
    assert p.result["version"] == 2 and p.result["default"]
    after = {k: v for k, v in _tree_digest(vault).items() if not k.startswith("litreader/")}
    assert after == before                           # only the output folder gets project views
    monkeypatch.setattr(D.NewProjectDialog, "exec", lambda self: (self.name.setText("又一个课题"), self._save(), 1)[2])
    page = LibraryPage(cfg)
    page.projects.new_project()
    assert page.projects.list.count() == 2
    page.close()
