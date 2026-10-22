"""新建模板 / 新建项目 dialogs (G6-5). Thin UI over gui/library.py create_template / create_project:
templates are registered in the app-data registry only (source "user"; built-ins and the vault 模板库 folder are never
written; a copy of the frozen main template gets a new id), projects go through the project registry (versioned)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QVBoxLayout)

from ..errors import LitError
from . import library as L
from .widgets import button, hrow, label

ROLES = [("MAIN_NOTE", "主模板"), ("MODULE", "专业模块")]


class _Base(QDialog):
    def __init__(self, title: str, sub: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("Page")
        self.setMinimumWidth(600)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(26, 22, 26, 20)
        self.v.setSpacing(12)
        self.v.addWidget(label(title, "h2", wrap=False))
        self.v.addWidget(label(sub, "sub"))
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.v.addLayout(self.form)
        self.err = label("", "warn")
        self.err.setVisible(False)
        self.result: dict | None = None

    def _footer(self, ok_text: str):
        self.v.addWidget(self.err)
        self.ok = button(ok_text, "primary", self._save, icon="check")
        self.v.addLayout(hrow(None, button("取消", None, self.reject), self.ok, spacing=8))

    def _fail(self, msg: str):
        self.err.setText(f"❌ {msg}")
        self.err.setVisible(True)


class NewTemplateDialog(_Base):
    def __init__(self, cfg, parent=None, *, edit_of: dict | None = None):
        """edit_of = a template row (source "user") → 「修改模板」: prefilled from it; saving creates the edited
        template and disables the old one (soft, see library.replace_template)."""
        self.edit_of = edit_of
        super().__init__("修改模板" if edit_of else "新建模板",
                         "保存后生成修改后的模板，旧模板自动停用（登记历史保留，可恢复）。" if edit_of else
                         "复制现有模板的结构，或从空白开始。只登记在应用数据目录；内置模板（含冻结的主模板）"
                         "不会被修改，复制出来的是一个新模板。", parent)
        self.cfg = cfg
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：我的步态研究模板")
        self.form.addRow("模板名称", self.name)
        self.role = QComboBox()
        for k, zh in ROLES:
            self.role.addItem(zh, k)
        self.form.addRow("类型", self.role)
        self.base = QComboBox()
        self.form.addRow("基于", self.base)
        self.v.addWidget(label("章节大纲（双击改名，拖动调整顺序）", "h3"))
        self.secs = QListWidget()
        self.secs.setMinimumHeight(240)
        self.secs.setMaximumHeight(240)
        self.secs.setSpacing(0)
        from . import theme

        def _style(*_):
            self.secs.setStyleSheet(
                f"QListWidget {{ background: {theme.c('field')}; border: 1px solid {theme.c('line')}; border-radius: 10px;"
                f" padding: 4px; }} QListWidget::item {{ background: transparent; border: none; margin: 0; padding: 4px 8px; min-height: 22px; border-radius: 6px; }}"
                f" QListWidget::item:selected {{ background: {theme.c('accent_soft')}; color: {theme.c('accent')}; }}")
        _style()
        theme.on_theme(self.secs, _style)
        self.v.addWidget(self.secs)
        self.v.addSpacing(10)
        self.v.addLayout(hrow(button("添加章节", "small", self._add, icon="plus"),
                              button("删除所选", "small", self._del, icon="x"),
                              button("上移", "small", lambda: self._move(-1)), button("下移", "small", lambda: self._move(1)),
                              None, spacing=6))
        self.v.addWidget(label("保存后按模板检查规则决定状态：启用，或待审（待审的模板不会被自动选用）。", "sub"))
        self._footer("保存修改" if edit_of else "创建模板")
        self.role.currentIndexChanged.connect(self._fill_bases)
        self.base.currentIndexChanged.connect(self._fill_outline)
        if edit_of:
            self.name.setText(edit_of["title"])
            self.role.setCurrentIndex(max(0, [k for k, _ in ROLES].index(edit_of["role"]) if edit_of["role"] in dict(ROLES) else 0))
            self.role.setEnabled(False)
        self._fill_bases()
        if edit_of:
            i = self.base.findData(edit_of["id"])
            if i >= 0:
                self.base.setCurrentIndex(i)
            self.base.setEnabled(False)

    def _fill_bases(self):
        role = self.role.currentData()
        self.base.blockSignals(True)
        self.base.clear()
        for r in L.template_bases(self.cfg):
            if r["role"] == role:
                self.base.addItem(f"复制：{r['title']}", r["id"])
        self.base.addItem("空白模板", None)
        self.base.blockSignals(False)
        self._fill_outline()

    def _fill_outline(self):
        self.secs.clear()
        for t in L.base_outline(self.cfg, self.base.currentData(), self.role.currentData()):
            it = self._item(t)
            if t.rstrip().endswith("、"):
                it.setToolTip("这一章的小标题由模型按论文补充")

    def _item(self, t: str):
        it = QListWidgetItem(t)
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        self.secs.addItem(it)
        return it

    def _add(self):
        it = self._item("新章节")
        self.secs.setCurrentItem(it)
        self.secs.editItem(it)

    def _del(self):
        r = self.secs.currentRow()
        if r >= 0:
            self.secs.takeItem(r)

    def _move(self, d: int):
        r = self.secs.currentRow()
        if 0 <= r + d < self.secs.count() and r >= 0:
            it = self.secs.takeItem(r)
            self.secs.insertItem(r + d, it)
            self.secs.setCurrentRow(r + d)

    def sections(self) -> list[str]:
        return [self.secs.item(i).text().strip() for i in range(self.secs.count()) if self.secs.item(i).text().strip()]

    def _save(self):
        if not self.name.text().strip():
            return self._fail("请填写模板名称")
        if not self.sections():
            return self._fail("至少需要一个章节")
        try:
            if self.edit_of:
                ok, why = L.can_edit_template(self.cfg, self.edit_of["id"])
                if not ok:
                    raise ValueError(why)
            self.result = L.create_template(self.cfg, title=self.name.text(), role=self.role.currentData(),
                                            base_id=self.base.currentData(), sections=self.sections())
            if self.edit_of:
                L.replace_template(self.cfg, self.edit_of["id"], self.result)
        except (LitError, ValueError) as e:
            return self._fail(str(e))
        self.accept()


class NewProjectDialog(_Base):
    def __init__(self, cfg, parent=None):
        super().__init__("新建项目", "新建一份课题档案（带版本记录）。下面的关键信息可以先空着，以后在终端用 "
                                     "litreader project set 补充。", parent)
        self.cfg = cfg
        self.name = QLineEdit()
        self.name.setPlaceholderText("课题题目（2–120 字）")
        self.form.addRow("课题题目", self.name)
        self.fields: dict[str, QPlainTextEdit | QLineEdit] = {}
        for k, zh in L.PROJECT_FIELDS:
            e = QLineEdit()
            e.setPlaceholderText("可选")
            self.fields[k] = e
            self.form.addRow(zh, e)
        self.default = QCheckBox("设为默认课题")
        self.form.addRow("", self.default)
        self._footer("创建项目")

    def _save(self):
        try:
            self.result = L.create_project(self.cfg, self.name.text(), {k: e.text() for k, e in self.fields.items()},
                                           self.default.isChecked() or None)
        except (LitError, ValueError) as e:
            return self._fail(str(e))
        self.accept()
