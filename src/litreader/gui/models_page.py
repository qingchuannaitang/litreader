"""模型设置 (G6, prototype p-models, stacked layout): tabs 主笔 / 看图 / 交叉核对 / 解析器. Each role shows its
slots as stacked cards — 「1 主用 优先使用」 then 备用1…3 — with 厂商 dropdown, 模型名, URL, API Key (masked, 更换),
输入/输出单价, 测试连接 and the calibration dots; dashed 「+ 添加备用N（最多 1 主用 + 3 备用）」. Same models.toml as the
CLI; keys only in the keychain. 解析器 tab: MinerU (in use) and PaddleOCR (备用, not wired into the reading flow yet)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import calibration, secrets
from ..llm import models as M
from ..llm import presets
from ..llm.config import ConfigError
from . import theme
from .widgets import Segmented, button, card, clear, hrow, label, page, pill

ROLE_EN = {"writer": "writer", "vision": "vision", "judge": "judge"}
ROLE_HINT = {"writer": "写笔记正文（最贵、最重要）", "vision": "看图表（需要支持图片输入的模型）",
             "judge": "交叉核对原文、机翻候选题名"}
VISION_OPTIONAL = "可选：留空则跳过看图，笔记只依据图注与正文（更省钱、更快，但没有「主要发现」读图和读图核对）"


def preset_for_slot(s: M.Slot) -> dict:
    return presets.by_url(s.url) or presets.by_vendor(s.vendor) or presets.CUSTOM


class _TestSignal(QObject):
    done = Signal(str, dict)


class CalDots(QWidget):
    """MIN_RUNS little bars, filled for each measured run, + the slot_line text (prototype calibration dots)."""

    def __init__(self, n: int):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        for i in range(calibration.MIN_RUNS):
            d = QFrame()
            d.setFixedSize(16, 5)
            d.setProperty("role", "caldot_on" if i < n else "caldot")
            h.addWidget(d)
        h.addSpacing(6)
        done = n >= calibration.MIN_RUNS
        txt = calibration.slot_line([{}] * n) + ("（估算显示“按本机实测校准”）" if done else "")
        h.addWidget(label(txt, "cal_txt_ok" if done else "sub", wrap=False))
        h.addStretch(1)


class SlotCard(QFrame):
    """One slot (主用 / 备用N) of one role, edited in place."""

    def __init__(self, editor: "RoleEditor", idx: int | None, slot: M.Slot | None):
        super().__init__()
        self.editor, self.owner, self.role = editor, editor.owner, editor.role
        self.idx = idx
        n = idx if idx is not None else len(self.owner.ms.roles[self.role])
        self.setProperty("role", "slotcard_main" if n == 0 else "slotcard")
        fl = QVBoxLayout(self)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.setSpacing(10)
        name = f"{n + 1}. {M.SLOT_NAMES[n]}" + ("（新）" if idx is None else "")
        self.form_title = label(name, "h3", wrap=False)
        badge = pill("优先使用", "acc") if n == 0 else pill("主用失败时按顺序使用", "gray")
        self.del_btn = button("删除", "small", self._delete, icon="x", icon_color="stop")
        self.del_btn.setEnabled(idx is not None)
        self.test_btn = button("测试连接", "small", self._test, "发一次很小的请求（约几十 tokens，会按厂商价格计费）",
                               icon="refresh-cw", icon_color="text")
        fl.addLayout(hrow(self.form_title, badge, None, self.test_btn, self.del_btn, spacing=8))
        self.vendor = QComboBox()
        for p in presets.choices():
            self.vendor.addItem(p["label"], p["id"])
        self.vendor.currentIndexChanged.connect(self._vendor_changed)
        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("例如：某某中转站（只是显示名称）")
        self.url = QLineEdit()
        self.url.setPlaceholderText("OpenAI 兼容 Base URL，例如 https://…/v1")
        self.model = QLineEdit()
        self.model.setPlaceholderText("从厂商文档或控制台复制模型 ID")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.change_key = button("更换", "small", self._unlock_key, "粘贴新的 Key（只存进系统钥匙串）")
        self.key_ref = label("", "sub", wrap=False)
        self.pin = QLineEdit()
        self.pin.setPlaceholderText("可选，自己从厂商价目表抄")
        self.pout = QLineEdit()
        self.pout.setPlaceholderText("可选")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(4)

        def field(r, c, cap, w, span=1):
            lab = label(cap, "th", wrap=False)
            g.addWidget(lab, r * 2, c, 1, span)
            if isinstance(w, QWidget):
                g.addWidget(w, r * 2 + 1, c, 1, span)
            else:
                g.addLayout(w, r * 2 + 1, c, 1, span)
            return lab
        field(0, 0, "厂商", self.vendor)
        field(0, 1, "模型名（从厂商文档复制）", self.model)
        self.custom_label = field(1, 0, "显示名称（自定义 / 中转站）", self.custom_name, span=2)
        field(2, 0, "URL（OpenAI 兼容 Base URL）", self.url)
        self.key_cap = field(2, 1, "API Key（只存进系统钥匙串）", hrow(self.key, self.change_key, spacing=8))
        field(3, 0, "输入单价（元 / 1M tokens，可选）", self.pin)
        field(3, 1, "输出单价（元 / 1M tokens，可选）", self.pout)
        g.addWidget(self.key_ref, 8, 1)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        fl.addLayout(g)
        self.note = label("", "sub")
        fl.addWidget(self.note)
        recs = []
        if self.owner.cal_store and slot is not None:
            recs = self.owner.cal_store.records(calibration.key(slot.vendor, slot.model, self.role))
        if slot is not None:
            fl.addWidget(CalDots(len(recs)))
        self.key_link = button("获取 Key ↗", "link", self._open_key_page)
        self.doc_link = button("接口文档 ↗", "link", self._open_doc)
        self.save_btn = button("保存", "primary", self._save)
        fl.addLayout(hrow(self.key_link, self.doc_link, None, self.save_btn, spacing=14))
        self.status = label("", "sub")
        fl.addWidget(self.status)
        self._sig = _TestSignal()
        self._sig.done.connect(self._test_done)
        self._filling = False
        self._key_ref = None
        if slot is not None:
            self._fill(slot)
        else:
            self._filling = True
            self.vendor.setCurrentIndex(0)
            self._filling = False
            self._vendor_changed()

    def _fill(self, s: M.Slot):
        pre = preset_for_slot(s)
        self._filling = True
        self.vendor.setCurrentIndex(max(0, self.vendor.findData(pre["id"])))
        self._filling = False
        self.custom_name.setText(s.vendor if pre["id"] == "custom" else "")
        self.url.setText(s.url)
        self.model.setText(s.model)
        self._key_ref = s.key_ref
        self.pin.setText("" if s.price_in is None else f"{s.price_in:g}")
        self.pout.setText("" if s.price_out is None else f"{s.price_out:g}")
        self._after_vendor(pre)

    # ----- vendor -----
    def current_preset(self) -> dict:
        return presets.by_id(self.vendor.currentData()) or presets.CUSTOM

    def _vendor_changed(self, *_):
        if self._filling:
            return
        pre = self.current_preset()
        self.url.setText(pre["url"])        # official base URL, editable; custom = user types it
        if self.idx is None or pre["id"] != "custom":
            self._key_ref = pre["key_ref"] or None
        self._after_vendor(pre)

    def _after_vendor(self, pre: dict):
        custom = pre["id"] == "custom"
        self.custom_name.setEnabled(custom)
        self.custom_name.setVisible(custom)
        self.custom_label.setVisible(custom)
        note = pre.get("note") or ("Base URL 已按官方文档预填，可以修改。" if not custom else "")
        if pre.get("unverified_call"):
            note = (note + " " if note else "") + "（URL 来自官方文档，尚未用真实 Key 实测。）"
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.key_link.setVisible(bool(pre.get("key_page")))
        self.doc_link.setVisible(bool(pre.get("doc")))
        self._show_key_ref()

    def _effective_key_ref(self) -> str:
        if self._key_ref:
            return self._key_ref
        vendor = self.custom_name.text().strip() or "CUSTOM"
        return M.default_key_ref(vendor, self.url.text().strip(), self.role,
                                 self.idx if self.idx is not None else len(self.owner.ms.roles[self.role]))

    def _show_key_ref(self):
        ref = self._effective_key_ref()
        st = secrets.status(ref)          # G11-1: never reads the keychain while rendering
        has = st in ("env", "saved", "indexed")
        self.key.clear()
        self.key.setEnabled(not has)
        self.change_key.setVisible(has)
        self.key.setPlaceholderText("•••••••••••• 已保存" if has else
                                    ("粘贴 API Key；留空 = 保留钥匙串里原有的（未读取，用到时再读）" if st == "unknown"
                                     else "粘贴 API Key（只存进系统钥匙串，不写进任何文件）"))
        self.key_ref.setText(f"钥匙串：{ref} · {secrets.STATUS_ZH[st]}")

    def _unlock_key(self):
        self.key.setEnabled(True)
        self.key.setPlaceholderText("粘贴新的 Key；留空 = 保留原来的")
        self.key.setFocus()

    def _open_key_page(self):
        u = self.current_preset().get("key_page")
        if u:
            QDesktopServices.openUrl(QUrl(u))

    def _open_doc(self):
        u = self.current_preset().get("doc")
        if u:
            QDesktopServices.openUrl(QUrl(u))

    # ----- save / delete / test -----
    def build_slot(self) -> M.Slot:
        pre = self.current_preset()
        vendor = self.custom_name.text().strip() if pre["id"] == "custom" else pre["label"]
        if not vendor:
            raise ConfigError("请填写显示名称（自定义 / 中转站）")

        def num(w):
            t = w.text().strip()
            if not t:
                return None
            try:
                return float(t)
            except ValueError:
                raise ConfigError("单价必须是数字（元/1M tokens）")
        old = self.owner.ms.roles[self.role][self.idx] if self.idx is not None else None
        s = M.Slot(vendor=vendor, model=self.model.text().strip(), url=self.url.text().strip(),
                   key_ref=self._effective_key_ref(), price_in=num(self.pin), price_out=num(self.pout),
                   json_mode=old.json_mode if old else None, max_tokens=old.max_tokens if old else None,
                   timeout_s=old.timeout_s if old else None, extra_body=old.extra_body if old else None)
        if old and (old.model, old.url) == (s.model, s.url):   # G12-3: the user's 支持看图 mark follows the same model only
            s.supports_vision = old.supports_vision
        s.validate(f"{M.ROLES[self.role]}")
        return s

    def _save(self):
        try:
            s = self.build_slot()
        except ConfigError as e:
            self.status.setText(f"❌ {e}")
            return
        slots = self.owner.ms.roles[self.role]
        if self.idx is None:
            if len(slots) >= 4:
                self.status.setText("❌ 每个角色最多 1 个主用 + 3 个备用")
                return
            slots.append(s)
            i = len(slots) - 1
        else:
            slots[self.idx] = s
            i = self.idx
        k = self.key.text().strip()
        try:
            self.owner.save()
            if k:
                secrets.set_secret(s.key_ref, k)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"❌ 保存失败：{e}")
            return
        self.key.clear()
        self.status.setText(f"✅ 已保存到 {self.owner.path.name}" + ("；Key 已存入钥匙串" if k else ""))
        self.editor.refresh()
        self.editor.flash(i, self.status.text())

    def _delete(self):
        if self.idx is None:
            return
        s = self.owner.ms.roles[self.role][self.idx]
        if QMessageBox.question(self, "删除模型", f"删除 {M.ROLES[self.role]}·{M.SLOT_NAMES[self.idx]}（{s.vendor} {s.model}）？\n"
                                "钥匙串中的 Key 不会删除。") != QMessageBox.Yes:
            return
        self.owner.ms.roles[self.role].pop(self.idx)
        self.owner.save()
        self.editor.refresh()
        self.editor.flash(None, "✅ 已删除（Key 仍在钥匙串）")

    def _test(self):
        try:
            s = self.build_slot()
        except ConfigError as e:
            self.status.setText(f"❌ {e}")
            return
        tmp = M.ModelSettings()
        tmp.roles[self.role].append(s)
        p = tmp.to_llm_config(require_writer=False).providers[tmp.slot_id(self.role, 0)]
        self.status.setText("… 正在测试（一次很小的请求）")
        self.test_btn.setEnabled(False)
        tx = self.owner.transport
        secrets.forget_denied(p.key_env)   # explicit click = one fresh read of THIS role's key only

        def work():
            try:
                r = M.test_slot(p, self.role, tx, secrets.SecretEnv())
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "category": type(e).__name__, "detail": str(e)}
            self._sig.done.emit(self.role, r)
        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, role, r):
        self.test_btn.setEnabled(True)
        self.status.setText(f"{'✅' if r.get('ok') else '❌'} {r.get('category')}"
                            f"{('：' + r['detail']) if r.get('detail') else ''}"
                            f"{('　提示：' + r['hint']) if r.get('hint') else ''}")



SHARE_LABEL = "与主笔共用（看图直接使用主笔的主用模型和 Key，不用再单独配置）"


class VisionShare(QWidget):
    """G12-3: 「与主笔共用」 on the 看图 tab. Only allowed when the 主笔 主用 slot is marked supports_vision — a mark the
    USER sets after checking the vendor's docs (the program has no list of vision models and does not guess)."""

    def __init__(self, owner: "ModelsPage", editor: "RoleEditor"):
        super().__init__()
        self.owner, self.editor = owner, editor
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.share = QCheckBox(SHARE_LABEL)
        self.share.toggled.connect(self._share_toggled)
        self.confirm = QCheckBox("")
        self.confirm.toggled.connect(self._confirm_toggled)
        self.msg = label("", "sub")
        v.addWidget(self.share)
        v.addWidget(self.confirm)
        v.addWidget(self.msg)
        self.sync()

    def writer(self) -> M.Slot | None:
        w = self.owner.ms.roles["writer"]
        return w[0] if w else None

    def sync(self, note: str = ""):
        ms, w = self.owner.ms, self.writer()
        on = ms.vision_share == "writer" and w is not None
        for cb, val in ((self.share, on), (self.confirm, bool(w and w.supports_vision is True))):
            cb.blockSignals(True)
            cb.setChecked(val)
            cb.blockSignals(False)
        self.confirm.setVisible(w is not None and (w.supports_vision is not True or not on))
        if w is not None:
            self.confirm.setText(f"我已在厂商文档确认「{w.vendor} {w.model}」支持图片输入，把它标记为「支持看图」")
        self.editor.setVisible(not on)
        if on:
            text = (f"✅ 看图使用主笔主用：{w.vendor} {w.model}（Key：钥匙串里的 {w.key_ref}，与主笔同一把，本次打开只读一次）。"
                    + ("原来单独配置的看图模型仍保存着，关闭共用即恢复使用。" if ms.roles["vision"] else ""))
        elif w is None:
            text = "要共用，请先在「主笔」页签设置主用模型。"
        elif w.supports_vision is not True:
            text = (f"主笔主用「{w.vendor} {w.model}」还没有标记为支持看图。程序不内置哪些模型能看图："
                    "请先查厂商文档，确认这个模型支持图片输入后，勾选上面的确认框，再打开「与主笔共用」。")
        else:
            text = f"主笔主用「{w.vendor} {w.model}」已标记支持看图，可以打开「与主笔共用」。"
        self.msg.setText(note + text)

    def _save(self) -> bool:
        try:
            self.owner.save()
        except (ConfigError, OSError) as e:
            self.sync(f"❌ 保存失败：{e}　")
            return False
        return True

    def _share_toggled(self, on: bool):
        w = self.writer()
        if on and (w is None or w.supports_vision is not True):
            self.sync("❌ 不能共用：")
            return
        self.owner.ms.vision_share = "writer" if on else None
        if self._save():
            self.sync("✅ 已保存。" if on else "✅ 已关闭共用，看图使用下面单独配置的模型（没有配置则跳过看图）。")

    def _confirm_toggled(self, on: bool):
        w = self.writer()
        if w is None:
            return self.sync()
        w.supports_vision = True if on else None
        if not on:
            self.owner.ms.vision_share = None
        if self._save():
            self.sync("✅ 已保存标记。" if on else "✅ 已取消「支持看图」标记，并关闭共用。")


class RoleEditor(QWidget):
    """Stacked slot cards for one role + the dashed 添加备用 button."""

    def __init__(self, owner: "ModelsPage", role: str):
        super().__init__()
        self.owner, self.role = owner, role
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(12)
        v.addLayout(self.cards_box)
        self.add_btn = button("", "dashed", self._add, icon="plus", icon_color="muted")
        v.addWidget(self.add_btn)
        self.msg = label("", "sub")
        v.addWidget(self.msg)
        self.cards: list[SlotCard] = []
        self.refresh()

    def refresh(self):
        clear(self.cards_box)
        slots = self.owner.ms.roles[self.role]
        self.cards = [SlotCard(self, i, s) for i, s in enumerate(slots)]
        for c in self.cards:
            self.cards_box.addWidget(c)
        if not slots:
            self._add()
        self._sync_add()

    def _sync_add(self):
        n = len(self.cards)
        self.add_btn.setVisible(n < 4)
        self.add_btn.setText(f"添加备用{n}（最多 1 主用 + 3 备用）" if n else "添加主用模型")

    def flash(self, i, text):
        if i is not None and 0 <= i < len(self.cards):
            self.cards[i].status.setText(text)
        else:
            self.msg.setText(text)

    def _add(self) -> "SlotCard":
        if any(c.idx is None for c in self.cards):        # one unsaved card at a time
            return next(c for c in self.cards if c.idx is None)
        c = SlotCard(self, None, None)
        self.cards.append(c)
        self.cards_box.addWidget(c)
        self._sync_add()
        return c


class ModelsPage(QWidget):
    def __init__(self, cfg, transport=None):
        super().__init__()
        self.setObjectName("Page")
        self.cfg = cfg
        if transport is None:
            from ..llm.client import urllib_transport as transport
        self.transport = transport
        body, lay = page("模型设置")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)
        lay.addWidget(label("和终端共用同一个 models.toml；API Key 只存进系统钥匙串（Keychain），界面不显示明文。"
                            "每个角色 1 个主用 + 最多 3 个备用，主用失败时按顺序自动换备用。", "muted"))
        self.ms, self.path, err = None, None, None
        if cfg is None:
            err = "还没有读到配置文件 config.local.toml：请先按《Mac 运行指南》第 2 节完成安装。"
        else:
            self.path = cfg.models_path
            try:
                if self.path.is_file():
                    self.ms = M.load(self.path)
                elif cfg.legacy_models:
                    err = "模型设置仍是旧格式：请在终端运行一次 litreader models migrate"
                else:
                    self.ms = M.ModelSettings()
            except ConfigError as e:
                err = f"models.toml 有问题：{e}"
        try:
            self.cal_store = calibration.Store(cfg.data_dir, cfg.vault_root) if cfg else None
        except (ValueError, AttributeError):
            self.cal_store = None
        if err:
            lay.addWidget(label(err, "err"))
            lay.addStretch(1)
            return
        self.tabs = Segmented([(r, zh, None) for r, zh in M.ROLES.items()] + [("parser", "解析器", None)], "writer")
        self.tabs.setMaximumWidth(420)
        lay.addLayout(hrow(self.tabs, None, label(f"文件：{self.path.name}", "path", wrap=False)))
        self.stack = QStackedWidget()
        self.editors = {}
        self._tab_index = {}
        for role, zh in M.ROLES.items():
            ed = RoleEditor(self, role)
            self.editors[role] = ed
            c, cl = card(margins=(24, 20, 24, 22), spacing=12)
            cl.addLayout(hrow(label(f"{zh}（{ROLE_EN[role]}）", "h2", wrap=False), None,
                              label("1 个主用 + 最多 3 个备用，按顺序自动切换", "sub", wrap=False)))
            cl.addWidget(label(f"{ROLE_HINT[role]}。程序不内置模型列表，也不内置价格：模型名、单价都从厂商文档复制填写；"
                               "选厂商会预填官方 Base URL。校准按“厂商 + 模型名 + 角色”分别记录在本机（应用支持目录，不在 Obsidian 库里）。",
                               "sub"))
            if role == "vision":
                self.vision_optional = label(VISION_OPTIONAL, "info")
                cl.addWidget(self.vision_optional)
                self.vision_share = VisionShare(self, ed)
                cl.addWidget(self.vision_share)
            cl.addWidget(ed)
            self._tab_index[role] = self.stack.count()
            self.stack.addWidget(_top(c))
        self.parser = ParserPanel(cfg)
        self._tab_index["parser"] = self.stack.count()
        self.stack.addWidget(_top(self.parser))
        self.tabs.changed.connect(lambda k: self.stack.setCurrentIndex(self._tab_index[k]))
        lay.addWidget(self.stack, 1)

    def save(self):
        sv = self.ms.shared_vision_slot()
        if self.ms.vision_share and (sv is None or sv.supports_vision is not True):
            self.ms.vision_share = None      # 主笔主用 changed/removed: 共用 can no longer apply -> switch it off
        M.save(self.ms, self.path)
        vs = getattr(self, "vision_share", None)
        if vs is not None:
            vs.sync()


def _top(w: QWidget) -> QWidget:
    """Stack page whose content sits at the top (a QStackedWidget page otherwise stretches its card)."""
    holder = QWidget()
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 2, 0, 0)
    v.addWidget(w)
    v.addStretch(1)
    return holder


PARSER_CARDS = [  # (id, title, sub, keychain name, token page, docs (label, url), wired into the reading flow?)
    ("mineru", "MinerU", "云端解析，vlm 模型（默认解析器）", "MINERU_API_TOKEN", "https://mineru.net/apiManage/token",
     ("接口文档", "https://mineru.net/apiManage/docs"), True),
    ("paddle", "PaddleOCR（PP-Structure）", "百度飞桨 AI Studio · 备用解析器 / OCR", "PADDLE_API_KEY",
     "https://aistudio.baidu.com/index/accessToken", ("PaddleOCR 服务页", "https://aistudio.baidu.com/paddleocr/task"), False),
]


def paddle_check(token: str, req=None) -> tuple[bool | None, str]:
    """No free, documented auth-check endpoint for the PaddleOCR (AI Studio) service could be verified, so this is a
    clearly labelled MINIMAL check: the token is stored and looks like a token. It does not contact the server."""
    if not token:
        return False, "未保存 Token"
    if len(token) < 16 or any(c.isspace() for c in token):
        return False, "格式不像 Token（太短或含空格）"
    return None, "仅本地检查：已保存且格式正常（PaddleOCR 没有可核实的免费鉴权接口，未联网验证）"


def mineru_check(token: str, req=None):
    from ..parse.mineru_api import check_token
    return check_token(token, req)


CHECKS = {"mineru": mineru_check, "paddle": paddle_check}


class ParserCard(QFrame):
    """Radio-style card: name + links, masked token (更换 / 保存), keychain status, 测试连接. Values are never displayed.
    G7: 保存 stays grey until something is typed; after saving the status pill reads 「钥匙串已保存」."""
    _tested = Signal(object, str)

    def __init__(self, pid, title, sub, ref, token_url, doc, wired, req=None):
        super().__init__()
        self.pid, self.req = pid, req          # req: injectable HTTP function (tests use fakes)
        self.ref, self.token_url, self.doc = ref, token_url, doc
        self.setProperty("role", "cand_on" if wired else "cand")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        dot = label("◉" if wired else "○", None, wrap=False)
        dot.setStyleSheet(f"color:{theme.c('accent' if wired else 'muted')}; font-size:16px;")
        state = pill("当前使用", "ok") if wired else pill("备用 · 本版本精读流程尚未接入", "gray")
        self.get_btn = button("获取 Token ↗", "link", lambda: QDesktopServices.openUrl(QUrl(token_url)))
        self.doc_btn = button(f"{doc[0]} ↗", "link", lambda: QDesktopServices.openUrl(QUrl(doc[1])))
        v.addLayout(hrow(dot, label(title, "h3", wrap=False), state, None, spacing=8))
        v.addLayout(hrow(label(sub, "sub"), None, self.get_btn, self.doc_btn, spacing=12))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setMinimumWidth(200)
        self.edit.returnPressed.connect(self.save)
        self.status = pill("", "gray")
        self.tested = pill("未测试", "gray")
        self.change = button("更换", "small", self._unlock)
        self.save_btn = button("保存", "small", self.save, "先粘贴 Token")
        self.save_btn.setEnabled(False)
        self.edit.textChanged.connect(lambda t: self.save_btn.setEnabled(bool(t.strip())))
        self.test_btn = button("测试连接", "small", self.test,
                               "MinerU：查询一个不存在的任务（不上传、不计费）判断 Token 是否有效" if pid == "mineru"
                               else "PaddleOCR：仅本地检查（没有可核实的免费鉴权接口）", icon="refresh-cw")
        self._tested.connect(self._show_test)
        v.addWidget(label(f"Token（钥匙串名称：{ref}）", "th", wrap=False))
        v.addLayout(hrow(self.edit, self.status, self.tested, self.change, self.save_btn, self.test_btn, spacing=8))
        self.msg = label("", "sub")
        self.msg.setVisible(False)
        v.addWidget(self.msg)
        self.refresh()

    def _say(self, t: str):
        self.msg.setText(t)
        self.msg.setVisible(bool(t))

    def state(self) -> str:
        import os
        if os.environ.get(self.ref):
            return "env"
        st = secrets.status(self.ref)     # G11-1: no keychain read while rendering
        return {"saved": "saved", "indexed": "indexed", "denied": "denied", "unknown": "unknown"}[st]

    def refresh(self):
        st = self.state()
        text, kind = {"env": ("来自环境变量", "info"), "saved": ("钥匙串已保存", "ok"),
                      "indexed": ("已保存（未读取）", "ok"), "unknown": ("未读取（用到时再读）", "gray"),
                      "denied": ("钥匙串读取被拒绝", "stop"), "missing": ("未保存", "trial")}[st]
        self.status.setText(text)
        self.status.setProperty("role", f"pill_{kind}")
        from .widgets import repolish
        repolish(self.status)
        has = st in ("env", "saved", "indexed")
        self.edit.clear()
        self.edit.setEnabled(not has)
        self.change.setVisible(has)
        self.save_btn.setVisible(not has)
        self.edit.setPlaceholderText("•••••••••••••••• 已保存" if has else "粘贴 Token（只存进系统钥匙串，不写进任何文件）")
        self.save_btn.setEnabled(False)
        self.test_btn.setEnabled(st != "missing")

    def test(self):
        secrets.forget_denied(self.ref)   # explicit click = one fresh read of this token only
        tok = secrets.get(self.ref) or ""
        self._set_tested("… 正在测试", "gray")
        self.test_btn.setEnabled(False)
        fn, req = CHECKS[self.pid], self.req

        def work():
            try:
                ok, msg = fn(tok, req)
            except Exception as e:  # noqa: BLE001
                ok, msg = None, type(e).__name__
            self._tested.emit(ok, msg)
        if self.req is not None:      # tests: synchronous
            work()
        else:  # pragma: no cover - real network in a thread
            import threading
            threading.Thread(target=work, daemon=True).start()

    def _set_tested(self, text, kind):
        from .widgets import repolish
        self.tested.setText(text)
        self.tested.setProperty("role", f"pill_{kind}")
        repolish(self.tested)

    def _show_test(self, ok, msg):
        self.refresh()                     # status pill reflects what the read just learned
        self._set_tested({True: "✅ 连接正常", False: "❌ 未通过", None: "ℹ 无法确认"}[ok], {True: "ok", False: "stop", None: "info"}[ok])
        self._say(msg)
        self.test_btn.setEnabled(True)

    def _unlock(self):
        self.edit.setEnabled(True)
        self.save_btn.setVisible(True)
        self.change.setVisible(False)
        self.edit.setPlaceholderText("粘贴新的 Token")
        self.edit.setFocus()

    def save(self):
        v = self.edit.text().strip()
        if not v:
            self._say("请先粘贴 Token。")
            return
        try:
            secrets.set_secret(self.ref, v)
        except Exception as e:  # noqa: BLE001
            self._say(f"❌ 保存失败：{type(e).__name__}")
            return
        self._say("✅ 钥匙串已保存（界面不会再显示它）。可以点「测试连接」。")
        self.refresh()


class ParserPanel(QWidget):
    """模型设置 → 解析器 (G6; moved here from 基础设置)."""

    def __init__(self, cfg=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        c, cl = card(margins=(24, 20, 24, 22), spacing=12)
        v.addWidget(c)
        cl.addLayout(hrow(label("PDF 解析器", "h2", wrap=False), None, label("Token 只存进系统钥匙串", "sub", wrap=False)))
        cl.addWidget(label("精读前先把 PDF 解析成文字、表格和图。本版本精读流程使用 MinerU；PaddleOCR 的 Token 可以先保存，"
                           "接入后作为备用解析器。解析结果缓存在本机，同一篇不会重复上传。", "sub"))
        self.cards = [ParserCard(*x) for x in PARSER_CARDS]
        for pc in self.cards:
            cl.addWidget(pc)
        self.rows = self.cards       # same shape as the old TokensCard (tests)
