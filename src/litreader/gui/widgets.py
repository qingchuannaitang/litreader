"""Building blocks shared by the pages (G3). Styling comes only from theme.py (QSS roles + tokens)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme

MAX_W = 1040   # content column, like the prototype (.page max-width)


def label(text: str = "", role: str | None = None, wrap: bool = True, selectable: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    if selectable:
        w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def path_label(path: str, role: str = "path") -> QLabel:
    """Long paths wrap after '/' (zero-width spaces are display-only; the tooltip has the exact path)."""
    w = label(str(path).replace("/", "/\u200b"), role)
    w.setToolTip(str(path))
    return w


def pill(text: str, kind: str = "gray") -> QLabel:
    w = label(text, f"pill_{kind}", wrap=False)
    w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return w


def set_role(w: QWidget, role: str) -> None:
    w.setProperty("role", role)
    repolish(w)


def button(text: str, role: str | None = None, slot=None, tip: str | None = None, icon: str | None = None,
           icon_color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if role:
        b.setProperty("role", role)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    if icon:
        set_icon(b, icon, icon_color)
    b.setCursor(Qt.PointingHandCursor)
    return b


def set_icon(b: QPushButton, name: str, color: str | None = None, size: int = 16, on: str | None = None) -> None:
    def paint(_d=None):
        b.setIcon(theme.icon(name, color or "text", size, on))
        b.setIconSize(QSize(size, size))
    paint()
    theme.on_theme(b, paint)


def icon_label(name: str, color: str = "muted", size: int = 18) -> QLabel:
    w = QLabel()
    w.setFixedSize(size, size)

    def paint(_d=None):
        w.setPixmap(theme.icon_pixmap(name, theme.c(color) if not color.startswith("#") else color, size))
    paint()
    theme.on_theme(w, paint)
    return w


def card(role: str = "card", margins=(26, 22, 26, 22), spacing=12, shadow: bool = True) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("role", role)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    if shadow:
        theme.shadow(f)
    return f, lay


class AccentCard(QFrame):
    """Card with the prototype's 3px gradient strip on top (.ipanel::before)."""

    def __init__(self):
        super().__init__()
        self.setProperty("role", "panel")
        theme.shadow(self)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS["panel"], theme.RADIUS["panel"])
        p.setClipPath(path)
        g = QLinearGradient(QPointF(0, 0), QPointF(r.width(), 0))
        for i, col in enumerate(theme.palette()["grad"]):
            g.setColorAt(i / 2, col)
        p.fillRect(QRectF(0, 0, r.width(), 3), g)
        p.end()


def accent_card(margins=(24, 20, 24, 20), spacing=10) -> tuple[QFrame, QVBoxLayout]:
    f = AccentCard()
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return f, lay


class GradientLabel(QWidget):
    """Hero title painted with the brand gradient (CSS background-clip:text equivalent)."""

    def __init__(self, text: str, px: int = theme.FONT["hero"]):
        super().__init__()
        self.text, self.px = text, px
        self.f = QFont(self.font())
        self.f.setPixelSize(px)
        self.f.setWeight(QFont.DemiBold)
        self.setMinimumHeight(int(px * 1.45))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(600, int(self.px * 1.45))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self.f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(self.text)
        x0 = (self.width() - w) / 2
        g = QLinearGradient(QPointF(x0, 0), QPointF(x0 + w, 0))
        for i, col in enumerate(theme.palette()["grad"]):
            g.setColorAt([0, .55, 1][i], col)
        p.setPen(QPen(g, 1))
        p.drawText(self.rect(), Qt.AlignCenter, self.text)
        p.end()


def hrow(*widgets, stretch_at: int | None = None, spacing: int = 10) -> QHBoxLayout:
    r = QHBoxLayout()
    r.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            r.addStretch(1)
        elif isinstance(w, QWidget):
            r.addWidget(w, 1 if i == stretch_at else 0)
        else:
            r.addLayout(w)
    return r


def clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().hide()
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def sep() -> QFrame:
    f = QFrame()
    f.setProperty("role", "sep")
    return f


def page(title: str | None = None, scroll: bool = True, margins=(36, 16, 36, 36)) -> tuple[QWidget, QVBoxLayout]:
    """Page = title bar (18px, like the prototype .topbar) + a centred content column (max 1040px)."""
    outer = QWidget()
    outer.setObjectName("Page")
    ov = QVBoxLayout(outer)
    ov.setContentsMargins(0, 0, 0, 0)
    ov.setSpacing(0)
    body = QWidget()
    body.setObjectName("PageBody")
    row = QHBoxLayout(body)
    row.setContentsMargins(margins[0], margins[1], margins[2], margins[3])
    col = QWidget()
    col.setObjectName("PageBody")
    col.setMaximumWidth(MAX_W)
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(18)
    row.addStretch(0)
    row.addWidget(col, 1)
    row.addStretch(0)
    if title:
        t = label(title, "h1", wrap=False)
        t.setContentsMargins(0, 0, 0, 2)
        lay.addWidget(t)
    if scroll:
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(body)
        ov.addWidget(sc)
    else:
        ov.addWidget(body)
    return outer, lay


def empty_state(icon: str, title: str, text: str, action: str | None = None, slot=None,
                extra: list[str] | None = None) -> QFrame:
    """Centred icon in a soft circle + title + hint (+ optional button)."""
    f, lay = card(margins=(60, 40, 60, 40), spacing=10)
    ic = label("", "empty_icon", wrap=False)
    ic.setFixedSize(56, 56)
    ic.setAlignment(Qt.AlignCenter)

    def paint(_d=None):
        ic.setPixmap(theme.icon_pixmap(icon, theme.c("accent"), 26))
    paint()
    theme.on_theme(ic, paint)
    lay.addWidget(ic, 0, Qt.AlignHCenter)
    lay.addSpacing(4)
    t = label(title, "h2", wrap=False)
    t.setAlignment(Qt.AlignCenter)
    lay.addWidget(t, 0, Qt.AlignHCenter)
    s = label(text, "muted")
    s.setAlignment(Qt.AlignCenter)
    lay.addWidget(s)
    for x in extra or []:
        e = label(x, "path", selectable=True)
        e.setAlignment(Qt.AlignCenter)
        lay.addWidget(e)
    if action:
        lay.addSpacing(6)
        lay.addWidget(button(action, "primary", slot), 0, Qt.AlignHCenter)
    return f


def table(headers: list[str], rows: list[list], stretch: int | None = None) -> QWidget:
    """Prototype table: muted 12px header, 1px row separators. Cells are str or QWidget."""
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(18)
    g.setVerticalSpacing(8)
    n = len(headers)
    for j, h in enumerate(headers):
        g.addWidget(label(h, "th", wrap=False), 0, j)
    g.addWidget(sep(), 1, 0, 1, n)
    for i, r in enumerate(rows):
        for j, cell in enumerate(r):
            g.addWidget(cell if isinstance(cell, QWidget) else label(str(cell), wrap=False), 2 + 2 * i, j)
        g.addWidget(sep(), 3 + 2 * i, 0, 1, n)
    if stretch is not None:
        g.setColumnStretch(stretch, 1)
    return w


class Clickable(QFrame):
    """A hoverable row (QFrame role=row) that emits clicked."""
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setProperty("role", "row")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class ElidedLabel(QLabel):
    """Single-line label that paints its text elided with '…' to the width it is given (tooltip = full text).
    Size hints never depend on the text, so fixed-width table columns stay aligned (G6)."""

    def __init__(self, text: str = "", role: str | None = None):
        super().__init__()
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)   # not Ignored: QBoxLayout mis-sizes it next to fixed cells
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self._full = str(text or "")
        super().setText(self._full)
        self.setToolTip(self._full if len(self._full) > 12 else "")
        self.update()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):
        return QSize(120, self.fontMetrics().height() + 2)

    def minimumSizeHint(self):
        return QSize(16, self.fontMetrics().height() + 2)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        r = self.contentsRect()
        p.drawText(r, int(Qt.AlignLeft | Qt.AlignVCenter), self.fontMetrics().elidedText(self._full, Qt.ElideRight, r.width()))


class Segmented(QFrame):
    """iOS-like segmented control (prototype .seg / theme toggle): a soft track with one raised selected segment.
    options = [(key, text, icon_name|None)]; emits changed(key)."""
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str, str | None]], current: str | None = None, compact: bool = False):
        super().__init__()
        self.setProperty("role", "segbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons: dict[str, QPushButton] = {}
        self._icons = {}
        for key, text, ic in options:
            b = QPushButton(text)
            b.setProperty("role", "seg_small" if compact else "seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_current(k, emit=True))
            self.buttons[key] = b
            self._icons[key] = ic
            lay.addWidget(b, 1)
        self._cur = None
        if current != "":                  # "" = start with nothing selected (action-bar style)
            self.set_current(current or options[0][0])
        theme.on_theme(self, lambda _d=None: self._paint_icons())

    def current(self) -> str:
        return self._cur

    def set_current(self, key: str | None, emit: bool = False) -> None:
        if key is None:
            self._cur = None
            for b in self.buttons.values():
                b.setChecked(False)
            self._paint_icons()
            return
        if key not in self.buttons:
            return
        changed = key != self._cur
        self._cur = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self._paint_icons()
        if emit and changed:
            self.changed.emit(key)

    def _paint_icons(self) -> None:
        for k, b in self.buttons.items():
            if self._icons.get(k):
                b.setIcon(theme.icon(self._icons[k], theme.c("text" if k == self._cur else "muted"), 14))
                b.setIconSize(QSize(14, 14))


class Keycap(QLabel):
    """Small keyboard key (prototype .kbd) shown inside decision pills."""

    def __init__(self, key: str):
        super().__init__(key)
        self.setProperty("role", "keycap")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(18)
