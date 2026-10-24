"""基础设置 panels: Zotero 一键检测 (G5) and the Obsidian vault card (G6). Parser tokens moved to 模型设置 → 解析器.

Zotero: reuses `litreader setup zotero` (zotero/setup.py): read prefs.js + check the data dir + GET
localhost:23119/api/. litreader never changes Zotero settings; config.local.toml is written only after the user
confirms (backup .bak-<time> first, TOML validated). Tokens: masked input → system keychain (secrets.set_secret);
values are never shown, only 已保存 / 未保存 / 来自环境变量."""
from __future__ import annotations

from ..platform_words import display_path

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..appconfig import DEFAULT_OUTPUT_DIR
from ..zotero import setup as zs
from .widgets import button, card, clear, hrow, label, path_label, pill, sep

API_TEXT = {"OK": ("ok", "本地接口可用（只读）"), "DISABLED": ("trial", "本地接口未开启"),
            "NOT_RUNNING": ("stop", "Zotero 没有运行 / 连不上"), "ERROR": ("stop", "本地接口返回异常")}


class _Sig(QObject):
    done = Signal(object, object)


class ZoteroSetupCard(QWidget):
    """一键检测 Zotero. `detect_fn` / `opener` are injectable for tests (no real Zotero needed)."""
    saved = Signal(str)

    def __init__(self, cfg, cfg_error: str | None = None, detect_fn=None, opener=None, cfg_path=None):
        super().__init__()
        self.cfg, self.cfg_error = cfg, cfg_error
        # W5: a config file can exist (fresh, vault root still empty) while cfg failed to load -> still savable
        self.cfg_file = Path(cfg.path) if cfg is not None else (Path(cfg_path) if cfg_path else None)
        self.detect_fn, self.opener = detect_fn, opener
        self.data_dir_override: Path | None = None
        self.result = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        c, self.l = card(spacing=12)
        v.addWidget(c)
        self.btn = button("一键检测 Zotero", "primary", self.run, "只读：找 Zotero 数据目录，并检查本地接口 localhost:23119",
                          icon="refresh-cw", icon_color="on_accent")
        self.pick = button("手动选择数据目录…", "small", self._pick_dir)
        self.l.addLayout(hrow(label("Zotero 一键检测", "h2", wrap=False), pill("只读", "gray"), None, self.pick, self.btn,
                              spacing=8))
        self.l.addWidget(label("自动查找 Zotero 数据目录（zotero.sqlite、storage/），并检查本地接口。litreader 只读取，"
                               "从不修改 Zotero 的设置；检测结果要你确认后才写入 config.local.toml。", "sub"))
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.l.addLayout(self.body)
        self._sig = _Sig()
        self._sig.done.connect(self._show)
        self._current()

    # ----- states -----
    def _current(self):
        clear(self.body)
        if self.cfg is None:
            self.body.addWidget(label(self.cfg_error or "还没有配置文件 config.local.toml：检测可以做，但保存要先完成安装。", "warn"))
            return
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(8)
        for i, (k, val) in enumerate((("配置文件", self.cfg.path), ("Zotero 本地接口", f"{self.cfg.zotero_api}（只读）"),
                                      ("Zotero 数据目录", self.cfg.zotero_data_dir), ("Obsidian 库", self.cfg.vault_root),
                                      ("笔记写入", display_path(f"{self.cfg.dry_run_root}/")))):
            g.addWidget(label(k, "th", wrap=False), i, 0)
            g.addWidget(path_label(str(val)), i, 1)
        g.setColumnMinimumWidth(0, 140)
        g.setColumnStretch(1, 1)
        self.body.addLayout(g)

    def run(self):
        self.btn.setEnabled(False)
        self.btn.setText("正在检测…")

        def work():
            try:
                res = zs.check(self.data_dir_override, opener=self.opener, detect_fn=self.detect_fn)
                self._sig.done.emit(res, None)
            except Exception as e:  # noqa: BLE001
                self._sig.done.emit(None, e)
        threading.Thread(target=work, daemon=True).start()

    def _pick_dir(self):
        p = QFileDialog.getExistingDirectory(self, "选择 Zotero 数据目录（里面有 zotero.sqlite 和 storage）")
        if p:
            self.data_dir_override = Path(p)
            self.run()

    def _show(self, res, err):
        self.btn.setEnabled(True)
        self.btn.setText("重新检测")
        clear(self.body)
        if err is not None:
            self.body.addWidget(label(f"检测失败：{err}", "err"))
            return
        d, pr = res
        self.result = res
        # data dir
        self.body.addLayout(hrow(pill("找到数据目录" if d["valid"] else "没找到数据目录", "ok" if d["valid"] else "stop"),
                                 label(f"来源：{d['source']}", "sub", wrap=False), None, spacing=8))
        self.body.addWidget(path_label(str(d["data_dir"])))
        self.body.addLayout(hrow(*[pill(f"{'✓' if ok else '✗'} {k}", "ok" if ok else "stop") for k, ok in d["checks"].items()],
                                 None, spacing=6))
        if d["profiles"] > 1:
            self.body.addWidget(label(f"找到 {d['profiles']} 个 Zotero 配置，用的是最近修改的那个。", "sub"))
        if not d["valid"]:
            self.body.addWidget(label("没找到 zotero.sqlite 或 storage/：请在 Zotero 设置 → 高级 查看“数据目录：”一行，"
                                      "再点右上角「手动选择数据目录…」。", "warn"))
        self.body.addWidget(sep())
        kind, text = API_TEXT.get(pr["status"], ("stop", pr["status"]))
        self.body.addLayout(hrow(pill(text, kind), label(pr["url"], "path", wrap=False), None, spacing=8))
        steps = []
        if pr["status"] == "DISABLED":
            head, steps = "Zotero 正在运行，但本地接口没有开启。请按下面步骤在 Zotero 里打开（litreader 不会替你改 Zotero 设置）：", zs.ENABLE_STEPS
        elif pr["status"] == "NOT_RUNNING":
            head, steps = "连不上 Zotero 的本地接口：", list(zs.NOT_RUNNING_STEPS)
            if not d.get("local_api_pref"):
                steps += ["打开 Zotero 后还需开启本地接口：" + "；".join(zs.ENABLE_STEPS[1:4])]
        elif pr["status"] == "ERROR":
            head = f"本地接口返回 HTTP {pr.get('http')}，请确认 Zotero 是 7 或更新版本。"
        if pr["status"] != "OK":
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(4)
            bl.addWidget(label(head, "strong"))
            for i, s in enumerate(steps, 1):
                bl.addWidget(label(f"{i}. {s}"))
            bl.addWidget(label("做完后点「重新检测」。", "sub"))
            self.body.addWidget(box)
        # save
        if self.cfg_file is None:
            self.body.addWidget(label("还没有 config.local.toml：请先在下方 Obsidian 卡片选好库并保存。", "sub"))
            return
        if not d["valid"]:
            self.body.addWidget(label("数据目录没有通过检查，暂不提供保存。", "sub"))
            return
        new, changes = zs.config_updates(self.cfg_file.read_text("utf-8"), d["data_dir"],
                                         f"http://localhost:{d['port']}/api")
        self.pending = (new, changes)
        if not changes:
            self.body.addWidget(label("✅ 设置已正确，无需保存（路径写法不同但指向同一位置，也算一致）。", "ok"))
            return
        self.body.addWidget(label("检测结果和 config.local.toml 不同，确认后写入（会先备份原文件）：", "strong"))
        for ch in changes:
            self.body.addWidget(path_label(ch))
        self.save_btn = button("保存检测结果", "primary", lambda: self._save(), "写入 config.local.toml（先备份原文件）")
        self.body.addLayout(hrow(None, self.save_btn))

    def _save(self, confirm=None):
        new, changes = self.pending
        ask = confirm or (lambda: QMessageBox.question(
            self, "保存 Zotero 设置？", "将修改 config.local.toml：\n" + "\n".join(changes) +
            "\n\n原文件会先备份为 .bak-时间戳。Zotero 本身不会被修改。") == QMessageBox.Yes)
        if not ask():
            return
        try:
            bak = zs.save_config(self.cfg_file, new)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.save_btn.setEnabled(False)
        self.body.addWidget(label(f"✅ 已保存；原文件备份在 {bak.name}。下一次精读开始时生效。", "ok"))
        self.saved.emit(str(bak))


class ObsidianCard(QWidget):
    """基础设置 → Obsidian (G6, G10-1): vault path + 选择…; 笔记文件夹 (output_dir, default litreader) editable + 选择…
    (must be inside the vault) with the resolved 论文库 path shown; a warning when the folder has no .obsidian/, and the
    same confirm + backup save into config.local.toml as the Zotero card. Nothing is created, moved or deleted here;
    runs write only under <vault>/<output_dir>/."""
    saved = Signal(str)

    def __init__(self, cfg, cfg_error: str | None = None, picker=None, detect=None, folder_picker=None,
                 cfg_path=None):
        super().__init__()
        self.folder_picker = folder_picker or (lambda start: QFileDialog.getExistingDirectory(
            self, "选择笔记文件夹（须在 Obsidian 库内）", start))
        self.cfg, self.cfg_error = cfg, cfg_error
        # W5: a config file can exist (fresh, vault root still empty) while cfg failed to load -> still savable
        self.cfg_file = Path(cfg.path) if cfg is not None else (Path(cfg_path) if cfg_path else None)
        from ..configedit import detect_vaults
        self.detect = detect or detect_vaults
        self.picker = picker or (lambda: QFileDialog.getExistingDirectory(self, "选择 Obsidian 库（含 .obsidian 文件夹）"))
        self.pending = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        c, l = card(spacing=12)
        v.addWidget(c)
        l.addWidget(label("Obsidian", "h2", wrap=False))
        l.addWidget(label("精读笔记会写入你的 Obsidian 库。", "sub"))
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        self.path = QLineEdit(str(cfg.vault_root) if cfg else "")
        self.detected = self._autodetect()
        self.path.setPlaceholderText("/Users/<你>/<你的库>")
        self.path.textChanged.connect(lambda _t: self.check())
        self.pick_btn = button("选择…", None, self._pick, icon="folder-open")
        g.addWidget(label("库（vault）路径", "th", wrap=False), 0, 0)
        g.addLayout(hrow(self.path, self.pick_btn, spacing=8), 0, 1)
        self.papers_dir = cfg.papers_dir if cfg else "论文库"
        self.cur_out = cfg.dry_run_dir if cfg else DEFAULT_OUTPUT_DIR
        self.out = QLineEdit(self.cur_out)
        self.out.setObjectName("OutputDir")
        self.out.setPlaceholderText(DEFAULT_OUTPUT_DIR)
        self.out.setToolTip("库根目录下的相对文件夹；笔记写在 <它>/论文库/<主题>/，图表和证据档案也在它里面")
        self.out.textChanged.connect(lambda _t: self.check())
        self.out_btn = button("选择…", None, self._pick_out, icon="folder-open")
        g.addWidget(label("笔记文件夹", "th", wrap=False), 1, 0)
        g.addLayout(hrow(self.out, self.out_btn, spacing=8), 1, 1)
        self.papers = path_label("")
        self.papers.setObjectName("ResolvedPapers")
        g.addWidget(label("论文写入位置", "th", wrap=False), 2, 0)
        g.addWidget(self.papers, 2, 1)
        g.setColumnMinimumWidth(0, 120)
        g.setColumnStretch(1, 1)
        l.addLayout(g)
        if self.detected:
            d = self.detected[0]
            more = f"（另有 {len(self.detected) - 1} 个库，可点「选择…」换）" if len(self.detected) > 1 else ""
            self.detect_note = label(f"🔍 已从 Obsidian 自动检测到库「{d['name']}」"
                                     f"{'（当前打开）' if d['open'] else '（最近打开）'}，请确认后保存{more}。", "sub")
            l.addWidget(self.detect_note)
        self.status = QVBoxLayout()
        self.status.setSpacing(8)
        l.addLayout(self.status)
        self.check()

    def _autodetect(self) -> list:
        """First run only: the current path is empty or not an existing vault -> prefill Obsidian's most recent one
        (obsidian.json is read, never written). Nothing is saved until the user presses 保存."""
        cur = self.path.text().strip()
        if cur and (Path(cur).expanduser() / ".obsidian").is_dir():
            return []
        try:
            found = [d for d in self.detect() if d["is_vault"]]
        except Exception:  # noqa: BLE001
            return []
        if found:
            self.path.setText(str(found[0]["path"]))
        return found

    def _pick(self):
        p = self.picker()
        if p:
            self.path.setText(str(p))

    def _pick_out(self):
        from ..configedit import rel_in_vault
        vault = self.path.text().strip()
        p = self.folder_picker(vault)
        if not p:
            return
        rel = rel_in_vault(vault, p) if vault else None
        if rel is None:
            QMessageBox.warning(self, "不在库内", "笔记文件夹必须在 Obsidian 库里面（库根目录下的某个文件夹）。")
            return
        self.out.setText(rel)

    def output_dir(self) -> str | None:
        """Normalized folder from the field (empty -> default), or None when invalid."""
        from ..appconfig import normalize_output_dir
        from ..errors import LitError
        try:
            return normalize_output_dir(self.out.text().strip() or DEFAULT_OUTPUT_DIR)
        except LitError:
            return None

    def check(self):
        from ..configedit import check_vault, vault_updates
        if not hasattr(self, "status"):
            return
        clear(self.status)
        self.pending = None
        txt = self.path.text().strip()
        out = self.output_dir()
        self.papers.setText(display_path(f"{txt or '<库>'}/{out}/{self.papers_dir}/") if out else "—")
        if not txt:
            self.status.addWidget(label("还没有填写库路径。", "warn"))
            return
        if out is None:
            self.status.addWidget(label("笔记文件夹必须是库里面的相对路径（如 litreader），不能以 / 开头，也不能含 ..", "err"))
            return
        info = check_vault(txt, self.papers_dir, out)
        if not info["exists"]:
            self.status.addWidget(label("找不到这个文件夹。", "err"))
            return
        if not info["is_vault"]:
            self.status.addWidget(label("⚠️ 这个文件夹里没有 .obsidian/，看起来不像 Obsidian 库。请确认选的是库的根目录"
                                        "（在 Obsidian 里打开过的那个文件夹）。", "warn"))
        if self.cfg_file is None:
            self.status.addWidget(label(self.cfg_error or "还没有 config.local.toml：先完成安装再保存。", "sub"))
            return
        if self.cur_out != out and (Path(txt).expanduser() / self.cur_out).is_dir():
            self.status.addWidget(label(f"已有笔记留在原文件夹「{self.cur_out}」，不会被移动或删除；"
                                        "之后的新笔记写到新文件夹。", "sub"))
        new, changes = vault_updates(self.cfg_file.read_text("utf-8"), txt, out, self.cur_out)
        if not changes:
            self.status.addWidget(label("✅ 设置已正确，无需保存。", "ok"))
            return
        self.pending = (new, changes)
        for ch in changes:
            self.status.addWidget(path_label(ch))
        self.save_btn = button("保存设置", "primary", lambda: self._save(), "写入 config.local.toml（先备份原文件）")
        self.status.addLayout(hrow(None, self.save_btn))

    def _save(self, confirm=None):
        if not self.pending:
            return
        new, changes = self.pending
        ask = confirm or (lambda: QMessageBox.question(
            self, "保存 Obsidian 设置？", "将修改 config.local.toml：\n" + "\n".join(changes) +
            "\n\n原文件会先备份为 .bak-时间戳。") == QMessageBox.Yes)
        if not ask():
            return
        try:
            bak = zs.save_config(self.cfg_file, new)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.pending = None
        self.save_btn.setEnabled(False)
        self.status.addWidget(label(f"✅ 已保存；原文件备份在 {bak.name}。下一次精读开始时生效。", "ok"))
        self.saved.emit(str(bak))
