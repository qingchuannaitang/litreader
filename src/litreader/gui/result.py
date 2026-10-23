"""结果页 (G7, approved mockup ui_shots/result_redesign/state_d.html):
  ① 「刚刚精读」 card — the paper just read (or the one opened from 主页) + action bar
     (segmented 笔记预览 / 证据摘要 / 用量 · 在 Obsidian 打开 · 在 Zotero 打开 · 显示文件位置);
  ② 「最近精读的笔记」 — one row per paper (latest run), the just-read paper excluded, Chinese title first,
     5 rows per page with 上一页 / 下一页; the same action bar acts on the selected row (grey when none);
  ③ a RIGHT DRAWER (~640 px, dim overlay; Esc / ✕ close) opened by any segment: segment switch inside, follows the
     list selection; the note preview shows only 论文信息 + 三分钟了解论文 + 「在 Obsidian 打开完整笔记」.
Shortcuts: ↑↓ select · Enter 笔记预览 · Esc close · ←→ page · ⌘O 在 Obsidian 打开.
The note is rendered by note_html.py into a QTextBrowser (no QtWebEngine)."""
from __future__ import annotations

from litreader.platform_words import file_manager_name
import json
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget

from ..llm.models import ROLES
from . import note_html, runner, theme
from .home import RecentList
from .widgets import (ElidedLabel, Segmented, button, card, clear, empty_state, hrow, label, page, path_label, pill,
                      table)

STAT_ZH = [("facts_ok", "核对通过的事实"), ("statements_and_tables_ok", "核对通过的陈述/表格"), ("figures", "图表"),
           ("unknowns_in_note", "笔记中的 UNKNOWN"), ("rejected", "被拒绝的说法"), ("duplicates", "重复合并"),
           ("inference_numbers_flagged", "推断中被标记的数字"), ("wording_changes", "措辞修正"),
           ("figures_without_model_text", "无模型描述的图"), ("meta_unknown", "元数据缺失项")]
SEGS = [("note", "笔记预览", None), ("evidence", "证据摘要", None), ("usage", "用量", None)]
DRAWER_W = 640
PER_PAGE = 5


def reveal(path: str, opener=None, runner=None) -> None:
    """Show the file in the system file manager: macOS `open -R` (Finder selects it), Windows
    `explorer /select,<path>` (资源管理器 selects it; list args, no shell); elsewhere open the folder."""
    p = Path(path)
    mac, win = sys.platform == "darwin", sys.platform.startswith("win")
    if opener is None and p.exists() and (mac or win):
        import subprocess
        run = runner or subprocess.Popen
        if mac:
            run(["open", "-R", str(p)])
        else:
            run(["explorer", f"/select,{p}"] if p.is_file() else ["explorer", str(p)])
        return
    (opener or QDesktopServices.openUrl)(QUrl.fromLocalFile(str(p.parent if p.is_file() else p)))


def full_receipt(r: dict) -> dict:
    """A recent_receipts() row carries the receipt path: merge the full JSON (stats, actual …) under it."""
    path = r.get("receipt") if isinstance(r.get("receipt"), str) else None
    if path:
        try:
            full = json.loads(Path(path).read_text("utf-8"))
            if isinstance(full, dict):
                return {**full, **{k: v for k, v in r.items() if v not in (None, {}, "")}}
        except (OSError, ValueError):
            pass
    return r


def is_ok(r: dict | None) -> bool:
    return bool(r) and (r.get("status") or r.get("status_code")) == "DRY_RUN_COMPLETE"


def row_of(r: dict) -> dict:
    return r.get("row") or runner.paper_row(r)


class ActionBar(QWidget):
    """segmented 笔记预览 / 证据摘要 / 用量 (opens the drawer) + 在 Obsidian 打开 / 在 Zotero 打开 / 显示文件位置."""
    segment = Signal(str)
    obsidian = Signal()
    zotero = Signal()
    reveal = Signal()

    def __init__(self, primary: bool = True):
        super().__init__()
        self.seg = Segmented(SEGS, "")
        for k, b in self.seg.buttons.items():
            b.clicked.connect(lambda _=False, k=k: (self.seg.set_current(None), self.segment.emit(k)))
        self.obs_btn = button("在 Obsidian 打开", "primary" if primary else None, lambda: self.obsidian.emit(),
                              "在 Obsidian 中打开这篇笔记（⌘O）")
        self.zot_btn = button("在 Zotero 打开", None, lambda: self.zotero.emit(), "zotero://select —— 在 Zotero 里选中这篇条目")
        self.rev_btn = button("显示文件位置", None, lambda: self.reveal.emit(), f"在{file_manager_name()}中显示笔记文件")
        h = hrow(self.seg, None, self.obs_btn, self.zot_btn, self.rev_btn, spacing=8)
        h.setContentsMargins(0, 0, 0, 0)
        self.setLayout(h)

    def set_target(self, r: dict | None):
        ok = is_ok(r)
        for b in self.seg.buttons.values():
            b.setEnabled(bool(r))
        self.seg.buttons["note"].setEnabled(ok and bool(r.get("note")))
        self.obs_btn.setEnabled(ok and bool(r.get("note")))
        self.rev_btn.setEnabled(ok and bool(r.get("note")))
        self.zot_btn.setEnabled(bool(r) and bool(note_html.item_key_of(r)))
        tip = "" if r else "先在列表里选中一篇"
        for w in (self.seg, self.obs_btn, self.zot_btn, self.rev_btn):
            w.setToolTip(tip or w.toolTip())


class PaperHead(QWidget):
    """Title + grey meta line · status pill · topic · date · E-level (same columns as the list)."""

    def __init__(self):
        super().__init__()
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(0, 0, 0, 0)
        self.h.setSpacing(16)

    def set(self, r: dict):
        clear(self.h)
        d = row_of(r)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        t = ElidedLabel(d.get("title") or "（未识别论文）", "h2")
        v.addWidget(t)
        if d.get("meta"):
            v.addWidget(ElidedLabel(d["meta"], "sub"))
        self.h.addWidget(box, 1)
        self.h.addWidget(pill(d.get("status") or "?", d.get("status_kind") or "gray"))
        self.h.addWidget(label(("📁 " + d["topic"]) if d.get("topic") else "—", None, wrap=False))
        self.h.addWidget(label(d.get("date") or "—", "muted", wrap=False))
        if d.get("e_level"):
            self.h.addWidget(pill(d["e_level"], d.get("e_kind") or "acc"))


class Drawer(QFrame):
    closed = Signal()

    def __init__(self, page_: "ResultPage"):
        super().__init__(page_)
        self.setProperty("role", "drawer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        theme.shadow(self, "strong")
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 22)
        v.setSpacing(10)
        self.heading = label("笔记预览", "h2", wrap=False)
        self.tabs = Segmented(SEGS, "note")
        self.close_btn = button("关闭", None, lambda: self.closed.emit(), "关闭（Esc）", icon="x")
        v.addLayout(hrow(self.heading, None, self.tabs, self.close_btn, spacing=8))
        self.title = ElidedLabel("", "strong")
        self.meta = ElidedLabel("", "sub")
        v.addWidget(self.title)
        v.addWidget(self.meta)
        self.stack = QStackedWidget()
        self.preview = QTextBrowser()
        self.preview.setProperty("role", "note")
        self.preview.setOpenLinks(False)
        self.stack.addWidget(self.preview)
        self.ev_card, self.ev = card(spacing=12, shadow=False, margins=(4, 4, 4, 4))
        self.stack.addWidget(self.ev_card)
        self.usage_card, self.usage = card(spacing=12, shadow=False, margins=(4, 4, 4, 4))
        self.stack.addWidget(self.usage_card)
        v.addWidget(self.stack, 1)
        self.full_link = button("在 Obsidian 打开完整笔记 →", "link", None, "预览只显示前两块；完整笔记在 Obsidian 中")
        v.addLayout(hrow(label("只显示前两块（论文信息、三分钟了解论文）", "sub", wrap=False), self.full_link, None, spacing=6))
        self.actions = ActionBar()
        self.actions.seg.setVisible(False)
        v.addWidget(self.actions)
        self.hide()


class ResultPage(QWidget):
    go_home = Signal()

    def __init__(self, opener=None):
        super().__init__()
        self.setObjectName("Page")
        self.setFocusPolicy(Qt.StrongFocus)
        self.opener = opener or QDesktopServices.openUrl     # injectable for tests
        self.r, self.cfg = None, None          # the 「刚刚精读」 paper
        self.target = None                     # what the drawer shows: self.r or the selected list row
        self.just = True
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, self.lay = page("结果页", scroll=False)
        self.lay.setSpacing(14)
        outer.addWidget(body)
        self.empty_card = empty_state("file-search", "还没有结果",
                                      "精读完成后，这里会显示刚刚精读的论文和最近精读的笔记。也可以在主页的「最近精读」里点一篇。",
                                      "去主页", lambda: self.go_home.emit())
        self.lay.addWidget(self.empty_card)

        # ① 刚刚精读
        self.top_card, tl = card(margins=(22, 16, 22, 16), spacing=10)
        self.top_title = label("刚刚精读", "h2", wrap=False)
        self.top_sub = label("", "sub", wrap=False)
        tl.addLayout(hrow(self.top_title, self.top_sub, None, spacing=10))
        self.head = PaperHead()
        tl.addWidget(self.head)
        self.stop_box = label("", "warn")
        tl.addWidget(self.stop_box)
        self.top_bar = ActionBar()
        tl.addWidget(self.top_bar)
        self.lay.addWidget(self.top_card)

        # ② 最近精读的笔记
        self.list_card, ll = card(margins=(22, 16, 22, 14), spacing=8)
        ll.addLayout(hrow(label("最近精读的笔记", "h2", wrap=False),
                          label("每篇一行（同一篇多次精读只显示最新） · ↑↓ 选择 · 回车 = 笔记预览", "sub", wrap=False), None,
                          spacing=10))
        self.list = RecentList(selectable=True, per_page=PER_PAGE)
        ll.addWidget(self.list)
        self.list_empty = label("还没有其他精读记录。", "muted")
        ll.addWidget(self.list_empty)
        ll.addWidget(self.list.pager())
        self.list_bar = ActionBar(primary=False)
        ll.addWidget(self.list_bar)
        self.lay.addWidget(self.list_card)
        self.lay.addStretch(1)

        # ③ drawer + scrim (children of the page, positioned in resizeEvent)
        self.scrim = QWidget(self)
        self.scrim.setProperty("role", "scrim")
        self.scrim.setAttribute(Qt.WA_StyledBackground, True)
        self.scrim.hide()
        self.scrim.installEventFilter(self)
        self.drawer = Drawer(self)
        self.drawer.closed.connect(self.close_drawer)
        self.drawer.tabs.changed.connect(self._tab)
        self.drawer.preview.anchorClicked.connect(self._link)
        self.drawer.full_link.clicked.connect(self._open_obsidian_target)
        a = self.drawer.actions
        a.obsidian.connect(self._open_obsidian_target)
        a.zotero.connect(lambda: self._zotero(self.target))
        a.reveal.connect(lambda: self._reveal_of(self.target))
        # compatibility handles (tests / app): preview, tabs, stack
        self.preview, self.tabs, self.stack = self.drawer.preview, self.drawer.tabs, self.drawer.stack

        self.top_bar.segment.connect(lambda k: self.open_drawer(self.r, k))
        self.top_bar.obsidian.connect(self._open_obsidian)
        self.top_bar.zotero.connect(self._open_zotero)
        self.top_bar.reveal.connect(self._reveal)
        self.list_bar.segment.connect(lambda k: self.open_drawer(self.list.current(), k))
        self.list_bar.obsidian.connect(lambda: self._obsidian(self.list.current()))
        self.list_bar.zotero.connect(lambda: self._zotero(self.list.current()))
        self.list_bar.reveal.connect(lambda: self._reveal_of(self.list.current()))
        self.list.selected.connect(self._on_select)

        for seq, fn in (("Up", lambda: self._key_move(-1)), ("Down", lambda: self._key_move(1)),
                        ("Left", lambda: self.list.page_by(-1)), ("Right", lambda: self.list.page_by(1)),
                        ("Return", self._enter), ("Enter", self._enter), ("Escape", self.close_drawer),
                        (QKeySequence.StandardKey.Open, self._cmd_o)):
            sc = QShortcut(QKeySequence(seq) if isinstance(seq, str) else QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
        theme.on_theme(self, lambda _d: self._render_target())
        self.empty()

    # ---------- layout ----------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def _place(self):
        w, h = self.width(), self.height()
        self.scrim.setGeometry(0, 0, w, h)
        dw = min(DRAWER_W, max(360, w - 120))
        self.drawer.setGeometry(w - dw, 0, dw, h)

    def eventFilter(self, obj, ev):
        if obj is self.scrim and ev.type() == QEvent.MouseButtonRelease:
            self.close_drawer()
            return True
        return super().eventFilter(obj, ev)

    # ---------- state ----------
    def empty(self):
        self.r = None
        self.close_drawer()
        self.top_card.setVisible(False)
        self.empty_card.setVisible(not self.list.count())
        self.top_bar.set_target(None)
        self.list_bar.set_target(self.list.current())
        self.drawer.preview.setHtml("")
        self.list_card.setVisible(bool(self.list.count()))

    def load(self, r: dict, cfg=None, just: bool = True):
        """r: a receipt (realrun.run return value) or a recent_receipts() entry. just=False when opened from 主页."""
        self.r, self.cfg, self.just = full_receipt(r), cfg, just
        r = self.r
        self.empty_card.setVisible(False)
        self.top_card.setVisible(True)
        ok = is_ok(r)
        self.top_title.setText("刚刚精读" if just else "所选精读")
        d = row_of(r)
        self.top_sub.setText(f"{d.get('date') or ''} {'完成' if ok else '未完成'}".strip())
        self.head.set(r)
        self.stop_box.setVisible(not ok)
        self.stop_box.setText(("⚑ 这次精读没有完成，没有写入任何笔记：" + (r.get("reason") or "（没有记录原因）")
                               + "。已调用模型的 token 不会退回；解析与看图缓存保留，下次同一篇不再重复上传。") if not ok else "")
        self.top_bar.set_target(r)
        self.refresh_list()
        self.target = r
        if ok:
            self._render_target()
        self.drawer.tabs.set_current("note")
        self.drawer.stack.setCurrentIndex(0)

    def refresh_list(self, data_dir=None):
        d = data_dir or (self.cfg.data_dir if self.cfg else None)
        rows = runner.recent_receipts(d, limit=500) if d else []
        excl = runner.paper_key(self.r) if self.r else None
        self.list.set(runner.dedup_papers(rows, exclude=excl))
        self.list.select(None, emit=False)
        self.list_empty.setVisible(not self.list.count())
        self.list.setVisible(bool(self.list.count()))
        self.list_card.setVisible(bool(self.list.count()) or self.r is not None)
        self.list_bar.set_target(None)
        if self.r is None:
            self.empty_card.setVisible(not self.list.count())

    def _on_select(self, r):
        self.list_bar.set_target(r)
        if r is not None and self.drawer_open():
            self.open_drawer(r, self.drawer.tabs.current())

    # ---------- drawer ----------
    def open_drawer(self, r: dict | None, seg: str = "note"):
        if not r:
            return
        r = full_receipt(r)
        if seg == "note" and not (is_ok(r) and r.get("note")):
            seg = "evidence"
        self.target = r
        d = row_of(r)
        self.drawer.title.set_text(d.get("title") or "")
        self.drawer.meta.set_text(d.get("meta") or "")
        self.drawer.actions.set_target(r)
        self.drawer.full_link.setEnabled(is_ok(r) and bool(r.get("note")))
        self.drawer.tabs.buttons["note"].setEnabled(is_ok(r) and bool(r.get("note")))
        self._render_target()
        self.drawer.tabs.set_current(seg)
        self._tab(seg)
        self._place()
        self.scrim.show()
        self.scrim.raise_()
        self.drawer.show()
        self.drawer.raise_()
        self.setFocus()

    def close_drawer(self):
        self.drawer.hide()
        self.scrim.hide()

    def drawer_open(self) -> bool:
        return not self.drawer.isHidden()

    def _tab(self, k):
        self.drawer.heading.setText(dict((a, b) for a, b, _ in SEGS)[k])
        self.drawer.stack.setCurrentIndex({"note": 0, "evidence": 1, "usage": 2}[k])

    # ---------- keyboard ----------
    def _key_move(self, d):
        self.list.move(d)

    def _enter(self):
        r = self.list.current() or self.r
        if r:
            self.open_drawer(r, "note")

    def _cmd_o(self):
        if self.drawer_open():
            self._open_obsidian_target()
        elif self.list.current():
            self._obsidian(self.list.current())
        else:
            self._open_obsidian()

    # ---------- render ----------
    def _render_target(self):
        r = self.target
        if not r:
            return
        self._render_note(r)
        self._render_evidence(r)
        self._render_usage(r)

    def _render_note(self, r):
        self._md = ""
        if not r.get("note"):
            self.drawer.preview.setHtml("")
            return
        note = r["note"]
        try:
            md = Path(note).read_text("utf-8")
        except OSError as e:
            self.drawer.preview.setPlainText(f"（读不到笔记文件：{e}）")
            return
        self._md = md
        head = note_html.preview_head(md)
        find = note_html.image_resolver(note, self.cfg)
        widths = {}

        def image(name):
            u = find(name)
            if u:
                sz = QImageReader(QUrl(u).toLocalFile()).size()
                widths[u] = min(540, sz.width()) if sz.isValid() and sz.width() > 0 else 480
            return u
        note_html.render(head, theme.palette(), dark=theme.is_dark(), image=image)
        self.drawer.preview.setHtml(note_html.render(head, theme.palette(), dark=theme.is_dark(), image=image, widths=widths))

    def _render_evidence(self, r):
        ev_l = self.drawer.ev
        clear(ev_l)
        el = (r.get("extraction") or {}).get("level") if isinstance(r.get("extraction"), dict) else r.get("e_level")
        tags = note_html.tag_counts(getattr(self, "_md", "") or "")
        chips = [pill(f"抽取完整度 {el or '?'}", "stop" if el in ("E0", "E1") else "acc")]
        topic = (r.get("topic") or {}).get("folder") if isinstance(r.get("topic"), dict) else r.get("topic")
        if topic:
            chips.append(pill(f"主题文件夹：{topic}", "gray"))
        chips += [pill(f"PAPER {tags['PAPER']}", "ok"), pill(f"INFERENCE {tags['INFERENCE']}", "info"),
                  pill(f"UNKNOWN {tags['UNKNOWN']}", "trial")]
        ev_l.addLayout(hrow(*chips, None, spacing=8))
        if not is_ok(r):
            ev_l.addWidget(label("停止原因：" + (r.get("reason") or "（没有记录原因）")))
        stats = r.get("stats") or {}
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        shown = [(k, zh) for k, zh in STAT_ZH if k in stats]
        for i, (k, zh) in enumerate(shown):
            tile, tl = card("inset", margins=(12, 8, 12, 8), spacing=2, shadow=False)
            tl.addWidget(label(f"{stats[k]}", "h2", wrap=False))
            tl.addWidget(label(zh, "sub"))
            g.addWidget(tile, i // 3, i % 3)
        if shown:
            ev_l.addLayout(g)
        wj = r.get("wording_judge") or {}
        if wj.get("status"):
            ev_l.addWidget(label(f"措辞核对：{wj['status']}（候选 {wj.get('candidates', 0)} 条）", "sub"))
        ev = r.get("evidence")
        if ev:
            ev_l.addWidget(label("证据档案", "th", wrap=False))
            ev_l.addWidget(path_label(ev))
            ev_l.addLayout(hrow(button("打开证据档案", None, lambda: self.opener(QUrl.fromLocalFile(ev)), icon="shield-check"),
                                None))
        ev_l.addStretch(1)

    def _render_usage(self, r):
        u = self.drawer.usage
        clear(u)
        act, est = r.get("actual") or {}, (r.get("estimate") or {}).get("roles") or {}
        u.addWidget(label("实际用量（与运行前估算对比）", "strong", wrap=False))
        if not act:
            u.addWidget(label("这次没有记录到模型用量。", "muted"))
            u.addStretch(1)
            return
        rows, tot, priced = [], 0.0, True
        for role, a in act.items():
            e = est.get(role) or {}
            rows.append([label(ROLES.get(role, role), "strong", wrap=False), ", ".join(a.get("models") or []),
                         f"{a.get('in', 0):,} / {a.get('out', 0):,}", f"{e['in']:,} / {e['out']:,}" if e else "—",
                         f"¥{a['cost']:.3f}" if a.get("priced") else "未填单价"])
            priced &= bool(a.get("priced"))
            tot += a.get("cost") or 0
        u.addWidget(table(["角色", "模型", "实际 输入/输出", "估算 输入/输出", "费用"], rows, stretch=1))
        u.addWidget(label(f"合计：¥{tot:.3f}" if priced else "合计：部分模型未填单价", "sub"))
        u.addWidget(label("实际 token 来自模型返回的 usage；每次成功运行都会记一笔本机实测，满 3 篇后估算按本机校准。", "sub"))
        u.addStretch(1)

    # ---------- buttons / links ----------
    def _obsidian(self, r):
        if r and r.get("note"):
            self.opener(QUrl(note_html.obsidian_uri(r["note"], self.cfg)))

    def _zotero(self, r):
        k = note_html.item_key_of(r or {})
        if k:
            self.opener(QUrl(note_html.zotero_uri(k)))

    def _reveal_of(self, r):
        if r and r.get("note"):
            reveal(r["note"], None if self.opener is QDesktopServices.openUrl else self.opener)

    def _open_obsidian(self):
        self._obsidian(self.r)

    def _open_zotero(self):
        self._zotero(self.r)

    def _reveal(self):
        self._reveal_of(self.r)

    def _open_obsidian_target(self):
        self._obsidian(self.target)

    def _link(self, url: QUrl):
        if url.scheme() in ("zotero", "http", "https", "obsidian"):
            self.opener(url)
