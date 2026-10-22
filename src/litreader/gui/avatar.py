"""App avatar. Default = an original monogram drawn in code (no third-party artwork). The user can pick their own
image (png/jpg/webp): cropped to a square (circle shown), saved as a 256 px PNG copy in <app data>/gui/avatar.png;
the original file is never modified. 恢复默认 removes only that copy."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget)

SIZE = 256
IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp)"


def default_avatar(size: int = SIZE) -> QPixmap:
    """Monogram 'L' on a soft blue-violet gradient, rounded square (original artwork)."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4f7cff"))
    g.setColorAt(1, QColor("#9b6bff"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    p.fillPath(path, g)
    # a small "page" accent: litreader = reading
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 46))
    p.drawRoundedRect(QRectF(size * 0.56, size * 0.18, size * 0.24, size * 0.30), size * 0.04, size * 0.04)
    f = QFont()
    f.setFamilies(["Helvetica Neue", "Arial", "DejaVu Sans"])
    f.setPixelSize(int(size * 0.62))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, size * 0.02, size, size), Qt.AlignCenter, "L")
    p.end()
    return QPixmap.fromImage(img)


def rounded(pm: QPixmap, size: int, circle: bool = False) -> QPixmap:
    pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    if circle:
        path.addEllipse(QRectF(0, 0, size, size))
    else:
        path.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def current(prefs) -> QPixmap:
    if prefs.get("avatar") == "custom" and prefs.avatar_path.is_file():
        pm = QPixmap(str(prefs.avatar_path))
        if not pm.isNull():
            return pm
    return default_avatar()


def crop_square(img: QImage, zoom: float = 1.0, cx: float = 0.5, cy: float = 0.5, size: int = SIZE) -> QImage:
    """Square crop: side = min(w, h) / zoom, centred at (cx, cy) in 0..1 (clamped inside the image)."""
    w, h = img.width(), img.height()
    side = max(1, int(min(w, h) / max(1.0, zoom)))
    x = int(min(max(cx * w - side / 2, 0), w - side))
    y = int(min(max(cy * h - side / 2, 0), h - side))
    return img.copy(x, y, side, side).scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def save_custom(img: QImage, prefs) -> Path:
    prefs.dir.mkdir(parents=True, exist_ok=True)
    tmp = prefs.avatar_path.with_suffix(".tmp.png")
    if not img.save(str(tmp), "PNG"):
        raise OSError("头像保存失败")
    tmp.replace(prefs.avatar_path)
    prefs.set("avatar", "custom")
    return prefs.avatar_path


def reset_default(prefs) -> None:
    if prefs.avatar_path.is_file():
        prefs.avatar_path.unlink()   # only our own copy in the app data dir
    prefs.set("avatar", "default")


class _CropView(QWidget):
    changed = Signal()

    def __init__(self, img: QImage):
        super().__init__()
        self.img, self.zoom, self.cx, self.cy = img, 1.0, 0.5, 0.5
        self._drag = None
        self.setMinimumSize(300, 300)
        self.setCursor(Qt.OpenHandCursor)

    def preview(self) -> QImage:
        return crop_square(self.img, self.zoom, self.cx, self.cy, 300)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        ox, oy = (self.width() - s) / 2, (self.height() - s) / 2
        p.drawImage(QRectF(ox, oy, s, s), self.preview())
        dim = QPainterPath()
        dim.addRect(QRectF(ox, oy, s, s))
        hole = QPainterPath()
        hole.addEllipse(QRectF(ox, oy, s, s))
        p.fillPath(dim.subtracted(hole), QColor(0, 0, 0, 110))
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.drawEllipse(QRectF(ox + 1, oy + 1, s - 2, s - 2))
        p.end()

    def mousePressEvent(self, e):
        self._drag = (e.position(), self.cx, self.cy)
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        start, cx0, cy0 = self._drag
        d: QPointF = e.position() - start
        s = min(self.width(), self.height())
        side = min(self.img.width(), self.img.height()) / self.zoom
        self.cx = cx0 - d.x() / s * side / self.img.width()
        self.cy = cy0 - d.y() / s * side / self.img.height()
        self.cx, self.cy = min(max(self.cx, 0), 1), min(max(self.cy, 0), 1)
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)


class CropDialog(QDialog):
    """Drag to move, slider to zoom; the circle shows how the avatar will look."""

    def __init__(self, img: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("裁剪头像")
        self.view = _CropView(img)
        zoom = QSlider(Qt.Horizontal)
        zoom.setRange(100, 400)
        zoom.valueChanged.connect(lambda v: (setattr(self.view, "zoom", v / 100), self.view.update()))
        lay = QVBoxLayout(self)
        tip = QLabel("拖动图片调整位置，滑块缩放。原图不会被修改，只保存一份 256×256 的副本。")
        tip.setProperty("role", "sub")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("缩放"))
        row.addWidget(zoom, 1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("使用这张")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(420, 520)

    def result_image(self) -> QImage:
        return crop_square(self.view.img, self.view.zoom, self.view.cx, self.view.cy, SIZE)


def load_image(path: str | Path) -> QImage | None:
    if Path(path).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return None
    img = QImage(str(path))
    return None if img.isNull() else img
