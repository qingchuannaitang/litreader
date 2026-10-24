"""Litreader desktop window (PySide6, v1). Launch: `litreader gui`."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__, appconfig
from ..platform_words import shortcut
from ..errors import LitError
from . import avatar as av
from . import bridge, runner, theme
from .about import FeedbackPopover, UpdateBar, UpdateModel
from .flow import FlowPage
from .home import HomePage
from .models_page import ModelsPage
from .prefs import Prefs
from .result import ResultPage
from .library_page import LibraryPage
from .settings_page import SettingsPage
from .widgets import Segmented, button, label, set_icon

NAV = [("home", "主页", "house"), ("flow", "精读流程", "book-open-check"), ("result", "结果页", "file-text"),
       ("models", "模型设置", "cpu"), ("library", "模板库 && 项目库", "library-big"), ("settings", "基础设置", "settings")]


class MainWindow(QMainWindow):
    def __init__(self, config: str | None = None, run_kwargs: dict | None = None, cfg=None, data_dir=None,
                 models_transport=None, zotero_detect=None, zotero_opener=None, update_getter=None,
                 check_updates: bool | None = None):
        super().__init__()
        self.config, self.run_kwargs = config, dict(run_kwargs or {})
        self.cfg, self.cfg_error, self.cfg_path = cfg, None, None
        if self.cfg is None:
            if config is None:   # W5: fresh install -> create ~/litreader/config.local.toml from the bundled example
                try:
                    appconfig.ensure_default_config()
                except OSError as e:
                    self.cfg_error = f"无法创建配置文件 {appconfig.default_config_path()}：{e}"
            try:
                self.cfg_path = appconfig.find_config(config)
            except LitError:
                pass
            try:
                self.cfg = appconfig.load(config)
            except LitError as e:
                self.cfg_error = self.cfg_error or str(e)
        self._fixed_cfg = cfg is not None
        self.prefs = Prefs(data_dir or (self.cfg.data_dir if self.cfg else appconfig.default_data_dir()))
        self.updates = UpdateModel(self.prefs, getter=update_getter)
        self.worker = self.thread = None
        self.last_result = None
        self.tray = None
        self.setWindowTitle("Litreader")
        self.resize(1180, 820)
        self.setMinimumSize(1000, 700)
        self.setUnifiedTitleAndToolBarOnMac(True)

        root = QWidget()
        root.setObjectName("Main")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.update_bar = UpdateBar(self.updates)
        cv.addWidget(self.update_bar)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        h.addWidget(content, 1)
        self.setCentralWidget(root)

        self.home = HomePage()
        self.flow = FlowPage()
        self.result = ResultPage()
        self.models = ModelsPage(self.cfg, models_transport)
        self.library = LibraryPage(self.cfg, self.cfg_error)
        self.settings = SettingsPage(self.cfg, self.prefs, self.cfg_error, zotero_detect=zotero_detect,
                                     zotero_opener=zotero_opener, update_model=self.updates,
                                     cfg_path=self.cfg_path)
        self.settings.zotero.saved.connect(lambda _b: self._reload_cfg())
        self.settings.obsidian.saved.connect(lambda _b: self._reload_cfg())
        self.pages = {"home": self.home, "flow": self.flow, "result": self.result, "models": self.models,
                      "library": self.library, "settings": self.settings}
        for k, *_ in NAV:
            self.stack.addWidget(self.pages[k])
        self.flow.go_home.connect(self.new_reading)
        self.result.go_home.connect(self.new_reading)

        self.home.submitted.connect(self.start_run)
        self.home.batch.connect(self.start_batch)
        self.queue: list[str] = []
        self.batch_info: dict | None = None
        self.home.open_recent.connect(lambda r: (self.result.load(r, cfg=self.cfg, just=False), self.go("result")))
        self.flow.answered.connect(self._answer)
        self.flow.cancel_requested.connect(self.cancel_run)
        self.flow.rerun_requested.connect(lambda t: t and self.start_run(t))
        self.flow.edit_requested.connect(self.edit_instruction)
        self.flow.show_result.connect(lambda: self.go("result"))
        self.settings.avatar_changed.connect(self.refresh_avatar)
        self.settings.pick_avatar.connect(self.choose_avatar)
        if self.cfg_error:
            self.home.set_banner(f"⚠️ {self.cfg_error}。请到「基础设置」选好 Obsidian 库并保存（写入 {self.cfg_path or 'config.local.toml'}），然后重新打开 Litreader。")
        self._menus()
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme())
        self.apply_theme()
        self.refresh_avatar()
        self.refresh_recent()
        self.go("home")
        self.updates.changed.connect(self.refresh_update_dot)
        self.refresh_update_dot()
        if check_updates is None:
            check_updates = not os.environ.get("LITREADER_NO_UPDATE_CHECK")
        if check_updates:   # G8-9: at most once a day, silent on failure
            QTimer.singleShot(2000, self.updates.auto_check)

    # ---------- chrome ----------
    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 22, 14, 16)
        v.setSpacing(4)
        self.avatar_btn = QPushButton()
        self.avatar_btn.setFlat(True)
        self.avatar_btn.setCursor(Qt.PointingHandCursor)
        self.avatar_btn.setToolTip("点击更换头像")
        self.avatar_btn.setFixedSize(76, 76)
        self.avatar_btn.setStyleSheet("QPushButton{border:none;background:transparent;}")
        self.avatar_btn.clicked.connect(self.choose_avatar)
        theme.shadow(self.avatar_btn, "strong")
        v.addWidget(self.avatar_btn, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        name = label("Litreader", wrap=False)
        name.setObjectName("AppName")
        name.setAlignment(Qt.AlignCenter)
        v.addWidget(name)
        sub = label("Zotero → AI 精读 → Obsidian", wrap=False)
        sub.setObjectName("AppSub")
        sub.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        v.addSpacing(16)
        nb = button("  新的精读", "new", self.new_reading, f"回到主页开始新的一篇（{shortcut('N')}）", icon="plus")
        theme.shadow(nb)
        v.addWidget(nb)
        v.addSpacing(12)
        self.nav = {}
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for k, t, ic in NAV:
            b = button(f"  {t}", "nav", lambda _=False, k=k: self.go(k))
            b.setCheckable(True)
            set_icon(b, ic, "muted", 18, on="accent")
            grp.addButton(b)
            v.addWidget(b)
            self.nav[k] = b
        v.addStretch(1)
        # G6: bottom-left = version + 浅色 / 深色 / 跟随系统 (trial mode is shown on the home status line + result banner)
        self.appearance_seg = Segmented([("light", "浅色", "sun"), ("dark", "深色", "moon"), ("system", "跟随系统", "monitor")],
                                        self.prefs.get("appearance") or "system", compact=True)
        self.appearance_seg.changed.connect(self.set_appearance)
        v.addWidget(self.appearance_seg)
        v.addSpacing(8)
        self.version_label = label(f"Litreader v{__version__}", "version", wrap=False)
        self.version_label.setAlignment(Qt.AlignCenter)
        self.update_dot = QWidget()
        self.update_dot.setFixedSize(7, 7)
        self.update_dot.setObjectName("UpdateDot")
        self.update_dot.setAttribute(Qt.WA_StyledBackground, True)
        self.update_dot.setToolTip("有新版本")
        self.feedback_btn = button("", "chip", self.show_feedback, "关于与反馈", icon="message-circle")
        self.feedback_btn.setFixedSize(28, 28)
        vr = QHBoxLayout()
        vr.setSpacing(4)
        vr.addStretch(1)
        vr.addWidget(self.version_label)
        vr.addWidget(self.update_dot, 0, Qt.AlignTop)
        vr.addSpacing(4)
        vr.addWidget(self.feedback_btn)
        vr.addStretch(1)
        v.addLayout(vr)
        self.popover = None
        return side

    def _menus(self):
        mb = self.menuBar()
        app_menu = mb.addMenu("Litreader")
        about = QAction("关于 Litreader", self)
        about.setMenuRole(QAction.AboutRole)
        about.triggered.connect(lambda: QMessageBox.about(self, "关于 Litreader",
                                                          f"Litreader v{__version__}\nZotero → AI 精读 → Obsidian"))
        chk = QAction("检查更新…", self)
        chk.setMenuRole(QAction.ApplicationSpecificRole)
        chk.triggered.connect(lambda: (self.show_about_card(), self.updates.check(manual=True)))
        app_menu.addAction(chk)
        prefs = QAction("设置…", self)
        prefs.setMenuRole(QAction.PreferencesRole)
        prefs.setShortcut(QKeySequence.Preferences)
        prefs.triggered.connect(lambda: self.go("settings"))
        self.quit_action = QAction("退出 Litreader", self)
        self.quit_action.setMenuRole(QAction.QuitRole)
        self.quit_action.setShortcut(QKeySequence.Quit)   # ⌘Q on macOS, Ctrl+Q elsewhere
        self.quit_action.triggered.connect(self.close)
        for a in (about, prefs, self.quit_action):
            app_menu.addAction(a)
        f = mb.addMenu("文件")
        new = QAction("新的精读", self)
        new.setShortcut(QKeySequence.New)
        new.triggered.connect(self.new_reading)
        f.addAction(new)
        view = mb.addMenu("显示")
        g = QActionGroup(self)
        self.appearance_actions = {}
        for k, zh in (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")):
            a = QAction(zh, self, checkable=True)
            a.setChecked(self.prefs.get("appearance") == k)
            a.triggered.connect(lambda _=False, k=k: self.set_appearance(k))
            g.addAction(a)
            view.addAction(a)
            self.appearance_actions[k] = a
        w = mb.addMenu("窗口")
        mini = QAction("最小化", self)
        mini.setShortcut(QKeySequence("Ctrl+M"))
        mini.triggered.connect(self.showMinimized)
        w.addAction(mini)
        self.addAction(self.quit_action)   # shortcut works even when the menu bar is hidden

    def show_feedback(self):
        if self.popover is None:
            self.popover = FeedbackPopover(self.updates, self)
            self.popover.more.connect(self.show_about_card)
        self.popover.show_at(self.feedback_btn)

    def show_about_card(self):
        self.go("settings")
        QTimer.singleShot(0, self.settings.show_about)

    def refresh_update_dot(self):
        self.update_dot.setVisible(self.updates.has_newer)

    def go(self, key: str):
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)

    def is_dark(self) -> bool:
        a = self.prefs.get("appearance")
        if a in ("light", "dark"):
            return a == "dark"
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def set_appearance(self, k: str):
        if k not in ("light", "dark", "system"):
            return
        self.prefs.set("appearance", k)
        self.appearance_seg.set_current(k)
        if k in getattr(self, "appearance_actions", {}):
            self.appearance_actions[k].setChecked(True)
        self.apply_theme()

    def apply_theme(self):
        dark = self.is_dark()
        theme.apply(dark)
        self.flow.restyle(dark)
        self.refresh_avatar()

    def refresh_avatar(self):
        pm = av.current(self.prefs)
        self.avatar_btn.setIcon(QIcon(av.rounded(pm, 128, circle=self.prefs.get("avatar") == "custom")))
        self.avatar_btn.setIconSize(self.avatar_btn.size())
        self.setWindowIcon(brand_icon())      # app/Dock icon stays the original 'L' even with a custom avatar
        self.settings.refresh_avatar()

    def _reload_cfg(self):
        if self._fixed_cfg:
            return
        try:
            self.cfg = appconfig.load(self.config)
            self.cfg_error = None
            self.home.set_banner(None)
        except LitError as e:
            self.cfg_error = str(e)

    def choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择头像图片", "", av.IMAGE_FILTER)
        if not path:
            return
        img = av.load_image(path)
        if img is None:
            QMessageBox.warning(self, "无法使用这张图片", "请选择 png / jpg / webp 图片。")
            return
        dlg = av.CropDialog(img, self)
        if dlg.exec():
            av.save_custom(dlg.result_image(), self.prefs)
            self.refresh_avatar()

    def refresh_recent(self):
        d = self.cfg.data_dir if self.cfg else None
        self.home.set_recent(runner.dedup_papers(runner.recent_receipts(d, limit=500)) if d else [])
        if d:
            self.result.refresh_list(d)
        self.refresh_status()

    def refresh_status(self):
        """Home status line (prototype): Zotero read-only · which roles have a model · trial mode."""
        items = [("ok" if self.cfg else "stop", "Zotero 本地接口（只读）" if self.cfg else "还没有配置文件")]
        ms = getattr(self.models, "ms", None)
        if ms is not None:
            from ..llm.models import ROLES
            have = [ROLES[r] for r in ROLES if ms.roles.get(r)]
            items.append(("ok" if len(have) == len(ROLES) else "warn",
                          f"{' · '.join(have)} 已设置" if have else "还没有设置模型"))
        self.home.set_status(items)

    # ---------- running ----------
    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.isRunning()

    def edit_instruction(self, text: str):
        """G8-2: back to home with the failed instruction prefilled for editing."""
        self.go("home")
        self.home.input.setText(text or "")
        self.home.input.setFocus()

    def new_reading(self):
        self.go("flow" if self.running else "home")
        if not self.running:
            self.home.input.setFocus()

    def start_run(self, text: str):
        if self.running:
            QMessageBox.information(self, "正在精读", "一次只精读一篇：请等当前这篇完成或先取消。")
            self.go("flow")
            return
        if self.cfg_error and not self._fixed_cfg:
            try:   # the user may have created config.local.toml since the window opened
                self.cfg = appconfig.load(self.config)
                self.cfg_error = None
                self.home.set_banner(None)
            except LitError as e:
                QMessageBox.warning(self, "还不能开始", str(e))
                return
        cfg = self.cfg if self._fixed_cfg else None   # None: reload config + models.toml for every run
        kw = self.run_kwargs
        self.worker = bridge.RunWorker(lambda ui: runner.run_text(text, ui, self.config, cfg=cfg, **kw))
        self.worker.event.connect(self._on_event)
        self.worker.finished.connect(self._on_finished)
        self.flow.start(text)
        self.go("flow")
        self.thread = bridge.start(self.worker, self)

    # ---------- G7-10 篇数 > 1: sequential queue of single-paper runs ----------
    def start_batch(self, cmds: list[str], confirm=None) -> bool:
        cmds = [c for c in cmds if c.strip()]
        if len(cmds) <= 1:
            if cmds:
                self.start_run(cmds[0])
            return bool(cmds)
        if self.running:
            QMessageBox.information(self, "正在精读", "请等当前这篇完成或先取消，再开始一批。")
            return False
        ask = confirm or (lambda: QMessageBox.question(
            self, f"按顺序精读 {len(cmds)} 篇？",
            "将一篇接一篇地精读（不会并行）：\n" + "\n".join(f"{i}. {c[:60]}" for i, c in enumerate(cmds, 1)) +
            "\n\n每一篇开始前都会单独显示费用估算并等你确认；任何一篇取消或出错，后面的不再自动开始。"
            "全部结束后显示合计实际费用。") == QMessageBox.Yes)
        if not ask():
            return False
        self.batch_info = {"total": len(cmds), "done": 0, "cost": 0.0, "priced": True, "notes": []}
        self.queue = list(cmds[1:])
        self.start_run(cmds[0])
        self._batch_say()
        return True

    def _start_next(self, cmd: str):
        if self.running:                      # the worker thread is still winding down
            QTimer.singleShot(50, lambda: self._start_next(cmd))
            return
        self.start_run(cmd)
        self._batch_say()

    def _batch_say(self):
        b = self.batch_info
        if b:
            self.flow.append(f"📚 批量精读：第 {b['done'] + 1} / {b['total']} 篇")

    def _batch_after(self, res: dict):
        b = self.batch_info
        if not b:
            return
        r = (res.get("result") or {})
        rc = r.get("receipt") or {}
        ok = res.get("status") == "ok" and r.get("kind") == "paper" and rc.get("status") == "DRY_RUN_COMPLETE"
        if ok:
            b["done"] += 1
            for a in (rc.get("actual") or {}).values():
                b["cost"] += float(a.get("cost") or 0)
                b["priced"] = b["priced"] and a.get("priced", True)
        if ok and self.queue:
            nxt = self.queue.pop(0)
            self._start_next(nxt)
            return
        left = len(self.queue)
        cost = f"合计实际费用约 ¥{b['cost']:.2f}" + ("" if b["priced"] else "（部分模型未定价，未计入）")
        self.flow.append(f"📚 批量精读结束：完成 {b['done']} / {b['total']} 篇；{cost}"
                         + (f"；因中断，剩余 {left} 篇未开始" if left else ""))
        self.queue, self.batch_info = [], None

    def _answer(self, rid: str, choice: str):
        if self.worker:
            self.worker.answer(rid, choice)

    def cancel_run(self):
        if self.worker and self.running:
            self.worker.cancel()
            self.flow.append("… 正在取消：会在当前这一步结束后停止，不写入任何笔记")

    def _on_event(self, ev):
        self.flow.on_event(ev)
        if ev.type == "decision_request":
            self.notify("decision", "Litreader · 需要你决定", ev["prompt"].strip().split("\n")[0][:80])
        elif ev.type == "error":
            self.notify("error", "Litreader · 已停止", ev["message"][:120])

    def _on_finished(self, res: dict):
        self.flow.finished(res)
        self.refresh_recent()          # stopped / cancelled runs are listed too (G6)
        if res.get("status") == "ok" and (res.get("result") or {}).get("kind") == "paper":
            rc = res["result"]["receipt"]
            self.last_result = rc
            self.result.load(rc, cfg=self.cfg)
            self.notify("done", "Litreader · 精读完成", rc.get("note", "")[-80:])
        self._batch_after(res)

    def notify(self, kind: str, title: str, text: str):
        """Only when the window is not in front; master + per-event toggles (plan A: QSystemTrayIcon)."""
        from . import macos
        in_app = bool(macos.bundle_id())
        if not should_notify(self.prefs, kind, self.isActiveWindow(), in_app or QSystemTrayIcon.isSystemTrayAvailable()):
            return
        if in_app and macos.bundle_notify(title, text):     # Litreader.app: system Notification Center
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.activated.connect(lambda *_: (self.showNormal(), self.raise_(), self.activateWindow()))
            self.tray.show()
        self.tray.showMessage(title, text, self.windowIcon(), 8000)

    def closeEvent(self, e):
        if self.running:
            r = QMessageBox.question(self, "正在精读，确定退出？",
                                     "已调用模型消耗的 token 不会退回；未完成的笔记不会写入 Obsidian。解析缓存会保留，下次不再上传。")
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.cancel()
            self.thread.wait(3000)
        e.accept()


def should_notify(prefs, kind: str, active: bool, tray_ok: bool) -> bool:
    """System notification only when the app is in the background and both toggles (总开关 + this event) are on."""
    return bool(prefs.get("notify") and prefs.get(f"notify_{kind}") and not active and tray_ok)


def brand_icon() -> QIcon:
    ic = QIcon()
    for n in (16, 32, 64, 128, 256, 512):
        ic.addPixmap(av.default_avatar(n))
    return ic


def brand_png(size: int = 512) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    av.default_avatar(size).save(buf, "PNG")
    return bytes(ba.data())


def main(argv=None, config: str | None = None) -> int:
    from . import macos
    if QApplication.instance() is None:
        macos.set_app_name_early("Litreader")     # before NSApplication starts: menu-bar name (no .app bundle)
    app = QApplication.instance() or QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Litreader")
    app.setApplicationDisplayName("Litreader")
    app.setOrganizationName("litreader")
    app.setStyle("Fusion")
    app.setWindowIcon(brand_icon())
    macos.set_dock_icon(brand_png(512))           # Dock icon while running (needs pyobjc; otherwise Python's rocket)
    w = MainWindow(config=config)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
