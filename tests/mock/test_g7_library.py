"""G7-5: 模板库/项目库 right-click actions — built-ins only copy; user templates edit/rename/delete (soft);
projects rename / copy / delete (= archive, versioned) / restore. The vault 模板库 folder is never written."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import gui_fakes  # noqa: E402
from test_realrun import MemKeyring  # noqa: E402

from litreader import secrets  # noqa: E402
from litreader.gui import library as L  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    return k


def _tree_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")) if p.exists() else []:
        if f.is_file():
            h.update(f.relative_to(p).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def test_template_menu_builtin_copy_only_and_user_soft_delete(app, tmp_path, kr):
    from litreader.gui.library_page import LibraryPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    lib_dir = cfg.vault_root / cfg.templates_dir if cfg.templates_dir else tmp_path / "none"
    before = _tree_hash(lib_dir)
    page = LibraryPage(cfg)
    tt = page.templates
    bi = next(i for i, r in enumerate(tt.rows) if L.template_source(cfg, r["id"]) == "builtin")
    acts = {t: en for t, en, _ in tt.menu_actions(bi)}
    assert acts == {"修改…": False, "重命名…": False, "复制为新模板": True, "删除…": False}
    tt.do("复制为新模板", bi)
    assert tt.status.text().startswith("✅ 已复制为新模板")
    ui = next(i for i, r in enumerate(tt.rows) if L.template_source(cfg, r["id"]) == "user")
    uid = tt.rows[ui]["id"]
    assert all(en for _, en, _ in tt.menu_actions(ui))
    tt.do("重命名…", ui, value="我的新名字")
    assert tt.status.text().startswith("✅ 已重命名")
    titles = [r["title"] for r in tt.rows]
    assert "我的新名字" in titles and uid not in [r["id"] for r in tt.rows]      # old one disabled (hidden)
    j = titles.index("我的新名字")
    tt.do("删除…", j, confirm=False)                                             # declined -> nothing
    assert "我的新名字" in [r["title"] for r in tt.rows]
    tt.do("删除…", j, confirm=True)
    assert "我的新名字" not in [r["title"] for r in tt.rows]
    all_rows = L.template_rows(cfg, show_all=True)["rows"]
    assert any(r["title"] == "我的新名字" and r["status"] == "DISABLED" for r in all_rows)   # soft
    assert _tree_hash(lib_dir) == before


def test_project_menu_rename_copy_delete_restore(app, tmp_path, kr):
    from litreader.gui.library_page import LibraryPage
    cfg, _, _ = gui_fakes.environment(tmp_path)
    gui_fakes.sample_project(cfg)
    page = LibraryPage(cfg)
    pt = page.projects
    pid = pt.rows[0]["id"]
    pt.do("重命名…", 0, value="新的课题题目")
    assert pt.rows[0]["title"] == "新的课题题目"
    pt.do("复制", 0)
    assert len(pt.rows) == 2 and any(r["title"].endswith("（副本）") for r in pt.rows)
    i = [r["id"] for r in pt.rows].index(pid)
    pt.do("删除…", i, confirm=True)
    r = next(r for r in pt.rows if r["id"] == pid)
    assert r["archived"] and not r["default"]
    d = L.project_detail(cfg, pid)
    assert len(d["history"]) >= 3                                              # versions kept
    i = [r["id"] for r in pt.rows].index(pid)
    assert [t for t, _, _ in pt.menu_actions(i)][0] == "恢复（取消归档）"
    pt.do("恢复（取消归档）", i)
    assert not next(r for r in pt.rows if r["id"] == pid)["archived"]
