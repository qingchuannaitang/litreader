"""基础设置: avatar, notifications, Zotero 一键检测, Obsidian 库路径. Production writes locked.
G6: 外观 moved to the sidebar toggle; parser tokens moved to 模型设置 → 解析器."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QScrollArea, QGridLayout, QLabel, QVBoxLayout, QWidget

from . import avatar as av
from .setup_panels import ObsidianCard, ZoteroSetupCard
from .widgets import button, card, empty_state, hrow, label, page, sep

class SettingsPage(QWidget):
    avatar_changed = Signal()
    pick_avatar = Signal()

    def __init__(self, cfg, prefs, cfg_error: str | None = None, zotero_detect=None, zotero_opener=None,
                 vault_picker=None, update_model=None):
        super().__init__()
        self.setObjectName("Page")
        self.prefs = prefs
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = page("基础设置")
        outer.addWidget(body)

        def setrow(l, title, hint, *controls):
            g = QGridLayout()
            g.setHorizontalSpacing(16)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, "strong", wrap=False))
            if hint:
                col.addWidget(label(hint, "sub"))
            g.addLayout(col, 0, 0)
            g.addLayout(hrow(*controls, None), 0, 1)
            g.setColumnMinimumWidth(0, 220)
            g.setColumnStretch(1, 1)
            l.addLayout(g)

        c, l = card(spacing=14)
        l.addWidget(label("头像", "h2"))
        self.preview = QLabel()
        self.preview.setFixedSize(64, 64)
        self.refresh_avatar()
        setrow(l, "头像", "png / jpg / webp；裁剪成正方形，只在应用数据目录保存一份 256×256 副本，原图不动。也可以直接点左上角头像。",
               self.preview, button("更换头像…", None, lambda: self.pick_avatar.emit(), icon="image"),
               button("恢复默认", None, self._reset_avatar, icon="refresh-cw"))
        lay.addWidget(c)

        c, l = card(spacing=14)
        l.addWidget(label("系统通知", "h2"))
        self.notify = QCheckBox("")
        self.n_dec = QCheckBox("")
        self.n_done = QCheckBox("")
        self.n_err = QCheckBox("")
        rows = ((self.notify, "notify", "应用不在前台时发送通知", "总开关"), (self.n_dec, "notify_decision", "需要你决定时", ""),
                (self.n_done, "notify_done", "精读完成时", ""), (self.n_err, "notify_error", "出错或停止时", ""))
        for i, (cb, k, t, hnt) in enumerate(rows):
            cb.setChecked(bool(prefs.get(k)))
            cb.toggled.connect(lambda v, k=k: (prefs.set(k, bool(v)), self._sync_notify()))
            cb.setCursor(Qt.PointingHandCursor)
            if i:
                l.addWidget(sep())
            setrow(l, t, hnt, cb)
        self._sync_notify()
        l.addWidget(label("第一次通知时 macOS 会询问是否允许；之后可在「系统设置 → 通知」里修改。拒绝后界面内照常提示。", "sub"))
        lay.addWidget(c)

        self.zotero = ZoteroSetupCard(cfg, cfg_error, detect_fn=zotero_detect, opener=zotero_opener)
        lay.addWidget(self.zotero)
        self.obsidian = ObsidianCard(cfg, cfg_error, picker=vault_picker)
        lay.addWidget(self.obsidian)
        self.about = None
        if update_model is not None:     # G8-10: 关于与反馈
            from .about import AboutCard
            self.about = AboutCard(update_model)
            lay.addWidget(self.about)
        lay.addStretch(1)

    def show_about(self):
        sc = self.findChild(QScrollArea)
        if sc and self.about:
            sc.ensureWidgetVisible(self.about, 0, 40)

    def _sync_notify(self):
        on = self.notify.isChecked()
        for cb in (self.n_dec, self.n_done, self.n_err):
            cb.setEnabled(on)

    def refresh_avatar(self):
        self.preview.setPixmap(av.rounded(av.current(self.prefs), 64, circle=self.prefs.get("avatar") == "custom"))

    def _reset_avatar(self):
        av.reset_default(self.prefs)
        self.refresh_avatar()
        self.avatar_changed.emit()


def placeholder(title: str, lines: list[str], icon: str = "layers") -> QWidget:
    body, lay = page(title)
    lay.addWidget(empty_state(icon, "下一版", lines[0], extra=lines[1:]))
    lay.addStretch(1)
    return body
