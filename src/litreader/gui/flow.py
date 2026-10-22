"""精读流程 page (G6, prototype p-flow): instruction bar · 9-step stepper · interaction panel (decision pills with
keycaps / live data-flow nodes) · step detail card · live log · 上一步 / 取消 / 继续.

Everything shown comes from the real event bus (stage / progress / log / decision_request). The pipeline only moves
forward: 「上一步」 re-shows an earlier step's details, 「继续」 answers the pending decision with its highlighted choice.
Step mapping lives in flow_steps.py (unit-tested)."""
from __future__ import annotations

import html
import re
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLayout, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import estimate as est_mod
from . import flow_steps as FS
from . import theme
from .widgets import (AccentCard, ElidedLabel, Keycap, button, card, clear, empty_state, hrow, label, page, path_label,
                      pill, repolish)

STEPS = [t for _, t in FS.STEPS]
NODES = [("zotero", "Zotero PDF"), ("parse", "解析"), ("vision", "看图"), ("writer", "主笔"), ("judge", "交叉核对"),
         ("write", "Obsidian")]
NODE_ICON = {"zotero": "file-text", "parse": "scan-text", "vision": "image", "writer": "pen-line", "judge": "shield-check",
             "write": "notebook-pen"}
STAGE_ZH = {"zotero": "Zotero", "project": "关联课题", "estimate": "估算", "parse": "解析", "template": "模板",
            "vision": "看图", "writer": "主笔", "judge": "交叉核对", "lens": "项目视角", "author": "作者核对",
            "topic": "主题文件夹", "write": "写入 Obsidian"}
KIND_TITLE = {"candidate": "选择论文", "pdf": "选择 PDF 附件", "consent": "需要模型帮忙理解指令吗？", "cost": "运行前费用估算",
              "template": "确认模板", "modules": "调整专业模块", "author": "作者顺序冲突：文件名用哪位作者区分？",
              "topic_folder": "放进哪个主题文件夹？", "confirm": "请确认", "project": "关联课题（只问一次）", "text": "需要你回答"}
CARD_KINDS = {"candidate", "pdf", "template", "modules", "topic_folder", "project"}
VISION_SKIPPED = "已跳过（未配置看图模型）"
ROLE_ORDER = [("vision", "看图"), ("writer", "主笔"), ("judge", "交叉核对"), ("lens", "项目视角")]
NUM_RE = re.compile(r"(?<![\w#])(\d[\d,]*(?:\.\d+)?%?|¥\d[\d,.]*)")


class FlowLayout(QLayout):
    """Wrapping row layout (Qt's flow-layout example) for the decision pills."""

    def __init__(self, spacing: int = 10):
        super().__init__()
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, r, test):
        x, y, line = r.x(), r.y(), 0
        for it in self._items:
            w = it.sizeHint()
            if x + w.width() > r.right() and line > 0:
                x, y, line = r.x(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + self._sp
            line = max(line, w.height())
        return y + line - r.y()


class Stepper(QWidget):
    """9 numbered circles on a gradient connector; done = green check, active = accent, skipped = dashed '–'.
    Click a reached step to see its details (does not rewind the run)."""
    clicked = Signal(str)

    def __init__(self, tracker: FS.Tracker):
        super().__init__()
        self.tr = tracker
        self.setFixedHeight(58)
        self.viewing = None
        self.failed = False
        self.setCursor(Qt.PointingHandCursor)

    @property
    def current(self) -> int:
        return self.tr.index()

    def refresh(self, viewing: str | None = None, failed: bool | None = None):
        if viewing is not None:
            self.viewing = viewing
        if failed is not None:
            self.failed = failed
        self.update()

    def restyle(self, dark):
        self.update()

    def _cx(self, i):
        w = self.width() / len(STEPS)
        return (i + 0.5) * w

    def mousePressEvent(self, e):
        w = self.width() / len(STEPS)
        i = int(e.position().x() // w)
        if 0 <= i < len(STEPS) and self.tr.state[FS.KEYS[i]] != "todo":
            self.clicked.emit(FS.KEYS[i])

    def paintEvent(self, e):
        c = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy, r = 15, 13
        n = len(STEPS)
        x0, x1 = self._cx(0), self._cx(n - 1)
        p.setPen(QPen(QColor(c["line"]), 2))
        p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        reached = max([i for i, k in enumerate(FS.KEYS) if self.tr.state[k] != "todo"], default=-1)
        if reached > 0:
            g = QLinearGradient(x0, 0, self._cx(reached), 0)
            g0, g1, g2 = c["grad"]
            g.setColorAt(0, QColor(g0)); g.setColorAt(0.5, QColor(g1)); g.setColorAt(1, QColor(g2))
            p.setPen(QPen(g, 3))
            p.drawLine(QPointF(x0, cy), QPointF(self._cx(reached), cy))
        f = QFont(self.font())
        for i, key in enumerate(FS.KEYS):
            st = self.tr.state[key]
            cx = self._cx(i)
            rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
            fail = self.failed and key == self.tr.current
            if self.viewing == key and st != "todo":
                p.setPen(QPen(QColor(c["accent_soft"]), 6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(-3, -3, 3, 3))
            if st == "done" and not fail:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["ok"]))
                p.drawEllipse(rect)
                p.drawPixmap(rect.adjusted(6, 6, -6, -6).toRect(), theme.icon_pixmap("check", c["panel"], 14))
            else:
                if fail:
                    pen, brush, fg, txt = QPen(QColor(c["stop"]), 2), QColor(c["stop_soft"]), c["stop"], "!"
                elif st == "active":
                    pen, brush, fg, txt = QPen(QColor(c["accent"]), 2), QColor(c["accent"]), c["on_accent"], str(i + 1)
                elif st == "skip":
                    pen, brush, fg, txt = QPen(QColor(c["muted"]), 1.5, Qt.DashLine), QColor(c["bg"]), c["muted"], "–"
                else:
                    pen, brush, fg, txt = QPen(QColor(c["line"]), 1.5), QColor(c["panel"]), c["muted"], str(i + 1)
                p.setPen(pen)
                p.setBrush(brush)
                p.drawEllipse(rect)
                f.setPixelSize(12)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(fg))
                p.drawText(rect, Qt.AlignCenter, txt)
            f.setPixelSize(11)
            f.setBold(st == "active")
            f.setStrikeOut(False)
            p.setFont(f)
            col = c["accent"] if st == "active" else c["text"] if st == "done" else c["muted"]
            p.setPen(QColor(col))
            w = self.width() / n
            name = STEPS[i] + ("（跳过）" if st == "skip" else "")
            p.drawText(QRectF(cx - w / 2, cy + r + 6, w, 18), Qt.AlignHCenter | Qt.AlignTop,
                       p.fontMetrics().elidedText(name, Qt.ElideRight, int(w) - 2))
        p.end()


class FlowNodes(QWidget):
    """Zotero PDF → 解析 → 看图 → 主笔 → 交叉核对 → Obsidian (prototype .flowviz). The edge into the running node is
    an animated dashed line (a cheap 90 ms QTimer, only while something runs and the widget is visible)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self.state = {k: "pending" for k, _ in NODES}
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(90)
        self.timer.timeout.connect(self._tick)

    def mark(self, stage: str, status: str):
        if stage not in self.state:
            return
        self.state[stage] = {"start": "running", "done": "done", "skip": "skip"}.get(status, self.state[stage])
        self._sync_timer()
        self.update()

    def finish_all(self):
        for k, s in self.state.items():
            if s in ("running", "pending"):
                self.state[k] = "done" if s == "running" or k == "write" else "skip"
        self._sync_timer()
        self.update()

    def stop(self):
        for k, s in self.state.items():
            if s == "running":
                self.state[k] = "pending"
        self._sync_timer()
        self.update()

    def reset(self):
        self.state = {k: "pending" for k, _ in NODES}
        self._sync_timer()
        self.update()

    def animating(self) -> bool:
        return self.timer.isActive()

    def _sync_timer(self):
        on = any(s == "running" for s in self.state.values())
        if on and not self.timer.isActive():
            self.timer.start()
        elif not on and self.timer.isActive():
            self.timer.stop()

    def _tick(self):
        if self.isVisible():
            self.phase = (self.phase + 1.5) % 16
            self.update()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        self._sync_timer()
        super().showEvent(e)

    def restyle(self, dark):
        self.update()

    def paintEvent(self, e):
        c = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(NODES)
        slot = 88
        gap = (self.width() - n * slot) / max(1, n - 1)
        box, cy = 40, 22
        keys = [k for k, _ in NODES]
        for i in range(n - 1):
            x0 = i * (slot + gap) + slot / 2 + box / 2 + 6
            x1 = (i + 1) * (slot + gap) + slot / 2 - box / 2 - 6
            a, b = self.state[keys[i]], self.state[keys[i + 1]]
            if b == "running" and a != "running":
                pen = QPen(QColor(c["accent"]), 2.2, Qt.CustomDashLine)
                pen.setDashPattern([3, 3])
                pen.setDashOffset(-self.phase)
            elif a in ("done", "skip") and b in ("done", "skip"):
                pen = QPen(QColor(c["ok"]), 2)
            else:
                pen = QPen(QColor(c["line"]), 2)
            p.setPen(pen)
            p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        f = QFont(self.font())
        f.setPixelSize(11)
        for i, (k, name) in enumerate(NODES):
            s = self.state[k]
            cx = i * (slot + gap) + slot / 2
            rect = QRectF(cx - box / 2, cy - box / 2, box, box)
            bg = {"done": c["ok_soft"], "running": c["accent_soft"]}.get(s, c["bg"])
            fg = {"done": c["ok"], "running": c["accent"]}.get(s, c["muted"])
            p.setPen(QPen(QColor(c["accent"]), 2) if s == "running" else QPen(QColor(c["line"]), 1))
            p.setBrush(QColor(bg))
            p.drawRoundedRect(rect, 13, 13)
            if s == "skip":
                p.setOpacity(0.45)
            p.drawPixmap(rect.adjusted(11, 11, -11, -11).toRect(), theme.icon_pixmap(NODE_ICON[k], fg, 18))
            p.setOpacity(1)
            p.setFont(f)
            p.setPen(QColor(c["text"] if s == "running" else c["muted"]))
            p.drawText(QRectF(cx - slot / 2, cy + box / 2 + 5, slot, 16), Qt.AlignHCenter,
                       name + ("（跳过）" if s == "skip" else ""))
        p.end()


class DecisionPill(QPushButton):
    """Decision button: keycap + label; the default choice is filled (prototype .opt pills)."""

    def __init__(self, key: str, text: str, default: bool = False, danger: bool = False, tip: str = ""):
        super().__init__()
        self.key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("role", "decide_default" if default else "decide")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 7, 16, 7)
        h.setSpacing(8)
        k = Keycap("↵" if key == "" else key)
        k.setProperty("role", "keycap_on" if default else "keycap")
        k.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(k, 0, Qt.AlignVCenter)
        t = ElidedLabel(text, "decide_t_on" if default else "decide_t")
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        bf = QFont(t.font())
        bf.setBold(True)
        from PySide6.QtGui import QFontMetrics
        t.setFixedWidth(min(460, QFontMetrics(bf).horizontalAdvance(text) + 12))
        if danger and not default:
            t.setStyleSheet(f"color:{theme.c('stop')};")
        h.addWidget(t)
        self.setToolTip(tip or text)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):
        return self.layout().sizeHint()


class ChoiceCard(QFrame):
    """Radio card in the step detail (candidates, templates, folders…). Click = select; double-click = answer."""
    picked = Signal(str)
    chosen = Signal(str)

    def __init__(self, key: str, title: str, lines: list[str] | None = None, zh: str | None = None,
                 machine: bool = False, selected: bool = False):
        super().__init__()
        self.key = key
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)
        self.dot = label("", None, wrap=False)
        self.dot.setFixedWidth(18)
        h.addWidget(self.dot, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(title, "strong"))
        if zh:
            c = theme.palette()
            tag = (f' <span style="background-color:{c["info_soft"]}; color:{c["info"]}; font-size:11px; font-weight:700;">'
                   f'&nbsp;机翻&nbsp;</span>') if machine else ""
            z = label(f"中文：{html.escape(zh)}{tag}")
            z.setTextFormat(Qt.RichText)
            col.addWidget(z)
        for ln in lines or []:
            col.addWidget(label(ln, "sub"))
        h.addLayout(col, 1)
        self.set_selected(selected)

    def set_selected(self, on: bool):
        self.selected = on
        self.setProperty("role", "cand_on" if on else "cand")
        repolish(self)
        self.dot.setText("◉" if on else "○")
        self.dot.setStyleSheet(f"color:{theme.c('accent' if on else 'muted')}; font-size:16px;")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.picked.emit(self.key)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.chosen.emit(self.key)


class FlowPage(QWidget):
    answered = Signal(str, str)     # decision id, choice text (exactly what the terminal would receive)
    cancel_requested = Signal()
    show_result = Signal()
    go_home = Signal()
    edit_requested = Signal(str)    # G8-2 「修改指令」: back to home with the instruction prefilled
    rerun_requested = Signal(str)   # 「从失败处重跑」: same command again; MinerU + per-figure vision caches are reused

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        self.setFocusPolicy(Qt.StrongFocus)
        self.tracker = FS.Tracker()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = page("精读流程")
        lay.setSpacing(14)
        outer.addWidget(body)

        # instruction bar
        self.cmd_card = QFrame()
        self.cmd_card.setProperty("role", "instr")
        cl = QHBoxLayout(self.cmd_card)
        cl.setContentsMargins(16, 9, 16, 9)
        self.cmd = label("", "sub", selectable=True)
        self.cmd.setTextFormat(Qt.RichText)
        cl.addWidget(self.cmd, 1)
        lay.addWidget(self.cmd_card)

        self.stepper = Stepper(self.tracker)
        self.stepper.clicked.connect(self.view_step)
        lay.addWidget(self.stepper)

        self.empty = empty_state("book-open-check", "还没有开始精读",
                                 "回到主页输入一句话指令，例如「精读zotero中的〈题名或关键词〉」。开始后，需要你决定的事会以按钮出现在这里，"
                                 "运行中显示数据流向、进度和实时日志。", "去主页输入指令", lambda: self.go_home.emit())
        lay.addWidget(self.empty)

        # interaction panel (prototype .ipanel)
        self.panel = AccentCard()
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(24, 20, 24, 18)
        pl.setSpacing(10)
        self.badge = label("等待开始", "pill_gray", wrap=False)
        self.step_no = label("", "strong", wrap=False)
        self.title = label("", "h2")
        pl.addLayout(hrow(self.badge, self.step_no, self.title, None, spacing=10))
        self.prompt = label("", "sub", selectable=True)
        pl.addWidget(self.prompt)
        self.opts_box = QWidget()
        self.opts = FlowLayout(10)
        self.opts_box.setLayout(self.opts)
        pl.addWidget(self.opts_box)
        self.custom = QLineEdit()
        self.custom.setPlaceholderText("或直接输入（例如新的主题文件夹名称），按回车确定")
        self.custom.returnPressed.connect(self._submit_custom)
        self.custom_ok = button("确定", "primary", self._submit_custom)
        self.custom_row = QWidget()
        cr = QHBoxLayout(self.custom_row)
        cr.setContentsMargins(0, 2, 0, 0)
        cr.addWidget(self.custom, 1)
        cr.addWidget(self.custom_ok)
        pl.addWidget(self.custom_row)
        self.nodes = FlowNodes()
        pl.addWidget(self.nodes)
        self.prog = QProgressBar()
        self.prog.setRange(0, 1)
        self.prog.setTextVisible(False)
        pl.addWidget(self.prog)
        self.prog_label = label("", "sub")
        pl.addWidget(self.prog_label)
        lay.addWidget(self.panel)

        # step detail card (prototype .stepbody)
        self.detail_card, dl = card(margins=(24, 20, 24, 20), spacing=10)
        self.detail_title = label("", "h2")
        self.detail_hint = label("", "sub")
        dl.addWidget(self.detail_title)
        dl.addWidget(self.detail_hint)
        self.detail = QVBoxLayout()
        self.detail.setSpacing(10)
        dl.addLayout(self.detail)
        lay.addWidget(self.detail_card)

        # live log
        self.log_card, ll = card(margins=(24, 18, 24, 20), spacing=10)
        ll.addLayout(hrow(label("实时日志", "h2", wrap=False), label("与终端显示的内容相同，可整段复制", "sub", wrap=False), None))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("role", "log")
        self.log.setMinimumHeight(220)
        ll.addWidget(self.log)
        lay.addWidget(self.log_card, 1)

        # bottom buttons
        self.prev_btn = button("上一步", None, self._prev, "查看上一步的详情（精读不会倒回去）")
        self.cancel_btn = button("取消", "danger", self._cancel, "在当前这一步结束后停止；不写入任何笔记", icon="x",
                                 icon_color="stop")
        self.next_btn = button("继续", "primary", self._continue, "有待你决定的选项时可用：按高亮的默认选项继续")
        self._rerun_mode = False
        self.result_btn = button("查看结果", "primary", lambda: self.show_result.emit(), icon="chevron-right",
                                 icon_color="on_accent")
        self.result_btn.setLayoutDirection(Qt.RightToLeft)
        self.result_btn.setEnabled(False)
        self.actions = QWidget()
        self.actions.setLayout(hrow(self.prev_btn, None, self.cancel_btn, self.next_btn, self.result_btn, spacing=10))
        self.actions.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.actions)
        lay.addStretch(0)

        self.req = None
        self.sel = None
        self.view = None
        self.prog_roles: dict[str, dict] = {}
        self.result_info = None
        self.t0 = time.time()
        self.dark = False
        self.started = False
        self.idle()

    # ---------- states ----------
    def _show_running_ui(self, on: bool):
        self.empty.setVisible(not on)
        for w in (self.cmd_card, self.panel, self.detail_card, self.log_card, self.actions):
            w.setVisible(on)
        self.stepper.setVisible(True)

    def _stream(self, on: bool):
        self.nodes.setVisible(on)
        self.prog.setVisible(on)
        self.prog_label.setVisible(on and bool(self.prog_label.text()))
        self.custom_row.setVisible(bool(self.req and self.req.get("allow_custom")))
        self.prompt.setVisible(bool(self.prompt.text()))
        self.opts_box.setVisible(self.opts.count() > 0)

    def idle(self):
        self.req = None
        self._badge("等待开始", "pill_gray")
        self.title.setText("交互面板")
        self.prompt.setText("")
        clear(self.opts)
        clear(self.detail)
        self.cancel_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self._stream(False)
        self._show_running_ui(False)

    def start(self, text: str):
        self.started = True
        self.tracker.reset()
        self.stopped = None   # G9-2: None while running; "failed" / "cancelled" once the run stopped
        self.stepper.refresh(viewing="select", failed=False)
        self._show_running_ui(True)
        self.t0 = time.time()
        self._cmd_text, self._interp = text, ""
        self._render_cmd()
        self.log.clear()
        self.nodes.reset()
        self.prog_roles = {}
        self.result_info = None
        self.result_btn.setEnabled(False)
        self.result_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.next_btn.setVisible(True)
        self._set_rerun(False)
        self.next_btn.setEnabled(False)
        self.req = None
        self.view = "select"
        clear(self.opts)
        self._badge("运行中", "pill_acc")
        self._title("select", "正在连接 Zotero（只读）")
        self.prompt.setText("")
        self.prog_label.setText("")
        self.prog.setRange(0, 0)
        self._stream(True)
        self._render_detail()

    def _render_cmd(self):
        t = f'指令：<span style="font-family:monospace;">{html.escape(self._cmd_text)}</span>'
        if self._interp:
            t += f" · {html.escape(self._interp)}"
        self.cmd.setText(t)

    def _badge(self, text, role):
        self.badge.setText(text)
        self.badge.setProperty("role", role)
        repolish(self.badge)

    def _title(self, key: str | None, text: str):
        if key in FS.KEYS:
            self.step_no.setText(f"第 {FS.KEYS.index(key) + 1} 步 ·")
        self.step_no.setVisible(key in FS.KEYS)
        self.title.setText(text)

    # ---------- events from the worker ----------
    def on_event(self, ev):
        t = ev.type
        key = self.tracker.feed(t, ev.data)
        if t == "log":
            self.append(ev["text"])
            m = re.match(r"\s*(理解为：.*)$", ev["text"] or "")
            if m:
                self._interp = m.group(1)
                self._render_cmd()
        elif t == "stage":
            st, status = ev["stage"], ev["status"]
            self.nodes.mark(st, status)
            if status == "start" and not self.req:
                self._title(key, f"{STAGE_ZH.get(st, st)}…")
                self.prog.setRange(0, 0)
                self.prog_label.setText("")
                self.prog_label.setVisible(False)
            if key and not self.req:
                self.view = key
            self._render_detail()
        elif t == "progress":
            done, total = ev["done"], max(1, ev["total"])
            r = self.prog_roles.setdefault(ev["stage"], {"in": 0, "out": 0})
            r.update(done=done, total=ev["total"])
            if ev.get("tokens_in") is not None:
                r["in"] = (r.get("in") or 0) + (ev.get("tokens_in") or 0)
                r["out"] = (r.get("out") or 0) + (ev.get("tokens_out") or 0)
            self.prog.setRange(0, total)
            self.prog.setValue(done)
            tok = ""
            if ev.get("tokens_in") is not None:
                tok = f" · 输入 {ev['tokens_in']:,} / 输出 {ev.get('tokens_out') or 0:,} tokens"
            self.prog_label.setText(f"{STAGE_ZH.get(ev['stage'], ev['stage'])} {done}/{ev['total']}{tok}")
            self.prog_label.setVisible(not self.req)
            if self.view == "reading":
                self._render_detail()
        elif t == "decision_request":
            self.show_decision(ev)
        elif t == "decision_response":
            if self.req and self.req["id"] == ev["id"]:
                self.req = None
                self.sel = None
                clear(self.opts)
                self._badge("运行中", "pill_acc")
                self._title(self.tracker.current, "继续运行…")
                self.prompt.setText("")
                self.next_btn.setEnabled(False)
                self._stream(True)
                self._render_detail()
        elif t == "done":
            self.nodes.finish_all()
            self.result_info = dict(ev.data)
        elif t == "error":
            self.append(("⏹ " if ev.get("cancelled") else "⛔ 已停止：") + ev["message"])
        self.stepper.refresh(viewing=self.view)

    def append(self, text: str):
        c = theme.palette()
        stamp = time.strftime("%H:%M:%S")
        for i, line in enumerate(str(text).split("\n")):
            esc = html.escape(line)
            esc = NUM_RE.sub(lambda m: f'<span style="color:{c["accent"]}; font-weight:600;">{m.group(1)}</span>', esc)
            if line.lstrip().startswith(("⛔", "⚠")):
                esc = f'<span style="color:{c["warn"]};">{esc}</span>'
            ts = stamp if i == 0 else "&nbsp;" * 8
            self.log.appendHtml(f'<span style="color:{c["muted"]};">{ts}</span>&nbsp;&nbsp;{esc.replace("  ", "&nbsp;&nbsp;")}')

    def show_decision(self, ev):
        self.req = ev
        kind = ev.get("kind")
        key = FS.step_of(kind=kind) or self.tracker.current
        self.view = key
        self._badge("需要你决定", "pill_trial")
        self._title(key, KIND_TITLE.get(kind, "需要你决定"))
        self.prompt.setText(ev["prompt"].strip())
        clear(self.opts)
        options = ev.get("options") or []
        default = ev.get("default")
        if default is None:
            keys = [o["key"] for o in options]
            default = "y" if "y" in keys else "" if "" in keys else (keys[0] if kind in CARD_KINDS and keys else None)
        self.sel = default
        has_cancel = any(o["key"] in ("n", "q") and "取消" in o["label"] for o in options)
        for o in options:
            k = o["key"]
            danger = k in ("n", "q") and "取消" in o["label"]
            b = DecisionPill(k, o["label"], default=(k == default), danger=danger,
                             tip=f"{o['label']}\n{o.get('detail') or ''}\n键盘：{'回车' if k == '' else k}".strip())
            b.clicked.connect(lambda _=False, k=k: self._answer(k))
            self.opts.addWidget(b)
        if not has_cancel:
            b = DecisionPill("q", "取消精读", danger=True)
            b.clicked.connect(lambda: self._answer("q"))
            self.opts.addWidget(b)
        self.custom.clear()
        self.next_btn.setEnabled(default is not None)
        self._stream(False)
        self._render_detail()
        self.stepper.refresh(viewing=self.view)
        if ev.get("allow_custom"):
            self.custom.setFocus()
        elif self.isVisible():
            self.setFocus()

    # ---------- step detail card ----------
    def view_step(self, key: str):
        self.view = key
        self.stepper.refresh(viewing=key)
        self._render_detail()

    def _render_detail(self):
        key = self.view or self.tracker.current or "select"
        clear(self.detail)
        i = FS.KEYS.index(key)
        st = self.tracker.state[key]
        suffix = {"done": "（已完成）", "skip": "（本次跳过）", "active": "", "todo": "（还没到）"}[st]
        if st == "active" and getattr(self, "stopped", None):
            suffix = "（已取消）" if self.stopped == "cancelled" else "（已停止）"
        self.detail_title.setText(f"{'①②③④⑤⑥⑦⑧⑨'[i]} {STEPS[i]}{suffix}")
        data = self.tracker.data[key]
        dec = data.get("decision") if (self.req and FS.step_of(kind=self.req.get("kind")) == key) else None
        self.detail_hint.setText("")
        getattr(self, f"_d_{key}")(data, dec, st)
        self.detail_hint.setVisible(bool(self.detail_hint.text()))
        self.prev_btn.setEnabled(i > 0 and any(self.tracker.state[k] != "todo" for k in FS.KEYS[:i]))

    def _cards(self, kind: str, cards: list[tuple[str, ChoiceCard]]):
        for k, cw in cards:
            cw.picked.connect(self._pick)
            cw.chosen.connect(self._answer)
            self.detail.addWidget(cw)
        self._card_widgets = dict(cards)

    def _pick(self, key: str):
        if not self.req:
            return
        self.sel = key
        for k, cw in getattr(self, "_card_widgets", {}).items():
            cw.set_selected(k == key)
        self.next_btn.setEnabled(True)

    def _option_cards(self, dec):
        if not dec or not self.req:
            return False
        opts = self.req.get("options") or []
        if not any(o.get("detail") for o in opts) and self.req.get("kind") not in CARD_KINDS:
            return False
        cards = [(o["key"], ChoiceCard(o["key"], f"{'↵' if o['key'] == '' else o['key']}  {o['label']}",
                                       [x for x in (o.get("detail") or "").split("\n") if x][:3],
                                       selected=o["key"] == self.sel)) for o in opts]
        self._cards(self.req.get("kind"), cards)
        return True

    def _kv(self, rows: list[tuple[str, str]]):
        from PySide6.QtWidgets import QGridLayout
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(6)
        for r, (k, v) in enumerate(rows):
            g.addWidget(label(k, "th", wrap=False), r, 0, Qt.AlignTop)
            g.addWidget(label(str(v), selectable=True), r, 1)
        g.setColumnMinimumWidth(0, 110)
        g.setColumnStretch(1, 1)
        self.detail.addLayout(g)

    def _wait(self, st):
        if st == "todo":
            self.detail.addWidget(label("还没运行到这一步。", "muted"))
        elif st == "active":
            stopped = getattr(self, "stopped", None)
            if stopped == "cancelled":
                self.detail.addWidget(label("⏹ 已取消：这一步没有完成。", "muted"))
            elif stopped:
                self.detail.addWidget(label("⛔ 已停止：这一步出错，没有完成。原因见上方提示和日志。", "err"))
            else:
                self.detail.addWidget(label("正在进行…", "muted"))

    def _d_select(self, data, dec, st):
        cands = ((dec or {}).get("data") or {}).get("candidates") if dec else None
        if dec and dec["kind"] == "candidate" and cands:
            self.detail_hint.setText(f"找到 {len(cands)} 篇候选。中文题名来自 Zotero；没有时由模型机翻并标注「机翻」。"
                                     "单击选中，双击或按「继续」确定。")
            cards = []
            for n, c in enumerate(cands, 1):
                meta = " · ".join(x for x in (str(c.get("year") or ""), c.get("added") and f"加入 Zotero：{c['added']}",
                                              c.get("key") and f"条目 {c['key']}") if x)
                cards.append((str(n), ChoiceCard(str(n), c.get("title") or "?", [meta], zh=c.get("title_zh"),
                                                 machine=bool(c.get("machine")), selected=str(n) == self.sel)))
            self._cards("candidate", cards)
            self.detail.addWidget(label("ℹ 若条目有多个 PDF 附件，会再请你选一个；附件父条目不一致时直接停止。", "info"))
            return
        if self._option_cards(dec):
            return
        z = data.get("zotero") or {}
        if z.get("item_key"):
            self._kv([("论文", z.get("title") or "—"), ("条目", z["item_key"]), ("PDF 附件", z.get("attachment_key") or "—")])
        else:
            self._wait(st)

    def _d_project(self, data, dec, st):
        if self._option_cards(dec):
            self.detail_hint.setText("课题档案只写在 Obsidian 里的课题档案文件夹；你的其他笔记不会被读取或改动。")
            return
        p = data.get("project") or {}
        if st == "skip":
            self.detail.addWidget(label("本次没有关联课题：按通用精读写「通用科研价值」。", "muted"))
        elif p.get("title"):
            self._kv([("课题", p["title"]), ("快照版本", f"v{p.get('version')}（冻结）" if p.get("version") else "—")])
        else:
            self._wait(st)

    def _d_estimate(self, data, dec, st):
        d = (dec or {}).get("data") or self.tracker.data["estimate"].get("_cost") or {}
        if dec:
            self.tracker.data["estimate"]["_cost"] = d
        cost = d.get("cost") or {}
        if not cost.get("roles"):
            self._wait(st)
            return
        self.detail_hint.setText("token 估算与模型无关：按论文长度与图数推算。不同厂商分词器（tokenizer）不同，实际会有差异；"
                                 "有本机实测的模型按自己的实测比例校准。")
        if d.get("upload"):
            self.detail.addWidget(label("⚠ 继续 = 同意把这篇 PDF 的副本上传到 MinerU（云端）解析；Zotero 里的原文件不会被修改。", "warn"))
        else:
            self.detail.addWidget(label("✓ MinerU：已有解析缓存，不上传。", "ok"))
        from PySide6.QtWidgets import QGridLayout
        from ..calibration import MIN_RUNS
        g = QGridLayout()
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(4)
        for j, h in enumerate(("角色", "模型（主用）", "输入 tokens", "输出 tokens", "费用")):
            g.addWidget(label(h, "th", wrap=False), 0, j)
        row = 1
        for role, r in (cost.get("roles") or {}).items():
            sp = r.get("spread", est_mod.RATIO["spread"])
            g.addWidget(_sep_line(), row, 0, 1, 5)
            row += 1
            g.addWidget(label(r["label"], "strong", wrap=False), row, 0, Qt.AlignTop)
            mc = QVBoxLayout()
            mc.setSpacing(3)
            mc.addWidget(label(r["model"]))
            if r.get("calibrated"):
                b = label(f"按本机 {r.get('n', 0)} 篇实测校准 · ±{round(sp * 100)}%", "cal_ok", wrap=False)
            else:
                b = label(f"按默认比例估算，误差较大 · ±{round(sp * 100)}%", "cal_def", wrap=False)
            mc.addWidget(b, 0, Qt.AlignLeft)
            n = int(r.get("n") or 0)
            if not r.get("calibrated"):
                mc.addWidget(label(f"已实测 {n} 篇，还需 {max(0, MIN_RUNS - n)} 篇才启用本模型校准" if n else "本模型尚无实测",
                                   "sub", wrap=False))
            g.addLayout(mc, row, 1)
            for col, v in ((2, r["in"]), (3, r["out"])):
                cc = QVBoxLayout()
                cc.setSpacing(2)
                cc.addWidget(label(f"约 {v:,}", "num", wrap=False))
                lo, hi = int(v * (1 - sp)), int(v * (1 + sp))
                cc.addWidget(label(f"{lo:,}–{hi:,}", "sub", wrap=False))
                cc.addStretch(1)
                g.addLayout(cc, row, col)
            fc = QVBoxLayout()
            fc.setSpacing(2)
            if r.get("cost") is not None:
                fc.addWidget(label(f"约 ¥{r['cost']:.3f}", "strong", wrap=False))
                if r.get("price_in") is not None:
                    fc.addWidget(label(f"按你填的单价 {r['price_in']:g} / {r['price_out']:g} 元·1M tokens", "sub"))
            else:
                fc.addWidget(pill("未填单价", "gray"), 0, Qt.AlignLeft)
                fc.addWidget(label("只显示 token", "sub", wrap=False))
            fc.addStretch(1)
            g.addLayout(fc, row, 4)
            row += 1
        g.setColumnStretch(1, 1)
        self.detail.addLayout(g)
        tot = cost.get("total")
        self.detail.addWidget(label(f"合计约 ¥{tot:.3f}（按你在模型设置里填的单价）" if tot is not None else
                                    "部分模型未填单价：只显示 token 估算", "sub"))
        if d.get("write_root"):
            self.detail.addWidget(path_label(f"写入位置：{d['write_root']}〈主题文件夹〉/"))

    def _d_parse(self, data, dec, st):
        p = data.get("parse") or {}
        if not p.get("level"):
            self._wait(st)
            return
        lvl = p["level"]
        self.detail.addLayout(hrow(pill(lvl, "stop" if lvl in ("E0", "E1") else "ok"),
                                   label("抽取完整度（E0 最差 → E3 完整）", "sub", wrap=False), None, spacing=8))
        rows = [("页数", p.get("pages") or "—"), ("解析缓存", "命中，未上传" if p.get("cached") else "本次上传解析")]
        if p.get("covered") is not None:
            rows.append(("正文覆盖", f"{p['covered']}"))
        if p.get("reasons"):
            rows.append(("说明", "；".join(map(str, p["reasons"]))[:400]))
        self._kv(rows)

    def _d_template(self, data, dec, st):
        if self._option_cards(dec):
            return
        t = data.get("template") or {}
        if not t.get("template_id"):
            self._wait(st)
            return
        self._kv([("主模板", f"{t.get('title') or ''}（{t['template_id']}）"), ("研究类型", t.get("study_type") or "—"),
                  ("专业模块", "、".join(t.get("modules") or []) or "不用模块"), ("选择理由", t.get("reason") or "—")])

    def _d_reading(self, data, dec, st):
        if not self.prog_roles and st == "todo":
            self._wait(st)
            return
        self.detail_hint.setText("各角色的实时进度与 token 用量（来自模型返回的 usage）。")
        for role, zh in ROLE_ORDER:
            r = self.prog_roles.get(role)
            node = self.nodes.state.get(role)
            if role == "vision" and node == "skip" and not r:   # G12-1: vision is optional
                self.detail.addLayout(hrow(label(zh, "strong", wrap=False), None,
                                           label(VISION_SKIPPED, "muted", wrap=False)))
                continue
            if not r and node not in ("running", "done"):
                continue
            r = r or {"done": 0, "total": 1}
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setRange(0, max(1, r.get("total") or 1))
            bar.setValue(r.get("done") or 0)
            tok = f"输入 {r['in']:,} · 输出 {r['out']:,} tokens" if r.get("in") else "—"
            self.detail.addLayout(hrow(label(zh, "strong", wrap=False), None,
                                       label(f"{r.get('done', 0)}/{r.get('total', 1)} · {tok}", "num", wrap=False)))
            self.detail.addWidget(bar)
        if not self.detail.count():
            self._wait(st)

    def _d_author(self, data, dec, st):
        c = (((dec or {}).get("data") or {}).get("conflict")) or (data.get("author") or {})
        if st == "skip" and not dec:
            self.detail.addWidget(label("没有作者顺序冲突。", "muted"))
            return
        if c.get("zotero_first") or c.get("pdf_first"):
            self._kv([("Zotero 第一作者", c.get("zotero_first") or "—"), ("PDF 第一位", c.get("pdf_first") or "—")]
                     + ([("采用", c["used"])] if c.get("used") else []))
            self.detail.addWidget(label("笔记里的作者会记为 UNKNOWN，请之后在 Zotero 里核对（litreader 不修改 Zotero）。", "warn"))
        else:
            self._wait(st)

    def _d_topic(self, data, dec, st):
        s = (((dec or {}).get("data") or {}).get("suggestion")) if dec else None
        if s:
            self.detail.addWidget(label(f"模型建议：{s.get('folder')}（{s.get('reason') or '主题相近'}）"
                                        + ("" if s.get("confident", True) else " · 模型自己也不太确定"), "info"))
        if self._option_cards(dec):
            return
        t = data.get("topic") or {}
        if t.get("folder"):
            self._kv([("主题文件夹", t["folder"] + ("（新建）" if t.get("new") else ""))])
        elif not s:
            self._wait(st)

    def _d_done(self, data, dec, st):
        r = self.result_info
        if not r:
            self._wait(st)
            return
        rows = [("笔记", r.get("note_path") or "—"), ("证据档案", r.get("evidence_path") or "—")]
        self._kv(rows)

    # ---------- actions ----------
    def _answer(self, key: str):
        if self.req:
            rid = self.req["id"]
            self.answered.emit(rid, key)

    def _set_rerun(self, on: bool, edit: bool = False):
        self._rerun_mode = on
        self._edit_mode = bool(on and edit)
        if self._edit_mode:
            self.next_btn.setText("修改指令")
            self.next_btn.setToolTip("还没有可复用的结果（停在选论文/估算之前）：回到主页修改这句指令后再试")
            return
        self.next_btn.setText("从失败处重跑" if on else "继续")
        self.next_btn.setToolTip("用同一条指令重新精读：已完成的 MinerU 解析和看图结果从缓存读取，不会重复扣费"
                                 if on else "有待你决定的选项时可用：按高亮的默认选项继续")

    def _continue(self):
        if self._rerun_mode and getattr(self, "_edit_mode", False):
            self.edit_requested.emit(getattr(self, "_cmd_text", "") or "")
            return
        if self._rerun_mode:
            self.rerun_requested.emit(getattr(self, "_cmd_text", "") or "")
            return
        if self.req and self.sel is not None:
            self._answer(self.sel)

    def _prev(self):
        i = FS.KEYS.index(self.view or "select")
        for k in reversed(FS.KEYS[:i]):
            if self.tracker.state[k] != "todo":
                self.view_step(k)
                return

    def _submit_custom(self):
        t = self.custom.text().strip()
        if self.req and t:
            self._answer(t)

    def _cancel(self):
        self.cancel_requested.emit()

    def keyPressEvent(self, e):
        """1–9 / y / n / q / Enter answer the pending decision, like typing in the terminal."""
        if self.req and not self.custom.hasFocus():
            keys = {o["key"] for o in self.req.get("options") or []} | {"q"}
            t = e.text().lower()
            if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.sel is not None:
                self._answer(self.sel)
                return
            if t and t in keys:
                self._answer(t)
                return
        super().keyPressEvent(e)

    def finished(self, res: dict):
        self.cancel_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.req = None
        clear(self.opts)
        st = res.get("status")
        if st == "ok":
            r = res.get("result") or {}
            self._badge("已完成", "pill_ok")
            if r.get("kind") == "paper":
                rc = r["receipt"]
                self.tracker.feed("done", {})
                self.result_info = {"note_path": rc.get("note"), "evidence_path": rc.get("evidence")}
                self._title("done", "精读完成")
                self.prompt.setText(f"笔记：{rc['note']}")
                self.nodes.finish_all()
                self.result_btn.setEnabled(True)
                self.result_btn.setVisible(True)
                self.next_btn.setVisible(False)
                self.view = "done"
            else:
                self._title(None, "已完成")
                self.prompt.setText("这条指令不是精读论文（模板库 / 课题命令），结果见下面的日志。")
        else:
            self.nodes.stop()
            self.stopped = "cancelled" if st == "cancelled" else "failed"
            self._badge("已停止" if st == "cancelled" else "出错", "pill_stop")
            self._title(None, "已取消" if st == "cancelled" else "已停止")
            self.prompt.setText(res.get("message") or "")
            self.stepper.refresh(failed=st != "cancelled")
            if st != "cancelled" and getattr(self, "_cmd_text", ""):
                # nothing reusable yet (failed while choosing the paper / before parsing) -> edit the instruction
                self._set_rerun(True, edit=self.tracker.state.get("parse") == "todo")
                self.next_btn.setEnabled(True)
        self._stream(False)
        self.nodes.setVisible(st == "ok")
        self._render_detail()
        self.stepper.refresh(viewing=self.view)

    def restyle(self, dark):
        self.dark = dark
        self.stepper.restyle(dark)
        self.nodes.restyle(dark)


def _sep_line():
    from .widgets import sep
    return sep()
