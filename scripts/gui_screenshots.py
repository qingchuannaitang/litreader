#!/usr/bin/env python3
"""Offscreen screenshots of GUI v1 driven by the REAL pipeline with local fakes (no network, no paid API).
  QT_QPA_PLATFORM=offscreen python scripts/gui_screenshots.py /workspace/ui_shots
Sample data only (invented titles marked 示例/sample)."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "mock")]
for k in ("MINERU_API_TOKEN", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "PADDLE_API_KEY"):
    os.environ[k] = "fake-local-only"          # fakes never send them anywhere; real keys are not read

from PySide6.QtWidgets import QApplication  # noqa: E402

import gui_fakes  # noqa: E402
from test_realrun import MemKeyring  # noqa: E402
from litreader import secrets  # noqa: E402

_kr = MemKeyring()
secrets._keyring = lambda: _kr
TEXT = "精读zotero中的 gait，并将精读笔记存入obsidian中"


def spin(app, cond, timeout=20):
    t = time.time()
    while not cond():
        app.processEvents()
        if time.time() - t > timeout:
            raise SystemExit("timeout")
        time.sleep(0.01)
    for _ in range(5):
        app.processEvents()


def main(out: Path, prefix: str = "gui_v2"):
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    from litreader.gui.app import MainWindow
    shots = []
    for mode in ("light", "dark"):
        tmp = Path(tempfile.mkdtemp(prefix=f"litreader_gui_{mode}_"))
        gate = threading.Event()
        cfg, kw, _ = gui_fakes.environment(tmp, llm={"writer_gate": gate})
        gui_fakes.sample_project(cfg)
        win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp / "guidata")
        win.set_appearance(mode)
        win.show()
        win.resize(1180, 820)

        def snap(name):
            for _ in range(6):     # let pending layout requests of a freshly shown page run
                app.processEvents()
                time.sleep(0.01)
            p = out / f"{prefix}_{name}_{mode}.png"
            win.grab().save(str(p))
            shots.append(p)

        snap("home_empty")
        win.go("flow"); snap("flow_0_empty")
        win.go("result"); snap("result_empty")
        win.go("home")
        win.home.input.setText(TEXT)
        win.home._submit()
        want = lambda k: (lambda: win.flow.req is not None and win.flow.req["kind"] == k)  # noqa: E731
        spin(app, want("candidate")); snap("flow_1_candidate"); win.flow._answer("1")
        spin(app, want("cost")); snap("flow_2_cost"); win.flow._answer("y")
        spin(app, want("template")); win.flow._answer("")
        spin(app, lambda: win.flow.nodes.state["writer"] == "running"); time.sleep(0.2); snap("flow_3_streaming")
        gate.set()
        spin(app, want("topic_folder")); snap("flow_4_topic")
        win.flow._answer("")
        spin(app, lambda: win.last_result is not None and not win.running)
        snap("flow_5_done")
        win.go("result"); snap("result")
        gui_fakes.seed_recent(cfg); win.refresh_recent()
        win.go("result"); snap("result_list")
        win.result.list.select(0); snap("result_selected")
        win.result.open_drawer(win.result.r, "note"); snap("result_drawer_note")
        win.result.drawer.tabs.buttons["usage"].click(); snap("result_drawer_usage")
        win.result.close_drawer()
        win.go("home"); snap("home_recent")
        win.go("models"); snap("models")
        win.models.tabs.buttons["parser"].click(); snap("models_parser")
        win.models.tabs.buttons["writer"].click()
        win.go("settings"); snap("settings")
        win.go("library"); snap("library_templates")
        win.library.tabs.setCurrentIndex(1); snap("library_projects")
        from litreader.gui.library_page import BulkFillDialog, FieldRow
        rows = win.library.projects.findChildren(FieldRow)
        if rows:
            rows[0].start_edit(); snap("library_project_edit")
            rows[0].stack.setCurrentIndex(0)
        win.go("home"); win.home.count.setCurrentIndex(2)
        win.home.input.setText("精读zotero中的 示例论文A\n精读zotero中的 示例论文B"); snap("home_batch")
        win.home.input.clear(); win.home.count.setCurrentIndex(0)
        bf = BulkFillDialog(win.library.projects)
        bf.text.setPlainText("（示例）本课题关注社区老年人的步态与认知。\n研究对象为 65 岁以上社区老年人。")
        bf.show(); bf.adjustSize()
        for _ in range(6):
            app.processEvents(); time.sleep(0.01)
        p = out / f"{prefix}_dlg_bulk_fill_{mode}.png"
        bf.grab().save(str(p)); shots.append(p); bf.close()
        from litreader.gui.library_dialogs import NewProjectDialog, NewTemplateDialog
        for nm, D in (("dlg_new_template", NewTemplateDialog), ("dlg_new_project", NewProjectDialog)):
            dlg = D(cfg, win)
            dlg.show(); dlg.adjustSize()
            for _ in range(6):
                app.processEvents(); time.sleep(0.01)
            p = out / f"{prefix}_{nm}_{mode}.png"
            dlg.grab().save(str(p)); shots.append(p); dlg.close()
        win.close()
    for p in shots:
        print(p)


def settings_shots(out: Path, prefix: str = "gui_v3"):
    """基础设置 after a fake 一键检测 (Zotero running, local API off -> guidance) + parser tokens (one saved)."""
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    import test_zotero_setup as T
    from litreader.zotero import setup as zs
    from litreader.gui.app import MainWindow
    for k in ("MINERU_API_TOKEN", "PADDLE_API_KEY"):
        os.environ.pop(k, None)
    _kr.set_password("litreader", "MINERU_API_TOKEN", "fake-local-only")
    shots = []
    for mode in ("light", "dark"):
        tmp = Path(tempfile.mkdtemp(prefix=f"litreader_set_{mode}_"))
        cfg, kw, _ = gui_fakes.environment(tmp)
        home, _, _ = T.mac_home(tmp / "z")
        win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp / "guidata",
                         zotero_detect=lambda: zs.detect("darwin", home), zotero_opener=T.op_403)
        win.set_appearance(mode)
        win.show()
        win.go("settings")
        z = win.settings.zotero
        z.run()
        spin(app, lambda: z.result is not None)
        for name, h in (("settings", 820), ("settings_full", 1720)):
            win.resize(1180, h)
            for _ in range(8):
                app.processEvents()
                time.sleep(0.01)
            if name == "settings":
                area = win.settings.findChild(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)
                if area is not None:
                    area.ensureWidgetVisible(z, 0, 0)
                    area.verticalScrollBar().setValue(z.mapTo(area.widget(), z.rect().topLeft()).y() - 24)
                    for _ in range(4):
                        app.processEvents()
            p = out / f"{prefix}_{name}_{mode}.png"
            win.grab().save(str(p))
            shots.append(p)
        win.close()
    for p in shots:
        print(p)


def g8_shots(out: Path, prefix: str = "gui_v6"):
    """G8: 关于与反馈 card, 💬 popover, update notice, keyword candidate list, 「修改指令」 button.
    The update info is a local fake (no network)."""
    import json
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QScrollArea
    from litreader.gui.app import MainWindow
    fake = {"version": "0.7.0", "notes": "（示例）新增批量导出与若干修复", "download_url": "https://example.com/litreader-0.7.0.zip",
            "qq_group": "1126184965"}
    from litreader.zotero.client import ZoteroClient
    _search = ZoteroClient.search
    # the shared fake library returns every item for any query; filter by title words so the
    # exact-title miss -> keyword fallback path is what the screenshot shows
    ZoteroClient.search = lambda self, q, *a, **k: [c for c in _search(self, q, *a, **k)
                                                     if str(q).lower() in (c.title or "").lower()]
    shots = []
    for mode in ("light", "dark"):
        tmp = Path(tempfile.mkdtemp(prefix=f"litreader_g8_{mode}_"))
        cfg, kw, _ = gui_fakes.environment(tmp)
        win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp / "guidata", check_updates=False,
                         update_getter=lambda u, t: json.dumps(fake).encode())
        win.updates.prefs.set("update_urls", ["https://local.fake/latest.json"])
        win.set_appearance(mode)
        win.show()
        win.resize(1180, 820)

        def settle(n=8):
            for _ in range(n):
                app.processEvents()
                time.sleep(0.01)

        def snap(name, popover=False):
            settle()
            pm = win.grab()
            if popover and win.popover and win.popover.isVisible():
                q = QPainter(pm)
                q.drawPixmap(win.popover.mapToGlobal(win.popover.rect().topLeft()) - win.mapToGlobal(win.rect().topLeft()),
                             win.popover.grab())
                q.end()
            p = out / f"{prefix}_{name}_{mode}.png"
            pm.save(str(p))
            shots.append(p)

        def about_view():
            win.show_about_card()
            settle()
            area = win.settings.findChild(QScrollArea)
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())

        about_view(); snap("about_card")
        win.go("home"); win.show_feedback(); snap("popover", popover=True); win.popover.hide()
        win.updates.check(manual=False, sync=True); settle()
        win.go("home"); snap("update_notice")
        win.show_feedback(); snap("popover_update", popover=True); win.popover.hide()
        about_view(); snap("about_card_update")
        win.go("home")
        win.home.input.setText("精读zotero中的 《gait older adults features》")
        win.home._submit()
        spin(app, lambda: win.flow.req is not None and win.flow.req["kind"] == "candidate")
        snap("candidate_keywords")
        win.flow._answer("q")
        spin(app, lambda: not win.running)
        win.go("home")
        win.home.input.setText("精读zotero中的 《不存在的示例论文》")
        win.home._submit()
        try:
            spin(app, lambda: not win.running and win.flow.next_btn.text() == "修改指令")
        except SystemExit:
            print("DEBUG", win.running, repr(win.flow.next_btn.text()), win.flow.tracker.state, win.flow.req)
            raise
        for _ in range(3):
            settle()
            for a in win.flow.findChildren(QScrollArea):
                a.verticalScrollBar().setValue(a.verticalScrollBar().maximum())
        snap("edit_instruction")
        win.close()
    for p in shots:
        print(p)


def g9_shots(out: Path, prefix: str = "gui_v7"):
    """G9 (light theme): home with v1.0.0 in the sidebar, ① card after a failure while choosing the paper,
    ⑨ card after a late failure (simulated with local fakes; no network)."""
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from litreader.gui.app import MainWindow
    from litreader.zotero.client import ZoteroClient
    _search = ZoteroClient.search
    ZoteroClient.search = lambda self, q, *a, **k: [c for c in _search(self, q, *a, **k)
                                                     if str(q).lower() in (c.title or "").lower()]
    tmp = Path(tempfile.mkdtemp(prefix="litreader_g9_"))
    cfg, kw, _ = gui_fakes.environment(tmp)
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp / "guidata", check_updates=False)
    win.set_appearance("light")
    win.show()
    win.resize(1180, 820)
    shots = []

    def snap(name):
        for _ in range(8):
            app.processEvents()
            time.sleep(0.01)
        p = out / f"{prefix}_{name}_light.png"
        win.grab().save(str(p))
        shots.append(p)

    win.go("home"); snap("home_version")
    win.home.input.setText("精读zotero中的 《不存在的示例论文》")
    win.home._submit()
    spin(app, lambda: not win.running and win.flow.next_btn.text() == "修改指令")
    win.flow.view_step("select"); snap("select_failed")
    f = win.flow
    f.start("精读zotero中的 示例")
    for k in ("select", "parse", "estimate"):
        f.tracker._activate(k)
    f.tracker._activate("done")
    f.finished({"status": "error", "message": "（示例）写入笔记时出错"})
    f.view_step("done"); snap("done_failed")
    win.close()
    for p in shots:
        print(p)


def g10_shots(out: Path, prefix: str = "gui_v8"):
    """G10 (light theme): 基础设置 → Obsidian with the 笔记文件夹 field + resolved 论文写入位置 (default litreader),
    and the same card after the user typed another folder (save button + 'existing notes stay' note). Fakes only."""
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    from PySide6.QtWidgets import QScrollArea
    from litreader.gui.app import MainWindow
    tmp = Path(tempfile.mkdtemp(prefix="litreader_g10_"))
    cfg, kw, _ = gui_fakes.environment(tmp)
    (Path(cfg.vault_root) / ".obsidian").mkdir(parents=True, exist_ok=True)
    (Path(cfg.vault_root) / cfg.dry_run_dir).mkdir(parents=True, exist_ok=True)
    win = MainWindow(cfg=cfg, run_kwargs=kw, data_dir=tmp / "guidata", check_updates=False)
    win.set_appearance("light")
    win.show()
    win.resize(1180, 820)
    win.go("settings")
    ob = win.settings.obsidian
    shots = []

    def snap(name):
        for _ in range(8):
            app.processEvents()
            time.sleep(0.01)
        area = win.settings.findChild(QScrollArea)
        if area is not None:
            area.verticalScrollBar().setValue(ob.mapTo(area.widget(), ob.rect().topLeft()).y() - 24)
            for _ in range(4):
                app.processEvents()
        p = out / f"{prefix}_{name}_light.png"
        win.grab().save(str(p))
        shots.append(p)

    snap("obsidian_folder")
    ob.out.setText("阅读笔记/litreader")
    snap("obsidian_folder_changed")
    win.close()
    for p in shots:
        print(p)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--g10":
        g10_shots(Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/ui_shots"))
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--g9":
        g9_shots(Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/ui_shots"))
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--g8":
        g8_shots(Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/ui_shots"),
                 sys.argv[3] if len(sys.argv) > 3 else "gui_v6")
        raise SystemExit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        settings_shots(Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/ui_shots"),
                       sys.argv[3] if len(sys.argv) > 3 else "gui_v3")
        raise SystemExit(0)
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/ui_shots"), sys.argv[2] if len(sys.argv) > 2 else "gui_v2")
