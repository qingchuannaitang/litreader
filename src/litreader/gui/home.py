"""主页: gradient hero + one big prompt box (one paper per run) + chips + status line + 最近精读 table.
Submitting jumps straight into the reading flow."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from . import theme
from .widgets import (Clickable, ElidedLabel, GradientLabel, button, card, clear, hrow, icon_label, label, page, pill, sep,
                      set_icon)

EXAMPLES = [("精读一篇论文", "精读zotero中的 〈题名或关键词〉，并将精读笔记存入obsidian中"),
            ("指定模板", "用〈模板名〉模板精读zotero中的 〈题名〉"),
            ("不关联课题", "本次精读不关联任何课题，精读zotero中的 〈题名〉")]
# 最近精读 columns (G6): 论文 stretches; the others have fixed widths so rows never misalign.
COLS = [("论文", None), ("状态", 124), ("主题文件夹", 150), ("日期", 88), ("抽取完整度", 80)]
MAX_RECENT = 12
ROW_H = 64            # one 最近精读 row (title + meta line + paddings + separator)
COUNTS = [("1 篇", 1), ("2 篇", 2), ("3 篇", 3), ("5 篇", 5), ("10 篇", 10)]
ZOTERO_RO_TIP = ("Zotero 只读：Litreader 只通过本地接口读取条目和 PDF，从不修改、删除或新增 Zotero 里的任何东西。")


def split_batch(text: str, n: int) -> list[str]:
    """篇数 = n > 1: one command per non-empty line (max n). A single line with n > 1 is refused by the caller."""
    if n <= 1:
        return [text.strip()] if text.strip() else []
    return [x.strip() for x in text.splitlines() if x.strip()][:n]


def rows_fit(avail_px: int, row_h: int = ROW_H) -> int:
    return max(1, int(avail_px) // row_h)


class PromptEdit(QPlainTextEdit):
    """Multi-line prompt; Enter sends, Shift+Enter = new line. QLineEdit-like text()/setText() for callers."""
    returnPressed = Signal()

    def __init__(self):
        super().__init__()
        self.setProperty("role", "prompt")
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(64)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.returnPressed.emit()
            return
        super().keyPressEvent(e)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, t: str) -> None:
        self.setPlainText(t)
        c = self.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.setTextCursor(c)


class RecentList(QWidget):
    """最近精读 table (prototype): bold Chinese title + grey 'Author Year · journal · 条目 KEY'; status pill
    (完成 green / 已停止 red / 已取消 grey); topic; day; E-level. Fixed widths + elide, hover, row separators.
    Rows come only from real receipts (runner.recent_receipts → r['row']).
    G7: paginated (per_page rows; pager() widget 上一页 / n/m / 下一页) and optionally selectable
    (click selects + emits selected(dict); the result page acts on the selection; ↑↓ ←→ via move()/page_by())."""
    open = Signal(dict)
    selected = Signal(object)     # dict | None
    paged = Signal()

    def __init__(self, selectable: bool = False, per_page: int = 5):
        super().__init__()
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(0)
        self.selectable = selectable
        self.per_page = max(1, per_page)
        self.page = 0
        self.sel: int | None = None      # index into self.items
        self.items: list[dict] = []
        self.rows: list[Clickable] = []
        self._pager = None

    def count(self) -> int:
        return len(self.items)

    def pages(self) -> int:
        return max(1, -(-len(self.items) // self.per_page))

    def page_items(self) -> list[dict]:
        a = self.page * self.per_page
        return self.items[a:a + self.per_page]

    def current(self) -> dict | None:
        return self.items[self.sel] if self.sel is not None and 0 <= self.sel < len(self.items) else None

    @staticmethod
    def _cells(h: QHBoxLayout, widgets: list[QWidget]) -> None:
        for (_, w), cell in zip(COLS, widgets):
            if w is None:
                h.addWidget(cell, 1)
            else:
                cell.setFixedWidth(w)
                h.addWidget(cell, 0)

    def set(self, items: list[dict], keep_page: bool = False):
        self.items = list(items)
        if not keep_page:
            self.page = 0
        self.page = min(self.page, self.pages() - 1)
        if self.sel is not None and self.sel >= len(self.items):
            self.sel = None
        self._render()

    def set_per_page(self, n: int):
        n = max(1, int(n))
        if n != self.per_page:
            first = self.page * self.per_page
            self.per_page = n
            self.page = min(first // n, self.pages() - 1)
            self._render()

    def go_page(self, i: int):
        i = max(0, min(self.pages() - 1, i))
        if i != self.page:
            self.page = i
            self._render()
            self.paged.emit()

    def page_by(self, d: int):
        self.go_page(self.page + d)

    def select(self, i: int | None, emit: bool = True):
        if i is not None and not 0 <= i < len(self.items):
            return
        self.sel = i
        if i is not None:
            self.page = i // self.per_page
        self._render()
        if emit:
            self.selected.emit(self.current())

    def move(self, d: int):
        if not self.items:
            return
        if self.sel is None or self.sel // self.per_page != self.page:      # start on the visible page
            a = self.page * self.per_page
            self.select(a if d > 0 else min(len(self.items), a + self.per_page) - 1)
            return
        self.select(min(len(self.items) - 1, max(0, self.sel + d)))

    def pager(self) -> QWidget:
        if self._pager is None:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            self._prev = button("上一页", None, lambda: self.page_by(-1), "上一页（←）", icon="chevron-left")
            self._next = button("下一页", None, lambda: self.page_by(1), "下一页（→）", icon="chevron-right")
            self._next.setLayoutDirection(Qt.RightToLeft)
            self._plabel = label("1 / 1", "sub", wrap=False)
            h.addStretch(1)
            for x in (self._prev, self._plabel, self._next):
                h.addWidget(x)
            self._pager = w
            self._update_pager()
        return self._pager

    def _update_pager(self):
        if self._pager is None:
            return
        self._plabel.setText(f"{self.page + 1} / {self.pages()}")
        self._prev.setEnabled(self.page > 0)
        self._next.setEnabled(self.page < self.pages() - 1)
        self._pager.setVisible(self.pages() > 1)

    def _render(self):
        clear(self.v)
        self.rows = []
        head = QWidget()
        hh = QHBoxLayout(head)
        hh.setContentsMargins(12, 0, 12, 8)
        hh.setSpacing(16)
        self._cells(hh, [label(t, "th", wrap=False) for t, _ in COLS])
        self.v.addWidget(head)
        self.v.addWidget(sep())
        base = self.page * self.per_page
        for i, r in enumerate(self.page_items()):
            if i:
                self.v.addWidget(sep())
            row = self._row(r, base + i)
            self.rows.append(row)
            self.v.addWidget(row)
        self._update_pager()

    def _row(self, r: dict, idx: int) -> QWidget:
        d = r.get("row") or {}
        row = Clickable()
        row.setProperty("role", "trow_sel" if self.selectable and idx == self.sel else "trow")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 11, 12, 11)
        h.setSpacing(16)
        title_box = QWidget()
        col = QVBoxLayout(title_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        title = d.get("title") or Path(r.get("note") or "").stem or "（未识别论文）"
        col.addWidget(ElidedLabel(title, "strong"))
        if d.get("meta"):
            col.addWidget(ElidedLabel(d["meta"], "sub"))
        st = QWidget()
        sl = QHBoxLayout(st)
        sl.setContentsMargins(0, 0, 0, 0)
        p = pill(d.get("status") or "?", d.get("status_kind") or "gray")
        p.setToolTip(r.get("reason") or "")
        sl.addWidget(p)
        sl.addStretch(1)
        el = QWidget()
        ell = QHBoxLayout(el)
        ell.setContentsMargins(0, 0, 0, 0)
        if d.get("e_level"):
            ell.addWidget(pill(d["e_level"], d.get("e_kind") or "acc"))
        else:
            ell.addWidget(label("—", "muted", wrap=False))
        ell.addStretch(1)
        self._cells(h, [title_box, st, ElidedLabel(d.get("topic") or "—"),
                        label(d.get("date") or "—", "muted", wrap=False), el])
        if self.selectable:
            row.clicked.connect(lambda i=idx: self.select(i))
            row.setToolTip("单击选中；回车 = 笔记预览")
        else:
            row.clicked.connect(lambda r=r: self.open.emit(r))
            row.setToolTip("点击查看结果" if r.get("status_code") == "DRY_RUN_COMPLETE" else "点击查看停止原因")
        return row


class HomePage(QWidget):
    submitted = Signal(str)
    batch = Signal(list)          # G7-10: 篇数 > 1 → list of single-paper commands (sequential queue)
    open_recent = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = page("主页", scroll=False, margins=(36, 16, 36, 20))
        outer.addWidget(body)
        lay.setSpacing(0)
        self.banner = label("", "warn")
        self.banner.setVisible(False)
        lay.addWidget(self.banner)
        lay.addSpacing(18)
        lay.addWidget(GradientLabel("你好，今天想精读哪篇论文？"))
        sub = label("一句话告诉我：从 Zotero 找到论文，精读后把笔记存入 Obsidian。", "lead")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(26)

        box, bl = card("prompt", margins=(24, 16, 16, 12), spacing=6)
        theme.shadow(box, "strong")
        box.setMaximumWidth(760)
        self.input = PromptEdit()
        self.input.setPlaceholderText("例如：精读zotero中的 DeepGaitLab，并将精读笔记存入obsidian中")
        self.input.returnPressed.connect(self._submit)
        self.input.textChanged.connect(self._sync_send)
        bl.addWidget(self.input)
        self.send = button("", "send", self._submit, "开始精读（回车；Shift+回车换行）")
        set_icon(self.send, "arrow-up", "on_accent", 20)
        self.send.setEnabled(False)
        hint = label("↩ 发送 · ⇧↩ 换行", "sub", wrap=False)
        self.count = QComboBox()
        for t, n in COUNTS:
            self.count.addItem(t, n)
        self.count.setToolTip("篇数：多于 1 篇时，每行写一篇；会按顺序逐篇精读（每篇单独确认费用），开始前显示总篇数")
        self.count.currentIndexChanged.connect(self._count_changed)
        self.lock = QWidget()
        lk = QHBoxLayout(self.lock)
        lk.setContentsMargins(4, 0, 4, 0)
        lk.setSpacing(4)
        lk.addWidget(icon_label("lock", "muted", 13))
        lk.addWidget(label("Zotero 只读", "sub", wrap=False))
        self.lock.setToolTip(ZOTERO_RO_TIP)
        bl.addLayout(hrow(label("篇数", "sub", wrap=False), self.count, self.lock, None, hint, self.send, spacing=8))
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(box, 10)
        wrap.addStretch(1)
        lay.addLayout(wrap)
        lay.addSpacing(16)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch(1)
        for name, e in EXAMPLES:
            ch = button(name, "chip", lambda _=False, t=e: (self.input.setText(t), self.input.setFocus()), e)
            theme.shadow(ch)
            chips.addWidget(ch)
        chips.addStretch(1)
        lay.addLayout(chips)
        lay.addSpacing(12)
        self.status = QHBoxLayout()
        self.status.setSpacing(18)
        lay.addLayout(self.status)
        self.set_status([("ok", "Zotero 本地接口（只读）")])
        lay.addSpacing(18)

        # G7-11: 最近精读 takes the remaining height; rows per page follow it (no vertical scroll on the home page).
        self.recent_card, rl = card(margins=(24, 16, 24, 12), spacing=8)
        self.recent = RecentList(per_page=5)
        self.recent.open.connect(self.open_recent.emit)
        rl.addLayout(hrow(label("最近精读", "h2", wrap=False), None, label("点击一行查看结果 · 每篇论文一行", "sub", wrap=False)))
        rl.addWidget(self.recent)
        rl.addStretch(1)
        rl.addWidget(self.recent.pager())
        self.recent_empty = label("还没有精读记录：在上面输入一句话，开始第一篇。", "muted")
        rl.addWidget(self.recent_empty)
        lay.addWidget(self.recent_card, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_rows()

    def fit_rows(self):
        """Rows that fit the card: card height − title row − table header − pager."""
        h = self.recent_card.height()
        if h > 0:
            self.recent.set_per_page(rows_fit(h - 16 - 12 - 36 - 38 - 40))

    def batch_n(self) -> int:
        return int(self.count.currentData() or 1)

    def _count_changed(self, _i=None):
        n = self.batch_n()
        self.input.setFixedHeight(64 if n == 1 else 112)
        self.input.setPlaceholderText("例如：精读zotero中的 DeepGaitLab，并将精读笔记存入obsidian中" if n == 1 else
                                      f"每行一篇，最多 {n} 行，例如：\n精读zotero中的 DeepGaitLab\n精读zotero中的 〈另一篇题名〉")
        self._sync_send()

    def _sync_send(self):
        self.send.setEnabled(bool(self.input.text().strip()))

    def _submit(self):
        t = self.input.text().strip()
        if not t:
            return
        n = self.batch_n()
        if n > 1:
            cmds = split_batch(t, n)
            self.batch.emit(cmds)
        else:
            self.submitted.emit(t)
        self.input.clear()

    def set_banner(self, text: str | None):
        self.banner.setText(text or "")
        self.banner.setVisible(bool(text))

    def set_status(self, items: list[tuple[str, str]]):
        """[(ok|warn|stop, text)] shown under the chips, like the prototype status line."""
        clear(self.status)
        self.status.addStretch(1)
        for kind, text in items:
            d = label("", f"dot_{kind}", wrap=False)
            d.setFixedSize(7, 7)
            r = hrow(d, label(text, "sub", wrap=False), spacing=6)
            r.setAlignment(d, Qt.AlignVCenter)
            self.status.addLayout(r)
        self.status.addStretch(1)

    def set_recent(self, items: list[dict]):
        self.recent.set(items)
        self.recent.setVisible(bool(items))
        self.recent_empty.setVisible(not items)
