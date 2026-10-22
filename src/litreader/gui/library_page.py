"""模板库 & 项目库. Two tabs reusing `templates list/show` and `project list/show` data (gui/library.py), plus
新建模板 / 新建项目 dialogs (G6-5, gui/library_dialogs.py). G7: right-click 修改/重命名/复制/删除 (soft, versioned)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QTabWidget, QVBoxLayout,
                               QWidget)

from ..errors import LitError
from . import library as L
from PySide6.QtWidgets import QDialog, QLineEdit, QPlainTextEdit, QStackedWidget

from .widgets import Clickable, button, card, clear, empty_state, hrow, label, page, path_label, pill, sep

STATE_PILL = {"CONFIRMED": "ok", "PENDING": "trial", "UNDECIDED": "gray", "SUGGESTION": "info"}
STATUS_PILL = {"启用": "ok", "待审": "trial", "ID 冲突": "stop"}


def soft_wrap(s: str) -> str:
    """Let long ID-like text (paths, ids, hashes) wrap: zero-width spaces after / _ - . : @ and every 24 chars."""
    import re
    s = re.sub(r"([/_\-.:@])", "\\1\u200b", str(s))
    return re.sub(r"([^\s\u200b]{24})(?=[^\s\u200b])", "\\1\u200b", s)


def section_head(num: str | None, title: str, sub: str | None = None) -> QHBoxLayout:
    """G7-6 section header: small accent number chip + 15px semibold title + optional grey count."""
    parts = []
    if num:
        chip = label(num, "chip_num", wrap=False)
        parts.append(chip)
    parts.append(label(title, "sec", wrap=False))
    if sub:
        parts.append(label(sub, "sub", wrap=False))
    return hrow(*parts, None, spacing=8)


def _kv(rows: list[tuple[str, str]], path_keys=()) -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(16)
    g.setVerticalSpacing(8)
    for i, (k, v) in enumerate(rows):
        g.addWidget(label(k, "fieldk", wrap=False), i, 0, Qt.AlignTop)
        val = path_label(soft_wrap(v)) if k in path_keys else label(soft_wrap(v), "fieldv", selectable=True)
        val.setWordWrap(True)
        g.addWidget(val, i, 1)
    g.setColumnMinimumWidth(0, 84)
    g.setColumnStretch(1, 1)
    return g


class FieldRow(QWidget):
    """G7-8 project item: label · value (click to edit inline → 保存 = 已确认) · state pill · 确认 / 忽略 for 待确认."""

    def __init__(self, tab, pid: str, it: dict):
        super().__init__()
        self.tab, self.pid, self.it = tab, pid, it
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 3, 0, 3)
        h.setSpacing(12)
        k = label(it["label"], "fieldk", wrap=False)
        k.setFixedWidth(104)
        h.addWidget(k, 0, Qt.AlignTop)
        self.stack = QStackedWidget()
        self.view = Clickable()
        self.view.setProperty("role", "field_click")
        vl = QHBoxLayout(self.view)
        vl.setContentsMargins(6, 2, 6, 2)
        self.val = label(soft_wrap(it["value"]) if it["value"] else "点击填写", "fieldv" if it["value"] else "muted")
        self.val.setWordWrap(True)
        vl.addWidget(self.val, 1)
        self.view.setToolTip((("来源：" + it["source"] + "\n") if it["source"] else "") + "单击修改；保存后标为「已确认」")
        self.view.clicked.connect(self.start_edit)
        self.stack.addWidget(self.view)
        ed = QWidget()
        el = QHBoxLayout(ed)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        self.edit = QLineEdit(it["value"])
        self.edit.setMinimumWidth(80)
        self.edit.returnPressed.connect(self.save)
        el.addWidget(self.edit, 1)
        el.addWidget(button("保存", "small", self.save))
        el.addWidget(button("取消", "small", lambda: self.stack.setCurrentIndex(0)))
        self.stack.addWidget(ed)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(self.stack)
        if it["state"] == "PENDING":
            col.addLayout(hrow(button("确认", "small", lambda: self.tab.decide(self.it, True), "标为已确认"),
                               button("忽略", "small", lambda: self.tab.decide(self.it, False), "删除这条建议"),
                               None, spacing=6))
        h.addLayout(col, 1)
        h.addWidget(pill(it["state_zh"] if it["state"] != "PENDING" else "待确认", STATE_PILL.get(it["state"], "gray")),
                    0, Qt.AlignTop)

    def start_edit(self):
        self.stack.setCurrentIndex(1)
        self.edit.setFocus()
        self.edit.selectAll()

    def save(self):
        self.tab.set_field(self.it["key"], self.edit.text())


class BulkFillDialog(QDialog):
    """批量填写: paste text; the model splits it into fields as 待确认 suggestions (nothing is confirmed here)."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setWindowTitle("批量填写")
        self.setObjectName("Page")
        self.setMinimumWidth(620)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 20)
        v.setSpacing(10)
        v.addWidget(label("批量填写", "h2", wrap=False))
        v.addWidget(label("粘贴开题报告、导师意见或任何描述课题的文字。模型会把它拆成各个字段，全部作为「建议·待确认」"
                          "保存；你逐条点「确认」后才会成为已确认。文字只发给主笔模型，不上传其他地方。", "sub"))
        self.text = QPlainTextEdit()
        self.text.setMinimumHeight(220)
        self.text.setPlaceholderText("在这里粘贴文字…")
        v.addWidget(self.text)
        self.msg = label("", "warn")
        self.msg.setVisible(False)
        v.addWidget(self.msg)
        self.ok = button("拆分为建议", "primary", self.run, icon="sparkles")
        self.ok.setEnabled(False)
        self.text.textChanged.connect(lambda: self.ok.setEnabled(bool(self.text.toPlainText().strip())))
        v.addLayout(hrow(None, button("取消", None, self.reject), self.ok, spacing=8))
        self.result = None

    def run(self):
        try:
            self.result = self.tab.bulk(self.text.toPlainText())
        except (LitError, ValueError) as e:
            self.msg.setText(f"❌ {e}")
            self.msg.setVisible(True)
            return
        self.accept()


def _master_detail() -> tuple[QWidget, QListWidget, QVBoxLayout]:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(18)
    lst = QListWidget()
    lst.setMinimumWidth(290)
    lst.setMaximumWidth(330)
    lst.setMinimumHeight(430)
    lst.setWordWrap(True)
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lst.setVerticalScrollMode(QListWidget.ScrollPerPixel)
    h.addWidget(lst, 0, Qt.AlignTop)
    detail, dl = card("slot", margins=(22, 18, 22, 18), spacing=10, shadow=False)
    h.addWidget(detail, 1, Qt.AlignTop)
    return w, lst, dl


class TemplatesTab(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 14, 2, 6)
        c, self.cl = card(margins=(22, 20, 22, 20), spacing=12)
        v.addWidget(c)
        v.addStretch(1)     # tabs share the tallest page's height; keep this card compact at the top
        self.refresh_btn = button("刷新模板库", "small", self.refresh, "登记新放入或改过的模板（= litreader templates refresh，"
                                                                "模板库文件夹只读，登记在应用数据目录）", icon="refresh-cw")
        self.new_btn = button("新建模板", "primary", self.new_template, icon="plus")
        self.cl.addLayout(hrow(label("模板库", "h2", wrap=False), None, self.refresh_btn, self.new_btn, spacing=8))
        self.info = label("", "sub")
        self.cl.addWidget(self.info)
        self.status = label("", "sub")
        self.status.setVisible(False)
        self.cl.addWidget(self.status)
        md, self.list, self.dl = _master_detail()
        self.cl.addWidget(md)
        self.list.currentRowChanged.connect(self._show)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.rows: list[dict] = []
        self.load()

    # ---------- G7-5: right-click menu ----------
    def _say(self, msg: str):
        self.status.setText(msg)
        self.status.setVisible(True)

    def menu_actions(self, i: int) -> list[tuple[str, bool, str]]:
        """[(text, enabled, tooltip)] for row i — built-in / library templates: only 复制为新模板."""
        ok, why = L.can_edit_template(self.cfg, self.rows[i]["id"])
        return [("修改…", ok, why), ("重命名…", ok, why), ("复制为新模板", True, ""), ("删除…", ok, why)]

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        i = self.list.row(it)
        self.list.setCurrentRow(i)
        m = QMenu(self)
        m.setToolTipsVisible(True)
        for text, en, tip in self.menu_actions(i):
            a = m.addAction(text)
            a.setEnabled(en)
            a.setToolTip(tip or text)
            a.triggered.connect(lambda _=False, t=text, i=i: self.do(t, i))
        m.exec(self.list.mapToGlobal(pos))

    def do(self, action: str, i: int, *, value: str | None = None, confirm=None):
        """Run one menu action. value/confirm are injectable for tests (no modal dialogs)."""
        r = self.rows[i]
        try:
            if action == "复制为新模板":
                res = L.copy_template(self.cfg, r["id"])
                self._say(f"✅ 已复制为新模板 {res['id']}（{res['status_zh']}）")
                return self.load(select=res["id"])
            if action == "重命名…":
                if value is None:
                    value, ok = QInputDialog.getText(self, "重命名模板", "新名称：", text=r["title"])
                    if not ok:
                        return
                res = L.rename_template(self.cfg, r["id"], value)
                self._say(f"✅ 已重命名为「{value.strip()}」（新 id {res['id']}；旧模板已停用，可恢复）")
                return self.load(select=res["id"])
            if action == "删除…":
                ok = confirm if confirm is not None else QMessageBox.question(
                    self, "删除模板", f"删除模板「{r['title']}」？\n\n这是软删除：模板会被停用并从列表隐藏，"
                    "登记历史全部保留，可以用 litreader templates enable 恢复。") == QMessageBox.Yes
                if not ok:
                    return
                L.delete_template(self.cfg, r["id"])
                self._say(f"✅ 已删除（停用）「{r['title']}」，可恢复")
                return self.load()
            if action == "修改…":
                from .library_dialogs import NewTemplateDialog
                d = NewTemplateDialog(self.cfg, self, edit_of=r)
                if d.exec() and d.result:
                    self._say(f"✅ 已保存修改：新 id {d.result['id']}（旧模板已停用，可恢复）")
                    self.load(select=d.result["id"])
        except (LitError, ValueError, KeyError) as e:
            self._say(f"❌ {e}")

    def load(self, select: str | None = None):
        data = L.template_rows(self.cfg)
        self.rows = data["rows"]
        lib = data["library"] or "（未设置模板库文件夹：只有内置模板）"
        self.info.setText(f"登记快照 #{data['snapshot']} · 模板库文件夹："
                          f"{lib}{'' if data['library_exists'] or not data['library'] else '（不存在）'}")
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.rows:
            mark = "★ 默认 · " if r["default"] else ""
            warn = f" · ⚠ {r['warnings']}" if r["warnings"] else ""
            it = QListWidgetItem(f"{r['title']}\n{mark}{r['role_zh']} · {r['status_zh']} · {r['source_zh']}{warn}")
            it.setToolTip(f"{r['id']} v{r['version']}")
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self.rows:
            ids = [r["id"] for r in self.rows]
            self.list.setCurrentRow(ids.index(select) if select in ids else 0)
            self._show(self.list.currentRow())

    def _show(self, i: int):
        clear(self.dl)
        if not 0 <= i < len(self.rows):
            return
        r = self.rows[i]
        d = L.template_detail(self.cfg, r["id"], r["version"])
        self.dl.addWidget(label(d["title"], "title_lg"))
        pills = [pill(d["role_zh"], "acc"), pill(d["status_zh"], STATUS_PILL.get(d["status_zh"], "gray")),
                 pill(d["source_zh"], "gray")]
        if r["default"]:
            pills.insert(0, pill("★ 默认主模板" if r["default_explicit"] else "★ 默认主模板（内置）", "info"))
        pills += [pill(f, "info") for f in r["flags"]]
        self.dl.addLayout(hrow(*pills, None, spacing=6))
        self.dl.addLayout(_kv([("ID", f"{d['id']}  v{d['version']}"), ("适用类型", "、".join(d["study_types"])),
                               ("精读层级", "、".join(d["levels"]) or "—"), ("能力", "、".join(d["features"]) or "—"),
                               ("文件", d["path"])], path_keys=("文件",)))
        if d["compatible_with"]:
            self.dl.addWidget(label("可搭配主模板：" + "、".join(d["compatible_with"]), "sub"))
        self.dl.addSpacing(4)
        self.dl.addWidget(sep())
        self.dl.addLayout(section_head(None, "章节预览", f"{len(d['sections'])} 节"))
        for s in d["sections"]:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.setContentsMargins(12 * max(0, s["level"] - 2), 1, 0, 1)
            t = label(s["title"], "fieldv_b" if s["level"] <= 2 else "fieldv")
            t.setWordWrap(True)
            row.addWidget(t, 1)
            for b in s["blocks"][:4]:
                row.addWidget(label(b, "tagchip", wrap=False), 0, Qt.AlignRight | Qt.AlignTop)
            self.dl.addLayout(row)
        if d["fields"]:
            self.dl.addWidget(label("新增字段：" + "；".join(d["fields"]), "sub"))
        for lab, x in d["issues"]:
            self.dl.addWidget(label(f"{lab}：{x}", "warn" if lab != "提示" else "info"))
        self.dl.addWidget(sep())
        self.dl.addLayout(section_head(None, "版本历史", None))
        self.dl.addWidget(label("；".join(d["history"]), "sub"))

    def new_template(self):
        from .library_dialogs import NewTemplateDialog
        d = NewTemplateDialog(self.cfg, self)
        if d.exec() and d.result:
            r = d.result
            self.status.setText(f"✅ 已新建模板 {r['id']} v{r['version']}（{r['status_zh']}）")
            self.status.setVisible(True)
            self.load(select=r["id"])

    def refresh(self):
        cur = self.rows[self.list.currentRow()]["id"] if self.rows and self.list.currentRow() >= 0 else None
        try:
            res = L.refresh_templates(self.cfg)
        except LitError as e:
            self.status.setText(f"❌ 刷新失败：{e}")
            self.status.setVisible(True)
            return
        msg = f"✅ 已刷新：登记快照 #{res['snapshot']}" + ("（无变化）" if not res["changes"] else "：" + "；".join(res["changes"]))
        if res["notes"]:
            msg += "　提示：" + "；".join(res["notes"])
        self.status.setText(msg)
        self.status.setVisible(True)
        self.load(select=cur)


class ProjectsTab(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(2, 14, 2, 6)
        self.load()

    def new_project(self):
        from .library_dialogs import NewProjectDialog
        d = NewProjectDialog(self.cfg, self)
        if d.exec() and d.result:
            self.load(select=d.result["id"], note=f"✅ 已新建课题「{d.result['title']}」v{d.result['version']}")

    def load(self, select: str | None = None, note: str | None = None):
        clear(self.v)
        v = self.v
        cfg = self.cfg
        data = L.project_rows(cfg)
        self.rows = data["rows"]
        if not self.rows:
            v.addWidget(empty_state("folder-tree", "还没有课题档案",
                                    "在主页输入「新建课题：〈题目〉」，或在终端运行 litreader project init。"
                                    "课题档案会让笔记多一节“与我的课题的关系”。", action="新建项目", slot=self.new_project,
                                    extra=[f"可读档案：{data['views']}"]))
            v.addStretch(1)
            return
        c, cl = card(margins=(22, 20, 22, 20), spacing=12)
        v.addWidget(c)
        v.addStretch(1)
        cl.addLayout(hrow(label("项目库", "h2", wrap=False), None,
                          label("★ = 默认课题；右键可重命名/复制/删除", "sub"),
                          button("新建项目", "primary", self.new_project, icon="plus"), spacing=8))
        self.status = label(note or "", "sub")
        self.status.setVisible(bool(note))
        cl.addWidget(self.status)
        cl.addWidget(label(f"登记快照 #{data['snapshot']} · 可读档案：{data['views']}", "sub"))
        md, self.list, self.dl = _master_detail()
        cl.addWidget(md)
        for r in self.rows:
            n = r["counts"]
            it = QListWidgetItem(f"{'★ ' if r['default'] else ''}{r['title']}\n"
                                 f"v{r['version']} · {'已归档' if r['archived'] else '进行中'} · 已确认 {n['CONFIRMED']} · "
                                 f"待确认 {n['PENDING']} · 未定 {n['UNDECIDED']}")
            it.setToolTip(f"{r['id']} · {r['folder']}")
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._show)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        ids = [r["id"] for r in self.rows]
        self.list.setCurrentRow(ids.index(select) if select in ids else next((i for i, r in enumerate(self.rows) if r["default"]), 0))
        self._show(self.list.currentRow())

    def menu_actions(self, i: int):
        return _project_menu_actions(self.rows[i])

    def do(self, action: str, i: int, *, value=None, confirm=None):
        return _project_do(self, action, i, value, confirm)

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        i = self.list.row(it)
        m = QMenu(self)
        m.setToolTipsVisible(True)
        for text, en, tip in self.menu_actions(i):
            a = m.addAction(text)
            a.setEnabled(en)
            a.setToolTip(tip or text)
            a.triggered.connect(lambda _=False, t=text, i=i: self.do(t, i))
        m.exec(self.list.mapToGlobal(pos))

    def _show(self, i: int):
        clear(self.dl)
        if not 0 <= i < len(self.rows):
            return
        r = self.rows[i]
        d = L.project_detail(self.cfg, r["id"])
        n = d["counts"]
        self.dl.addWidget(label(d["title"], "title_lg"))
        pills = [pill("★ 默认课题", "info")] if r["default"] else []
        pills += [pill("已归档" if d["archived"] else "进行中", "gray" if d["archived"] else "acc"),
                  pill(f"已确认 {n['CONFIRMED']}", "ok"), pill(f"待确认 {n['PENDING']}", "trial"),
                  pill(f"未定 {n['UNDECIDED']}", "gray"), pill(f"建议 {n['SUGGESTION']}", "info")]
        self.dl.addLayout(hrow(*pills, None, spacing=6))
        self.dl.addLayout(_kv([("ID", f"{d['id']}  v{d['version']}"), ("文件夹", r["folder"])]))
        self.dl.addLayout(hrow(label("单击任一字段即可修改（保存后为「已确认」）", "sub", wrap=False), None,
                               button("批量填写…", None, self.open_bulk, "粘贴文字，由模型拆成各字段的建议（待确认）",
                                      icon="sparkles"), spacing=8))
        self._pid = r["id"]
        for m in d["modules"]:
            self.dl.addSpacing(6)
            self.dl.addWidget(sep())
            filled = sum(1 for it in m["items"] if it["value"])
            self.dl.addLayout(section_head(m["id"], m["name"], f"{filled}/{len(m['items'])} 已填"))
            for it in m["items"]:
                self.dl.addWidget(FieldRow(self, r["id"], it))
        self.dl.addWidget(sep())
        self.dl.addLayout(section_head(None, "版本历史", f"共 {len(d['history'])} 版"))
        for h in d["history"][-8:]:
            self.dl.addWidget(label(f"v{h['version']}  {h['created']}  {h['op']}  {h['summary']}", "sub"))

    # ---------- G7-8 actions ----------
    def _cur_index(self):
        return [x["id"] for x in self.rows].index(self._pid)

    def set_field(self, key: str, text: str):
        try:
            res = L.set_project_field(self.cfg, self._pid, key, text)
            self.load(select=self._pid, note=f"✅ 已保存（v{res['version']}，已确认）")
        except (LitError, ValueError) as e:
            self.load(select=self._pid, note=f"❌ {e}")

    def decide(self, it: dict, accept: bool):
        try:
            res = L.decide_project_value(self.cfg, self._pid, it["key"], it["idx"], accept)
            self.load(select=self._pid, note=f"✅ {'已确认' if accept else '已忽略'}「{it['label']}」（v{res['version']}）")
        except (LitError, ValueError) as e:
            self.load(select=self._pid, note=f"❌ {e}")

    def llm(self):
        """(chain, transport, env) for 批量填写; tests replace this with fakes."""
        from ..llm.client import urllib_transport
        from ..secrets import SecretEnv
        return self.cfg.llm.chain("extract"), urllib_transport, SecretEnv()

    def bulk(self, text: str) -> dict:
        if self.cfg.llm is None:
            raise ValueError("模型未设置：先在「模型设置」里设置主笔")
        chain, tx, env = self.llm()
        res = L.bulk_fill(self.cfg, self._pid, text, chain=chain, transport=tx, env=env)
        self.load(select=self._pid, note=f"✅ 批量填写：新增 {res['added']} 条建议（待确认），请逐条确认")
        return res

    def open_bulk(self):
        BulkFillDialog(self).exec()


def _project_menu_actions(row: dict) -> list[tuple[str, bool, str]]:
    if row["archived"]:
        return [("恢复（取消归档）", True, ""), ("复制", True, "")]
    return [("修改…", True, "在右侧详情里点任一字段即可修改"), ("重命名…", True, ""), ("复制", True, ""),
            ("删除…", True, "软删除 = 归档：所有版本与档案文件保留，可恢复")]


def _project_do(tab, action: str, i: int, value=None, confirm=None):
    r = tab.rows[i]
    try:
        if action == "复制":
            res = L.copy_project(tab.cfg, r["id"])
            return tab.load(select=res["id"], note=f"✅ 已复制为「{res['title']}」")
        if action == "重命名…":
            if value is None:
                value, ok = QInputDialog.getText(tab, "重命名课题", "新题目：", text=r["title"])
                if not ok:
                    return
            res = L.rename_project(tab.cfg, r["id"], value)
            return tab.load(select=r["id"], note=f"✅ 已重命名（v{res['version']}）")
        if action == "删除…":
            ok = confirm if confirm is not None else QMessageBox.question(
                tab, "删除课题", f"删除课题「{r['title']}」？\n\n这是软删除：课题会被归档（不再作为默认或本次课题），"
                "所有版本和档案文件都保留，可以右键「恢复」。") == QMessageBox.Yes
            if not ok:
                return
            L.delete_project(tab.cfg, r["id"])
            return tab.load(select=r["id"], note=f"✅ 已删除（归档）「{r['title']}」，可恢复")
        if action == "恢复（取消归档）":
            L.restore_project(tab.cfg, r["id"])
            return tab.load(select=r["id"], note=f"✅ 已恢复「{r['title']}」")
        if action == "修改…":
            tab.list.setCurrentRow(i)
    except (LitError, ValueError, KeyError) as e:
        tab.load(select=r["id"], note=f"❌ {e}")


class LibraryPage(QWidget):
    def __init__(self, cfg, cfg_error: str | None = None):
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body, lay = page("模板库 & 项目库")
        outer.addWidget(body)
        lay.addWidget(label("和终端 litreader templates list/show、project list/show 显示的是同一份登记。"
                            "可以在这里新建、修改（右键）和整理模板与项目。", "muted"))
        self.tabs = None
        if cfg is None:
            lay.addWidget(empty_state("circle-alert", "还没有读到配置文件", cfg_error or "请先按《Mac 运行指南》完成安装。"))
            lay.addStretch(1)
            return
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        try:
            self.templates = TemplatesTab(cfg)
            self.tabs.addTab(self.templates, "模板库")
        except Exception as e:  # noqa: BLE001 — a broken registry must not stop the window from opening
            self.tabs.addTab(empty_state("circle-alert", "模板登记读取失败", str(e)), "模板库")
        try:
            self.projects = ProjectsTab(cfg)
            self.tabs.addTab(self.projects, "项目库")
        except Exception as e:  # noqa: BLE001
            self.tabs.addTab(empty_state("circle-alert", "课题登记读取失败", str(e)), "项目库")
        lay.addWidget(self.tabs, 1)
