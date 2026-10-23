"""G6 backend logic: path normalisation, config edits, template / project creation, flow step mapping,
notification gating. No Qt needed except where marked; no network, no paid API."""
from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_realrun import MemKeyring  # noqa: E402

from litreader import configedit, secrets  # noqa: E402
from litreader.gui import flow_steps as FS  # noqa: E402
from litreader.zotero import setup as zs  # noqa: E402


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


# ---------- path normalisation ----------
def test_norm_path_tilde_equals_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Zotero").mkdir()
    assert configedit.same_path("~/Zotero", str(tmp_path / "Zotero"))
    assert configedit.same_path(str(tmp_path / "Zotero") + "/", "~/Zotero/")
    assert configedit.same_path("~/./Zotero", "~/Zotero")
    assert not configedit.same_path("~/Zotero", "~/Zotero2")
    assert configedit.norm_url("http://localhost:23119/api/") == configedit.norm_url("http://LOCALHOST:23119/api")


def test_zotero_config_updates_ignore_equivalent_spelling(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    text = '[zotero]\ndata_dir = "~/Zotero"\napi_base = "http://localhost:23119/api/"\n\n[obsidian]\nvault_root = "~/v"\n'
    new, ch = zs.config_updates(text, tmp_path / "Zotero", "http://localhost:23119/api")
    assert ch == [] and new == text            # 设置已正确，无需保存
    new, ch = zs.config_updates(text, tmp_path / "Other", "http://localhost:23119/api")
    assert len(ch) == 1 and "data_dir" in ch[0] and tomllib.loads(new)["zotero"]["data_dir"] == (tmp_path / "Other").as_posix()
    assert tomllib.loads(new)["obsidian"]["vault_root"] == "~/v"     # other sections untouched


def test_vault_updates_and_check(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    v = tmp_path / "MyVault"
    v.mkdir()
    text = '[zotero]\ndata_dir = "~/Zotero"\n\n[vault]\nroot = "~/MyVault"\npapers_dir = "论文库"\n'
    new, ch = configedit.vault_updates(text, v)
    assert ch == [] and new == text
    info = configedit.check_vault(v, "论文库", "_litreader_试运行")
    assert info["exists"] and not info["is_vault"]          # no .obsidian → GUI warns
    (v / ".obsidian").mkdir()
    assert configedit.check_vault(v, "论文库", "_litreader_试运行")["is_vault"]
    new, ch = configedit.vault_updates(text, tmp_path / "Other")
    assert ch and tomllib.loads(new)["vault"]["root"] == (tmp_path / "Other").as_posix()
    assert tomllib.loads(new)["vault"]["papers_dir"] == "论文库"
    new, ch = configedit.vault_updates("[zotero]\ndata_dir = \"x\"\n", v)    # section added when missing
    assert ch and tomllib.loads(new)["vault"]["root"] == str(v)


# ---------- template / project creation ----------
def _builtin_bytes():
    from litreader.templates import registry
    root = Path(registry.__file__).parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*.md")}


def test_create_template_based_on_and_blank(tmp_path, kr):
    from litreader.gui import library as L
    cfg, _, _ = gui_fakes.environment(tmp_path)
    before = _builtin_bytes()
    vault_before = sorted(p for p in (tmp_path / "vault").rglob("*"))
    outline = L.base_outline(cfg, "main.general", "MAIN_NOTE")
    assert len(outline) >= 8
    r = L.create_template(cfg, title="我的步态模板", role="MAIN_NOTE", base_id="main.general",
                          sections=outline[:5] + ["新增：临床意义"])
    assert r["id"].startswith("user.main.") and r["version"] == 1 and r["status"] == "ACTIVE"
    secs = L.template_detail(cfg, r["id"])["sections"]
    assert [s["id"] for s in secs][:5] == ["s1", "s2", "s3", "s4", "s5"] and secs[-1]["id"].startswith("x")
    r2 = L.create_template(cfg, title="我的步态模板", role="MAIN_NOTE", base_id="main.general", sections=outline)
    assert r2["id"] != r["id"]                                   # ids never collide
    m = L.create_template(cfg, title="空白模块", role="MODULE", base_id=None, sections=["模块A"])
    assert m["id"].startswith("user.module.")
    with pytest.raises(ValueError):
        L.create_template(cfg, title="x", role="MODULE", base_id="main.general", sections=["a"])
    rows = {x["id"]: x for x in L.template_rows(cfg)["rows"]}
    assert r["id"] in rows and "main.general" in rows
    assert _builtin_bytes() == before                            # frozen builtins (Yang-based main.general) unchanged
    assert sorted(p for p in (tmp_path / "vault").rglob("*")) == vault_before   # registry only, nothing in the vault
    assert Path(r["registry"]).is_relative_to(cfg.data_dir)


def test_create_project_versioned_with_fields(tmp_path, kr):
    from litreader.gui import library as L
    cfg, _, _ = gui_fakes.environment(tmp_path)
    p = L.create_project(cfg, "示例课题：步态", {"core_question": "步速能否预测跌倒（示例）", "population": "社区老年人",
                                                "design": ""}, True)
    assert p["version"] == 2 and p["default"]                    # v1 create + v2 confirmed fields
    q = L.create_project(cfg, "空课题", {}, False)
    rows = {r["id"]: r for r in L.project_rows(cfg)["rows"]}
    assert rows[p["id"]]["title"] == "示例课题：步态"
    assert rows[p["id"]]["counts"]["CONFIRMED"] == rows[q["id"]]["counts"]["CONFIRMED"] + 2   # the 2 filled fields
    assert Path(p["folder"]).is_relative_to(cfg.dry_run_root)    # views only in the trial folder
    assert q["version"] == 1 and not q["default"]
    with pytest.raises(ValueError):
        L.create_project(cfg, "  ", {}, False)


# ---------- flow step mapping ----------
def _ev(tr, t, **d):
    return tr.feed(t, d)


def test_flow_step_mapping_and_skips():
    assert [t for _, t in FS.STEPS] == ["选择论文", "关联课题", "费用估算", "解析 E0–E3", "类型与模板", "精读进度",
                                        "作者冲突", "主题文件夹", "完成"]
    from litreader import events
    assert set(FS.STAGE_STEP) == set(events.STAGES)              # every pipeline stage lands on a step
    assert set(FS.KIND_STEP) <= set(events.KINDS)
    tr = FS.Tracker()
    _ev(tr, "decision_request", kind="candidate", data={"candidates": []})
    assert tr.current == "select" and tr.state["select"] == "active"
    _ev(tr, "stage", stage="zotero", status="done", item_key="K1")
    _ev(tr, "stage", stage="project", status="skip")
    _ev(tr, "stage", stage="estimate")
    _ev(tr, "decision_request", kind="cost", data={"roles": []})
    assert tr.state["select"] == "done" and tr.state["project"] == "skip" and tr.current == "estimate"
    for s in ("parse", "template"):
        _ev(tr, "stage", stage=s)
        _ev(tr, "stage", stage=s, status="done")
    _ev(tr, "stage", stage="writer")
    _ev(tr, "progress", stage="writer", done=1, total=2, tokens_in=10)
    assert tr.current == "reading" and tr.data["reading"]["progress"]["writer"]["done"] == 1
    _ev(tr, "stage", stage="topic")                                # no author conflict event at all
    assert tr.state["author"] == "skip" and tr.state["reading"] == "done"
    _ev(tr, "done")
    assert all(v in ("done", "skip") for v in tr.state.values()) and tr.state["done"] == "done"
    assert tr.data["select"]["zotero"]["item_key"] == "K1"


# ---------- notifications ----------
def test_should_notify_respects_toggles_and_focus():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from litreader.gui.app import should_notify
    prefs = {"notify": True, "notify_decision": True, "notify_done": False}
    assert should_notify(prefs, "decision", active=False, tray_ok=True)
    assert not should_notify(prefs, "decision", active=True, tray_ok=True)      # app in front → in-app only
    assert not should_notify(prefs, "done", active=False, tray_ok=True)         # per-event toggle off
    assert not should_notify({**prefs, "notify": False}, "decision", active=False, tray_ok=True)
    assert not should_notify(prefs, "decision", active=False, tray_ok=False)


# ---------- result page helpers (Qt-free) ----------
def test_note_html_callouts_chips_links_and_uris(tmp_path):
    from types import SimpleNamespace
    from litreader.gui import note_html as N
    from litreader.gui.theme import DARK, LIGHT
    md = ("---\ntitle_zh: x\n---\n# 示例标题\n*Sample title*\n> [!info] 论文信息\n> **作者／年份：** UNKNOWN\n\n"
          "> [!abstract] 三分钟了解论文\n> 研究什么：示例（PAPER） [方法p4](zotero://open-pdf/library/items/ATT1?page=4)\n\n"
          "> [!note] 阅读约定\n> **PAPER** 原文 · **INFERENCE** 推断\n\n## 二、方法\n| a | b |\n|---|---|\n| 1 | 2 |\n"
          "![[_litreader_试运行/论文库/_图表/K/F1.png]]\n")
    for pal in (LIGHT, DARK):
        h = N.render(md, pal, dark=pal is DARK)
        assert pal["accent"] in h and pal["teal"] in h and pal["info"] in h          # blue / teal / purple strips
        assert 'href="zotero://open-pdf/library/items/ATT1?page=4"' in h and "方法p4" in h
        assert h.count("&nbsp;PAPER&nbsp;") == 2 and "&nbsp;UNKNOWN&nbsp;" in h and "&nbsp;INFERENCE&nbsp;" in h
        assert "title_zh" not in h and "〔图：F1.png〕" in h and "<table" in h
    assert N.tag_counts(md) == {"PAPER": 2, "INFERENCE": 1, "UNKNOWN": 1}
    vault = tmp_path / "My Vault"
    note = vault / "_litreader_试运行" / "论文库" / "主题" / "示例 笔记.md"
    assert N.vault_root_of(note) == vault
    assert N.obsidian_uri(note) == ("obsidian://open?vault=My%20Vault&file="
                                    "_litreader_%E8%AF%95%E8%BF%90%E8%A1%8C%2F%E8%AE%BA%E6%96%87%E5%BA%93%2F"
                                    "%E4%B8%BB%E9%A2%98%2F%E7%A4%BA%E4%BE%8B%20%E7%AC%94%E8%AE%B0")
    assert N.obsidian_uri(tmp_path / "x.md").startswith("obsidian://open?path=")
    assert N.vault_root_of(note, SimpleNamespace(vault_root=vault)) == vault
    assert N.item_key_of({"paper": {"item_key": "ABCD1234"}}) == "ABCD1234"
    assert N.item_key_of({"paper": {"item_key": "UNKNOWN"}}) is None
    assert N.zotero_uri("ABCD1234") == "zotero://select/library/items/ABCD1234"
    img = vault / "_litreader_试运行" / "论文库" / "_图表" / "K" / "F1.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\x89PNG")
    assert N.image_resolver(note)("_litreader_试运行/论文库/_图表/K/F1.png") == img.resolve().as_uri()
