"""All visual tokens + the one stylesheet (G3). Mirrors docs/design/ui_prototype (v0.2/v0.3 'Gemini desktop' look):
soft background, airy rounded cards with a faint shadow, pill buttons, gradient hero. No Google marks or icons.

Everything visual lives here: colour tokens (LIGHT/DARK), sizes (FONT/RADIUS/SPACE), the QSS, tinted Lucide icons
(icon()), card shadows (shadow()) and a tiny theme-change hook (on_theme()) for custom-painted widgets."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

ICON_DIR = Path(__file__).parent / "icons"

LIGHT = dict(bg="#f7f8fc", panel="#ffffff", side="#f0f2f8", line="#e3e6ef", text="#1f2330", muted="#6b7183",
             accent="#3d6df2", accent_soft="#e9effe", on_accent="#ffffff",
             ok="#1f8f4e", ok_soft="#e5f5ec", warn="#b26a00", warn_soft="#fff4e0", stop="#c62828", stop_soft="#fdeaea",
             info="#5b4bd1", info_soft="#efedfc", hover="#e7eaf3", field="#f7f8fc", teal="#138a9e", teal_soft="#e3f4f7",
             grad=("#4b7bf5", "#8a6cf0", "#d46aa8"), shadow=(30, 40, 80, 26), shadow_blur=28, shadow_dy=6)
DARK = dict(bg="#15171c", panel="#1e2128", side="#191b21", line="#2c303a", text="#eceef4", muted="#9aa1b2",
            accent="#7ea2ff", accent_soft="#232c45", on_accent="#0d1530",
            ok="#5fd08e", ok_soft="#1b3326", warn="#ffbf5c", warn_soft="#3a2e18", stop="#ff7b7b", stop_soft="#3d2224",
            info="#b4a6ff", info_soft="#2a2645", hover="#262a33", field="#171a20", teal="#4cc3d6", teal_soft="#173238",
            grad=("#7ea2ff", "#a98cff", "#e48cc0"), shadow=(0, 0, 0, 110), shadow_blur=14, shadow_dy=2)
for _p in (LIGHT, DARK):    # aliases used by older code paths
    _p.update(card=_p["panel"], sub=_p["muted"], soft=_p["accent_soft"], sel=_p["accent_soft"], ok_bg=_p["ok_soft"],
              err=_p["stop"], err_bg=_p["stop_soft"], warn_bg=_p["warn_soft"], input=_p["field"], log=_p["bg"],
              accent_text=_p["on_accent"], badge=_p["warn_soft"])

FONT = dict(base=14, small=12, tiny=11, h1=18, h2=16, hero=34, prompt=17, mono=12)
RADIUS = dict(card=22, panel=22, prompt=28, field=12, pill=999, option=16, slot=18, nav=18)
SANS = '"PingFang SC", ".AppleSystemUIFont", "Hiragino Sans GB", "Helvetica Neue", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif'
MONO = '"SF Mono", Menlo, "JetBrains Mono", "DejaVu Sans Mono", monospace'

_dark = False
_hooks: list = []


def is_dark() -> bool:
    return _dark


def palette(dark: bool | None = None) -> dict:
    return DARK if (_dark if dark is None else dark) else LIGHT


def c(key: str) -> str:
    return palette()[key]


# ---------- icons ----------
_cache: dict = {}


def icon_pixmap(name: str, color: str, size: int = 18, stroke: float | None = None) -> QPixmap:
    """Lucide SVG with stroke=currentColor recoloured; rendered at 2x for retina."""
    k = (name, color, size, stroke)
    if k in _cache:
        return _cache[k]
    from PySide6.QtSvg import QSvgRenderer
    svg = (ICON_DIR / f"{name}.svg").read_text("utf-8").replace("currentColor", color)
    if stroke:
        svg = svg.replace('stroke-width="2"', f'stroke-width="{stroke}"')
    r = QSvgRenderer(QByteArray(svg.encode()))
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[k] = pm
    return pm


def icon(name: str, color: str | None = None, size: int = 18, on: str | None = None) -> QIcon:
    """color/on are token names or #hex. `on` = colour when a checkable button is checked (nav selection)."""
    pal = palette()
    col = pal.get(color or "text", color or pal["text"])
    ic = QIcon()
    ic.addPixmap(icon_pixmap(name, col, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icon_pixmap(name, pal.get(on, on) if on else col, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(icon_pixmap(name, pal["muted"], size), QIcon.Disabled, QIcon.Off)
    return ic


# ---------- shadows + theme hooks ----------
def shadow(w: QWidget, level: str = "card") -> QWidget:
    """Soft card shadow (used sparingly: cards, prompt box, avatar, 新的精读)."""
    w._lit_shadow = level
    _apply_shadow(w)
    on_theme(w, lambda _d, w=w: _apply_shadow(w))
    return w


def _apply_shadow(w):
    pal = palette()
    r, g, b, a = pal["shadow"]
    strong = getattr(w, "_lit_shadow", "card") == "strong"
    eff = QGraphicsDropShadowEffect(w)
    eff.setBlurRadius(pal["shadow_blur"] * (1.6 if strong else 1))
    eff.setOffset(0, pal["shadow_dy"] * (1.8 if strong else 1))
    eff.setColor(QColor(r, g, b, min(255, int(a * (1.5 if strong else 1)))))
    w.setGraphicsEffect(eff)


def on_theme(widget: QWidget, fn) -> None:
    """Call fn(dark) on every theme change while widget is alive (custom painting, icons)."""
    _hooks.append((widget, fn))


def apply(dark: bool) -> None:
    global _dark
    _dark = dark
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(qss(dark))
    _cache.clear()
    from shiboken6 import isValid
    alive = []
    for w, fn in _hooks:
        if isValid(w):
            fn(dark)
            alive.append((w, fn))
    _hooks[:] = alive


def qss(dark: bool) -> str:
    p = palette(dark)
    f, r = FONT, RADIUS
    g0, g1, g2 = p["grad"]
    fam = f"font-family: {SANS};"
    return f"""
* {{ {fam} }}
QWidget {{ color: {p['text']}; font-size: {f['base']}px; }}
QMainWindow, #Main, #Page, #PageBody, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: {p['bg']}; }}
#Sidebar {{ background: {p['side']}; border: none; }}
#AppName {{ font-size: 17px; font-weight: 700; }}
#AppSub {{ color: {p['muted']}; font-size: {f['tiny']}px; }}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: {f['h1']}px; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: {f['h2']}px; font-weight: 600; }}
QLabel[role="title_lg"] {{ font-size: 19px; font-weight: 700; padding-bottom: 2px; }}
QLabel[role="sec"] {{ font-size: 15px; font-weight: 600; }}
QLabel[role="chip_num"] {{ background: {p['accent_soft']}; color: {p['accent']}; border-radius: 6px; padding: 1px 7px;
    font-size: 11px; font-weight: 700; }}
QLabel[role="fieldk"] {{ color: {p['muted']}; font-size: 12px; font-weight: 600; padding-top: 3px; }}
QLabel[role="fieldv"] {{ font-size: 13px; line-height: 150%; }}
QLabel[role="fieldv_b"] {{ font-size: 13px; font-weight: 600; }}
QLabel[role="tagchip"] {{ background: {p['hover']}; color: {p['muted']}; border-radius: 8px; padding: 1px 8px; font-size: 11px; }}
QFrame[role="field_click"] {{ background: transparent; border: 1px solid transparent; border-radius: 8px; }}
QFrame[role="field_click"]:hover {{ background: {p['field']}; border: 1px dashed {p['line']}; }}
QLabel[role="h3"] {{ font-size: {f['base']}px; font-weight: 600; }}
QLabel[role="lead"] {{ color: {p['muted']}; font-size: 15px; }}
QLabel[role="sub"] {{ color: {p['muted']}; font-size: {f['small']}px; }}
QLabel[role="muted"] {{ color: {p['muted']}; }}
QLabel[role="th"] {{ color: {p['muted']}; font-size: {f['small']}px; font-weight: 600; }}
QLabel[role="strong"] {{ font-weight: 600; }}
QLabel[role="path"] {{ font-family: {MONO}; font-size: {f['small']}px; color: {p['muted']}; }}
QLabel[role="kbd"] {{ font-family: {MONO}; font-size: {f['tiny']}px; color: {p['muted']}; border: 1px solid {p['line']};
    border-radius: 5px; padding: 0px 5px; background: {p['bg']}; }}
QLabel[role="kbd_on"] {{ font-family: {MONO}; font-size: {f['tiny']}px; color: {p['on_accent']}; border: 1px solid {p['on_accent']};
    border-radius: 5px; padding: 0px 5px; }}
QLabel[role="opt_title"] {{ font-weight: 600; }}
QLabel[role="opt_title_on"] {{ font-weight: 600; color: {p['on_accent']}; }}
QLabel[role="opt_detail"] {{ color: {p['muted']}; font-size: {f['small']}px; }}
QLabel[role="empty_icon"] {{ background: {p['accent_soft']}; border-radius: 28px; }}
QLabel[role="dot_ok"] {{ background: {p['ok']}; border-radius: 3px; }}
QLabel[role="dot_warn"] {{ background: {p['warn']}; border-radius: 3px; }}
QLabel[role="dot_stop"] {{ background: {p['stop']}; border-radius: 3px; }}
QLabel[role="pill_trial"], QLabel[role="badge"], QLabel[role="trial"] {{ background: {p['warn_soft']}; color: {p['warn']};
    border-radius: 10px; padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="pill_ok"] {{ background: {p['ok_soft']}; color: {p['ok']}; border-radius: 10px; padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="pill_stop"] {{ background: {p['stop_soft']}; color: {p['stop']}; border-radius: 10px; padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="pill_info"] {{ background: {p['info_soft']}; color: {p['info']}; border-radius: 10px; padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="pill_acc"], QLabel[role="badge_run"] {{ background: {p['accent_soft']}; color: {p['accent']}; border-radius: 10px;
    padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="pill_gray"] {{ background: {p['hover']}; color: {p['muted']}; border-radius: 10px; padding: 2px 10px; font-size: {f['tiny']}px; font-weight: 600; }}
QLabel[role="warn"], QLabel[role="alert_warn"] {{ background: {p['warn_soft']}; color: {p['text']}; border-radius: 16px; padding: 11px 16px; }}
QLabel[role="ok"], QLabel[role="alert_ok"] {{ background: {p['ok_soft']}; color: {p['text']}; border-radius: 16px; padding: 11px 16px; }}
QLabel[role="err"], QLabel[role="alert_stop"] {{ background: {p['stop_soft']}; color: {p['text']}; border-radius: 16px; padding: 11px 16px; }}
QLabel[role="info"], QLabel[role="alert_info"] {{ background: {p['accent_soft']}; color: {p['text']}; border-radius: 16px; padding: 11px 16px; }}
QFrame[role="card"], QFrame[role="panel"] {{ background: {p['panel']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: {r['card']}px; }}
QFrame[role="slot"] {{ background: {p['bg']}; border: none; border-radius: {r['slot']}px; }}
QFrame[role="inset"] {{ background: {p['bg']}; border: none; border-radius: 16px; }}
QFrame[role="prompt"] {{ background: {p['panel']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: {r['prompt']}px; }}
QFrame[role="bar"] {{ background: {p['panel']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: 16px; }}
QFrame[role="sep"] {{ background: {p['line']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[role="row"] {{ background: transparent; border: none; border-radius: 12px; }}
QFrame[role="row"]:hover {{ background: {p['hover']}; }}
QFrame[role="trow"] {{ background: transparent; border: none; border-radius: 10px; }}
QFrame[role="trow"]:hover {{ background: {p['hover']}; }}
QFrame[role="trow_sel"] {{ background: {p['accent_soft']}; border: none; border-left: 3px solid {p['accent']}; border-radius: 10px; }}
QFrame[role="drawer"] {{ background: {p['panel']}; border: none; border-left: 1px solid {p['line']}; }}
QWidget[role="scrim"] {{ background: rgba(20, 25, 45, 60); }}
QPushButton {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 15px; padding: 7px 18px; font-weight: 500; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; border-color: {p['line']}; }}
QPushButton[role="primary"] {{ background: {p['accent']}; color: {p['on_accent']}; border: 1px solid {p['accent']}; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {p['accent']}; border-color: {g1}; }}
QPushButton[role="primary"]:disabled {{ background: {p['line']}; border-color: {p['line']}; color: {p['muted']}; }}
QPushButton[role="danger"] {{ color: {p['stop']}; }}
QPushButton[role="small"] {{ padding: 4px 12px; font-size: {f['small']}px; border-radius: 12px; }}
QPushButton[role="option"] {{ text-align: left; padding: 0; border-radius: {r['option']}px; background: {p['panel']}; border: 1px solid {p['line']}; }}
QPushButton[role="option"]:hover {{ border-color: {p['accent']}; background: {p['panel']}; }}
QPushButton[role="option_default"] {{ text-align: left; padding: 0; border-radius: {r['option']}px; background: {p['accent_soft']};
    border: 2px solid {p['accent']}; }}
QPushButton[role="choice"] {{ padding: 0; border-radius: 15px; }}
QPushButton[role="choice_primary"] {{ padding: 0; border-radius: 15px; background: {p['accent']}; border: 1px solid {p['accent']}; }}
QPushButton[role="choice_primary"]:hover {{ background: {p['accent']}; border-color: {g1}; }}
QPushButton[role="new"] {{ background: {p['panel']}; border: none; border-radius: 16px; padding: 11px 16px; font-weight: 600; text-align: left; }}
QPushButton[role="new"]:hover {{ background: {p['panel']}; }}
QPushButton[role="nav"] {{ background: transparent; border: none; border-radius: {r['nav']}px; padding: 9px 14px; text-align: left; }}
QPushButton[role="nav"]:hover {{ background: {p['hover']}; }}
QPushButton[role="nav"]:checked {{ background: {p['accent_soft']}; color: {p['accent']}; font-weight: 600; }}
QPushButton[role="send"] {{ background: {p['accent']}; border: none; border-radius: 20px; min-width: 40px; min-height: 40px;
    max-width: 40px; max-height: 40px; padding: 0; }}
QPushButton[role="send"]:disabled {{ background: {p['line']}; }}
QPushButton[role="chip"] {{ background: {p['panel']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: 14px;
    padding: 6px 14px; font-size: {f['small']}px; }}
QPushButton[role="chip"]:hover {{ background: {p['accent_soft']}; color: {p['accent']}; }}
QPushButton[role="link"] {{ background: transparent; border: none; color: {p['accent']}; padding: 2px 0; font-weight: 600;
    font-size: {f['small']}px; }}
QPushButton[role="link"]:hover {{ background: transparent; text-decoration: underline; }}
QPushButton[role="dashed"] {{ background: transparent; border: 1.5px dashed {p['line']}; border-radius: {r['slot']}px; padding: 12px;
    color: {p['muted']}; }}
QPushButton[role="dashed"]:hover {{ border-color: {p['accent']}; color: {p['accent']}; background: transparent; }}
QPushButton[role="row"] {{ background: transparent; border: none; border-radius: 12px; padding: 0; text-align: left; }}
QPushButton[role="row"]:hover {{ background: {p['hover']}; }}
QLineEdit, QComboBox, QDoubleSpinBox {{ background: {p['field']}; border: 1px solid {p['line']}; border-radius: {r['field']}px;
    padding: 7px 12px; selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {p['accent']}; }}
QLineEdit:disabled {{ color: {p['muted']}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url({_chevron(p['muted'])}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['line']}; border-radius: 10px;
    selection-background-color: {p['accent_soft']}; selection-color: {p['accent']}; padding: 4px; outline: 0; }}
QPlainTextEdit[role="prompt"] {{ border: none; background: transparent; font-size: {f['prompt']}px; padding: 0;
    selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; }}
QPlainTextEdit[role="log"] {{ background: {p['bg']}; border: none; border-radius: 14px; padding: 8px 10px;
    font-family: {MONO}; font-size: {f['mono']}px; selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; }}
QTextBrowser {{ background: {p['panel']}; border: none; padding: 4px 6px; selection-background-color: {p['accent_soft']}; }}
QProgressBar {{ background: {p['line']}; border: none; border-radius: 4px; min-height: 6px; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {g0}, stop:1 {g1}); border-radius: 3px; }}
QTabWidget::pane {{ border: none; }}
QTabWidget::tab-bar {{ left: 0; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: {p['side']}; color: {p['text']}; padding: 7px 20px; margin: 0; border: none; font-weight: 500; }}
QTabBar::tab:first {{ border-top-left-radius: 17px; border-bottom-left-radius: 17px; padding-left: 22px; }}
QTabBar::tab:last {{ border-top-right-radius: 17px; border-bottom-right-radius: 17px; padding-right: 22px; }}
QTabBar::tab:selected {{ background: {p['panel']}; color: {p['accent']}; font-weight: 600; border: 4px solid {p['side']};
    border-radius: 15px; padding: 3px 16px; }}
QListWidget {{ background: transparent; border: none; padding: 0; outline: 0; }}
QListWidget::item {{ background: {p['bg']}; border: 2px solid transparent; border-radius: 16px; padding: 10px 12px; margin: 0 0 8px 0; color: {p['text']}; }}
QListWidget::item:hover {{ border-color: {p['line']}; }}
QListWidget::item:selected {{ background: {p['accent_soft']}; border: 2px solid {p['accent']}; color: {p['text']}; }}
QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 34px; height: 20px; border-radius: 10px; background: {p['line']}; image: url({_knob('left')}); }}
QCheckBox::indicator:checked {{ background: {p['ok']}; image: url({_knob('right')}); }}
QCheckBox::indicator:disabled {{ background: {p['hover']}; }}
QCheckBox:disabled {{ color: {p['muted']}; }}
QMenuBar {{ background: {p['side']}; color: {p['text']}; }}
QMenuBar::item:selected {{ background: {p['hover']}; }}
QMenu {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['line']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['accent_soft']}; color: {p['accent']}; }}
QToolTip {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 4px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['line']}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['line']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; width: 0; background: transparent; }}
QFrame[role="segbar"] {{ background: {p['hover'] if not dark else p['bg']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: 10px; }}
QPushButton[role="seg"], QPushButton[role="seg_small"] {{ background: transparent; border: none; border-radius: 8px; padding: 5px 10px;
    color: {p['muted']}; font-weight: 500; }}
QPushButton[role="seg_small"] {{ padding: 4px 6px; font-size: {f['tiny']}px; }}
QPushButton[role="seg"]:hover, QPushButton[role="seg_small"]:hover {{ color: {p['text']}; background: transparent; }}
QPushButton[role="seg"]:checked, QPushButton[role="seg_small"]:checked {{ background: {p['panel']}; color: {p['text']}; font-weight: 600;
    border: 1px solid {p['line']}; }}
QLabel[role="keycap"] {{ font-family: {MONO}; font-size: {f['tiny']}px; color: {p['muted']}; background: {p['panel']};
    border: 1px solid {p['line']}; border-bottom: 2px solid {p['line']}; border-radius: 5px; padding: 0px 5px; }}
QLabel[role="keycap_on"] {{ font-family: {MONO}; font-size: {f['tiny']}px; color: {p['accent']}; background: {p['on_accent']};
    border: none; border-radius: 5px; padding: 0px 5px; font-weight: 700; }}
QPushButton[role="decide"] {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 18px; padding: 0; }}
QPushButton[role="decide"]:hover {{ border-color: {p['accent']}; background: {p['panel']}; }}
QPushButton[role="decide_default"] {{ background: {p['accent']}; border: 1px solid {p['accent']}; border-radius: 18px; padding: 0; }}
QPushButton[role="decide_default"]:hover {{ background: {p['accent']}; border-color: {g1}; }}
QLabel[role="decide_t"] {{ font-weight: 600; }}
QLabel[role="decide_t_on"] {{ font-weight: 600; color: {p['on_accent']}; }}
QFrame[role="cand"] {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 16px; }}
QFrame[role="cand"]:hover {{ border-color: {p['accent']}; }}
QFrame[role="cand_on"] {{ background: {p['accent_soft']}; border: 2px solid {p['accent']}; border-radius: 16px; }}
QFrame[role="instr"] {{ background: {p['panel']}; border: 1px solid {p['line'] if dark else 'transparent'}; border-radius: 16px; }}
QFrame[role="slotcard"] {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 18px; }}
QFrame[role="slotcard_main"] {{ background: {p['panel']}; border: 2px solid {p['accent']}; border-radius: 18px; }}
QFrame[role="hdr"] {{ background: transparent; border: none; }}
QLabel[role="cal_ok"] {{ background: {p['ok_soft']}; color: {p['ok']}; border-radius: 9px; padding: 2px 9px; font-size: {f['tiny']}px; font-weight: 600; }}
QLabel[role="cal_def"] {{ background: {p['warn_soft']}; color: {p['warn']}; border-radius: 9px; padding: 2px 9px; font-size: {f['tiny']}px; font-weight: 600; }}
QFrame[role="caldot"] {{ background: {p['line']}; border: none; border-radius: 2px; }}
QFrame[role="caldot_on"] {{ background: {p['ok']}; border: none; border-radius: 2px; }}
QLabel[role="cal_txt_ok"] {{ color: {p['ok']}; font-size: {f['small']}px; }}
QLabel[role="tag_mt"] {{ background: {p['info_soft']}; color: {p['info']}; border-radius: 6px; padding: 1px 6px; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="num"] {{ font-family: {MONO}; font-size: {f['small']}px; }}
QLabel[role="version"] {{ color: {p['muted']}; font-size: {f['tiny']}px; font-family: {MONO}; }}
QWidget#UpdateDot {{ background: {p['stop']}; border-radius: 3px; }}
QLabel#Toast {{ background: {p['text']}; color: {p['panel']}; border-radius: 8px; padding: 6px 14px; }}
QFrame#Popover {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 14px; }}
QFrame#UpdateBar {{ background: {p['accent_soft']}; border: none; border-radius: 0; }}
QLabel[role="stepnum"] {{ background: {p['panel']}; color: {p['muted']}; border: 1.5px solid {p['line']}; border-radius: 13px;
    font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="stepnum_on"] {{ background: {p['accent']}; color: {p['on_accent']}; border: 1.5px solid {p['accent']}; border-radius: 13px;
    font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="stepnum_done"] {{ background: {p['ok']}; color: {p['on_accent']}; border: 1.5px solid {p['ok']}; border-radius: 13px; }}
QLabel[role="stepnum_skip"] {{ background: {p['hover']}; color: {p['muted']}; border: 1.5px dashed {p['line']}; border-radius: 13px;
    font-size: {f['tiny']}px; }}
QLabel[role="steplbl"] {{ color: {p['muted']}; font-size: {f['tiny']}px; }}
QLabel[role="steplbl_on"] {{ color: {p['accent']}; font-size: {f['tiny']}px; font-weight: 700; }}
QLabel[role="steplbl_done"] {{ color: {p['text']}; font-size: {f['tiny']}px; }}
QLabel[role="steplbl_skip"] {{ color: {p['muted']}; font-size: {f['tiny']}px; text-decoration: line-through; }}
QTextBrowser[role="note"] {{ background: {p['panel']}; border: none; padding: 8px 18px; }}
QMessageBox QLabel {{ font-size: {f['base']}px; }}
"""


_asset_dir: Path | None = None


def _assets() -> Path:
    """Small generated PNGs referenced from QSS (url() needs files): combo chevron + switch knob."""
    global _asset_dir
    if _asset_dir is None:
        import tempfile
        _asset_dir = Path(tempfile.mkdtemp(prefix="litreader_qss_"))
    return _asset_dir


def _chevron(color: str) -> str:
    p = _assets() / f"chevron_{color.strip('#')}.png"
    if not p.exists():
        from PySide6.QtSvg import QSvgRenderer
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="2.4" ' \
              'stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>' % color
        pm = QPixmap(28, 28)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        QSvgRenderer(QByteArray(svg.encode())).render(q)
        q.end()
        pm.save(str(p))
    return p.as_posix()


def _knob(side: str) -> str:
    p = _assets() / f"knob_{side}.png"
    if not p.exists():
        pm = QPixmap(68, 40)
        pm.fill(Qt.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(0, 0, 0, 40))
        x = 4 if side == "left" else 32
        q.drawEllipse(x, 5, 32, 32)
        q.setBrush(QColor("#ffffff"))
        q.drawEllipse(x, 4, 32, 32)
        q.end()
        pm.save(str(p))
    return p.as_posix()
