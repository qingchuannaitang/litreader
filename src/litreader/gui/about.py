"""G8-9/10: update check state + 「关于与反馈」 (settings card and sidebar 💬 popover). Nothing is uploaded:
the only network call is a GET of a public latest.json, and a failure is silent."""
from __future__ import annotations

import threading
from datetime import date

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import __version__, update
from .widgets import button, card, label, pill, repolish, sep


class UpdateModel(QObject):
    """Shared by the settings card, the popover, the sidebar dot and the notice bar."""
    changed = Signal()

    def __init__(self, prefs, getter=None, version: str = __version__):
        super().__init__()
        self.prefs, self.getter, self.version = prefs, getter, version
        self.info: dict | None = None      # last valid latest.json
        self.status = "idle"               # idle | checking | latest | newer | failed
        self.announce = False              # show red dot + notice bar
        self._done.connect(self._finish)

    _done = Signal(object, bool)

    # ---- config ----
    @property
    def urls(self):
        return list(self.prefs.get("update_urls") or []) or update.DEFAULT_URLS

    @property
    def qq_group(self) -> str:
        return (self.info or {}).get("qq_group") or self.prefs.get("qq_group") or update.DEFAULT_QQ_GROUP

    @property
    def feedback_url(self) -> str:
        return self.prefs.get("feedback_url") or update.DEFAULT_FEEDBACK_URL

    @property
    def has_newer(self) -> bool:
        return bool(self.info) and update.newer(self.info["version"], self.version)

    # ---- checking ----
    def auto_check(self, today: date | None = None, sync: bool = False) -> bool:
        if not update.due(self.prefs, today):
            return False
        self.check(manual=False, sync=sync, today=today)
        return True

    def check(self, manual: bool = True, sync: bool = False, today: date | None = None):
        self.prefs.set("last_update_check", (today or date.today()).isoformat())
        self.status = "checking"
        self.changed.emit()

        def work():
            self._done.emit(update.fetch_latest(self.urls, getter=self.getter), manual)
        if sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _finish(self, info, manual: bool):
        if info is None:
            self.status = "failed" if manual else ("newer" if self.has_newer else "idle")   # auto: silent
        else:
            self.info = info
            if info.get("qq_group"):
                self.prefs.set("qq_group", info["qq_group"])
            self.status = "newer" if self.has_newer else "latest"
            if manual and self.has_newer and self.prefs.get("skipped_version") == info["version"]:
                self.prefs.set("skipped_version", "")   # an explicit check shows it again
            if manual:
                self.prefs.set("remind_after", "")
        self.announce = update.should_announce(self.info, self.version, self.prefs)
        self.changed.emit()

    # ---- notice actions ----
    def open_download(self):
        if self.info and self.info.get("download_url"):
            QDesktopServices.openUrl(QUrl(self.info["download_url"]))

    def skip(self):
        if self.info:
            self.prefs.set("skipped_version", self.info["version"])
        self.announce = False
        self.changed.emit()

    def later(self):
        self.prefs.set("remind_after", update.snooze_until())
        self.announce = False
        self.changed.emit()

    def status_text(self) -> tuple[str, str]:
        if self.status == "checking":
            return "正在检查…", "gray"
        if self.status == "failed":
            return "暂时无法检查（网络不可用）", "gray"
        if self.has_newer:
            return f"有新版本 v{self.info['version']}", "stop"
        if self.status == "latest":
            return "已是最新", "ok"
        return "", "gray"


def toast(parent: QWidget, text: str = "已复制", ms: int = 1400) -> QLabel:
    t = QLabel(text, parent.window())
    t.setObjectName("Toast")
    t.adjustSize()
    w = parent.window()
    t.move((w.width() - t.width()) // 2, w.height() - t.height() - 48)
    t.show()
    t.raise_()
    QTimer.singleShot(ms, t.deleteLater)
    return t


def copy_qq(model: UpdateModel, anchor: QWidget):
    QGuiApplication.clipboard().setText(model.qq_group)
    return toast(anchor, "已复制")


def _qq_field(model) -> QLabel:
    f = label(model.qq_group, "path", wrap=False, selectable=True)
    f.setMinimumWidth(120)
    return f


class AboutCard(QFrame):
    """Bottom of 基础设置 (mockup a.png)."""

    def __init__(self, model: UpdateModel):
        c, l = card(spacing=12)
        super().__init__()
        self.setObjectName("AboutCard")
        self.model = model
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(c)
        l.addWidget(label("关于与反馈", "h2"))
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(14)
        g.setColumnMinimumWidth(0, 160)
        g.setColumnStretch(2, 1)

        def row(r, title, *ws, right=None):
            g.addWidget(label(title, "strong", wrap=False), r, 0)
            h = QHBoxLayout()
            h.setSpacing(10)
            for w in ws:
                h.addWidget(w)
            h.addStretch(1)
            if right is not None:
                h.addWidget(right)
            g.addLayout(h, r, 1, 1, 2)

        self.qq = _qq_field(model)
        self.copy_btn = button("复制", None, lambda: copy_qq(model, self), icon="copy")
        row(0, "QQ 交流群", self.qq, self.copy_btn, label("使用问题、经验交流", "sub", wrap=False))
        self.ver = label(f"v{model.version}", "strong", wrap=False)
        self.state = pill("", "gray")
        self.check_btn = button("检查更新", None, lambda: model.check(manual=True), icon="refresh-cw")
        self.view_btn = button("查看更新", "primary", model.open_download)
        row(1, "当前版本", self.ver, self.state, right=self._pair(self.view_btn, self.check_btn))
        self.auto = QCheckBox("")
        self.auto.setChecked(bool(model.prefs.get("auto_update")))
        self.auto.toggled.connect(lambda on: model.prefs.set("auto_update", bool(on)))
        self.auto.setCursor(Qt.PointingHandCursor)
        row(2, "自动检查更新", label("每天启动时最多查一次是否有新版本（只读取版本号，不上传任何数据）", "sub"), right=self.auto)
        self.issue_btn = button("提建议（GitHub Issues）", "link",
                                lambda: QDesktopServices.openUrl(QUrl(model.feedback_url)), icon="external-link")
        row(3, "提建议", self.issue_btn, right=label("会在浏览器中打开", "sub", wrap=False))
        l.addLayout(g)
        model.changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _pair(*ws) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for x in ws:
            h.addWidget(x)
        return w

    def refresh(self):
        m = self.model
        self.qq.setText(m.qq_group)
        t, kind = m.status_text()
        self.state.setText(t)
        self.state.setProperty("role", f"pill_{kind}")
        self.state.setVisible(bool(t))
        repolish(self.state)
        self.view_btn.setVisible(m.has_newer and bool((m.info or {}).get("download_url")))
        self.check_btn.setEnabled(m.status != "checking")


class FeedbackPopover(QFrame):
    """Sidebar 💬 popover (mockups b.png / b2.png)."""
    more = Signal()

    def __init__(self, model: UpdateModel, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("Popover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.model = model
        self.setMinimumWidth(300)
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(10)
        l.addWidget(label("关于与反馈", "h2"))
        l.addWidget(sep())
        self.qq = _qq_field(model)
        self.copy_btn = button("复制", None, lambda: copy_qq(model, self.parentWidget() or self), icon="copy")
        h = QHBoxLayout()
        h.addWidget(label("QQ 交流群", "strong", wrap=False))
        h.addWidget(self.qq, 1)
        h.addWidget(self.copy_btn)
        l.addLayout(h)
        l.addWidget(sep())
        self.ver = label(f"v{model.version}", "strong", wrap=False)
        self.state = pill("", "gray")
        self.check_btn = button("检查更新", None, lambda: model.check(manual=True))
        self.view_btn = button("查看更新", "primary", model.open_download)
        h = QHBoxLayout()
        h.addWidget(self.ver)
        h.addWidget(self.state)
        h.addStretch(1)
        h.addWidget(self.check_btn)
        h.addWidget(self.view_btn)
        l.addLayout(h)
        l.addWidget(sep())
        self.issue_btn = button("提建议（GitHub Issues）", "link",
                                lambda: QDesktopServices.openUrl(QUrl(model.feedback_url)), icon="external-link")
        self.more_btn = button("更多设置…", "link", self._more)
        h = QHBoxLayout()
        h.addWidget(self.issue_btn)
        h.addStretch(1)
        h.addWidget(self.more_btn)
        l.addLayout(h)
        model.changed.connect(self.refresh)
        self.refresh()

    def _more(self):
        self.hide()
        self.more.emit()

    def refresh(self):
        m = self.model
        self.qq.setText(m.qq_group)
        t, kind = m.status_text()
        self.state.setText(t)
        self.state.setProperty("role", f"pill_{kind}")
        self.state.setVisible(bool(t))
        repolish(self.state)
        newer = m.has_newer and bool((m.info or {}).get("download_url"))
        self.view_btn.setVisible(newer)
        self.check_btn.setVisible(not newer)
        self.check_btn.setEnabled(m.status != "checking")

    def show_at(self, anchor: QWidget):
        self.adjustSize()
        p = anchor.mapToGlobal(QPoint(0, 0))
        self.move(max(0, p.x() - 20), p.y() - self.height() - 8)
        self.show()


class UpdateBar(QFrame):
    """Notice at the top of the content area: 查看更新 / 跳过此版本 / 稍后提醒."""

    def __init__(self, model: UpdateModel):
        super().__init__()
        self.setObjectName("UpdateBar")
        self.model = model
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 10, 18, 10)
        self.text = label("", None)
        h.addWidget(self.text, 1)
        self.view_btn = button("查看更新", "primary", model.open_download)
        h.addWidget(self.view_btn)
        h.addWidget(button("跳过此版本", None, model.skip))
        h.addWidget(button("稍后提醒", None, model.later))
        model.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        m = self.model
        self.setVisible(m.announce)
        if m.announce and m.info:
            notes = m.info.get("notes") or ""
            self.text.setText(f"发现新版本 v{m.info['version']}（当前 v{m.version}）" + (f"：{notes[:80]}" if notes else ""))
            self.view_btn.setVisible(bool(m.info.get("download_url")))
