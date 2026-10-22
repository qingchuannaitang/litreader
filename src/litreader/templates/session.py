"""Per-run template step for the reading flow: refresh -> classify -> choose -> confirm/override -> freeze.

The frozen result holds the parsed template objects built from registry snapshot bytes (objects/<sha>.md), so editing
the library during the run cannot mix versions (spec §5.4 第三关, T07)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import Stop
from . import classify as cls
from . import select as sel
from .format import Template
from .prompt import prompt_suffix, validation_spec
from .registry import Corrupt, Locked, Registry

REQ = re.compile(r"^\s*(?:请)?(?:用|使用|按)[「“\"《]?(?P<t>[^」”\"》]{1,40}?)[」”\"》]?模板(?:来|进行)?\s*")


@dataclass
class Frozen:
    main: Template
    main_rec: dict
    modules: list[Template]
    module_recs: list[dict]
    study: dict
    reason: str
    user_override: bool
    snapshot_n: int
    warnings: list[str] = field(default_factory=list)

    @property
    def prompt_suffix(self) -> str | None:
        return prompt_suffix(self.main, self.modules)

    @property
    def validation_spec(self) -> dict | None:
        return validation_spec(self.main, self.modules) if self.prompt_suffix else None

    def provenance(self) -> dict:
        r = self.main_rec
        ver = f"{r['declared_version']}+r{r['registry_version']}" if r.get("declared_version") else f"r{r['registry_version']}"
        return {"template_id": r["id"], "template_version": ver, "template_sha256": r["sha256"],
                "template_modules": [f"{m['id']}@r{m['registry_version']}" for m in self.module_recs],
                "study_type": self.study["study_type"]}

    def receipt(self) -> dict:
        return {**self.provenance(), "template_title": self.main_rec["title"], "registry_snapshot": self.snapshot_n,
                "modules": [{"id": m["id"], "version": m["registry_version"], "sha256": m["sha256"]} for m in self.module_recs],
                "selection_reason": self.reason, "user_override": self.user_override,
                "study": {k: self.study.get(k) for k in ("study_type", "secondary", "confidence", "reason", "quote", "block_id",
                                                          "page", "source", "keyword_check", "ambiguous")},
                "warnings": self.warnings}


def split_request(command: str) -> tuple[str | None, str]:
    m = REQ.match(command)
    if not m:
        return None, command
    return m.group("t").strip(), command[m.end():]


def registry_for(cfg) -> Registry:
    lib = cfg.vault_root / cfg.templates_dir if cfg.templates_dir else None
    return Registry(cfg.data_dir / "templates", lib)


def refresh_or_current(reg: Registry, ui, tagger=None) -> dict:
    try:
        snap, events, notes = reg.refresh(tagger)
    except Locked as e:
        ui.say(f"⚠️ {e}；本次使用上一次完整的模板登记")
        snap = reg.snapshot()
        if not snap["n"]:
            raise Stop("模板登记被锁且从未完成过登记，停止")
        return snap
    except Corrupt:
        raise
    new = [e for e in events if e.get("op") in ("NEW", "NEW_VERSION", "MOVED", "STATUS", "RESTORED")]
    for e in new:
        if e["op"] in ("NEW", "NEW_VERSION") and str(e.get("id", "")).startswith(("main.", "overview.", "module.")) \
                and e.get("to") == "ACTIVE" and snap["n"] == 1:
            continue   # first-run built-ins: not news
        ui.say(f"  模板库变化：{_event_zh(e)}")
    for n in notes:
        ui.say(f"  模板库提示：{n}")
    return snap


def _event_zh(e) -> str:
    to = {"ACTIVE": "可用", "NEEDS_REVIEW": "待审（不会自动选用，用 litreader templates approve 批准）", "REJECTED": "已拒绝",
          "SUPERSEDED": "旧版已被替代", "REMOVED": "文件已移除", "CONFLICT": "ID 冲突（请改其中一个文件的 id）"}.get(e.get("to"), e.get("to"))
    if e["op"] == "MOVED":
        return f"{e['id']} 改名/移动为 {e['to_path']}（内容不变，版本不变）"
    return f"{e['id']} v{e.get('version')} → {to}"


def resolve_request(pool: list[dict], text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    exact = [r for r in pool if text in (r["id"], r["title"])]
    sub = exact or [r for r in pool if text in r["title"] or text in r["id"]]
    if len(sub) == 1:
        return sub[0]["id"], None
    return None, (f"没有找到名为「{text}」的可用主模板" if not sub else f"「{text}」对应多个模板，请在下一步用序号选择")


def prepare(cfg, ui, blocks, *, title: str, zotero_tags: list[str], chain, transport, env, requested: str | None,
            ask_always: bool = False, runs: list | None = None, project_id: str | None = None,
            project_title: str | None = None) -> Frozen:
    reg = registry_for(cfg)
    snap = refresh_or_current(reg, ui)
    study = cls.classify(blocks, title=title, zotero_tags=zotero_tags, chain=chain, transport=transport, env=env)
    if runs is not None and study.get("run"):
        runs.append(study["run"])
    pool = sel.mains(reg, snap)
    req_id, msg = resolve_request(pool, requested)
    if msg:
        ui.say(f"⚠️ {msg}")
    ch = sel.choose(reg, snap, study, requested=req_id, project_id=project_id)
    if ch.tier == 3 and project_title:
        ch.reason = f"课题《{project_title}》指定的主模板"
    ui.say(f"论文类型：{cls.describe(study)}")
    main, mods, override, mods_manual = ch.main, list(ch.modules), False, False
    must_pick = ch.ambiguous or ask_always or bool(msg)
    while True:
        ui.say(f"本次使用：{sel.label(main)} ＋ " + ("、".join(m["title"] for m in mods) if mods else "无专业模块"))
        ui.say(f"  理由：{ch.reason if not override else '你手动选择'}")
        for s in ch.skipped_modules:
            ui.say(f"  未用模块：{s}")
        cands = ch.candidates
        ui.say("可选主模板：")
        for i, (r, tier, note) in enumerate(cands, 1):
            mark = " ← 本次" if r is main else ""
            extra = f" —— {sel.TIER_ZH[tier]}" if tier is not None else f" —— 不适用：{note or '不在候选'}"
            ui.say(f"  {i}. {sel.label(r)}{extra}{mark}")
        if must_pick:
            ui.say("⚠️ " + ("论文类型或模板存在歧义，" if ch.ambiguous else "") + "请输入序号选择主模板（不会随机选择）")
        from .. import events
        opts = ([events.opt("", f"确认：{sel.label(main)}", "回车")] if not must_pick else [])
        opts += [events.opt(str(i), sel.label(r), (f"{sel.TIER_ZH[tier]}" if tier is not None else f"不适用：{note or '不在候选'}")
                            + (" ← 本次" if r is main else "")) for i, (r, tier, note) in enumerate(cands, 1)]
        opts.append(events.opt("m", "调整专业模块"))
        a = events.decide(ui, "template", "回车确认 / 输入序号改选主模板 / m 调整专业模块 / q 取消：" if not must_pick else
                          "输入序号 / m 调整专业模块 / q 取消：", opts, default=None if must_pick else "",
                          data={"study": cls.describe(study), "main": sel.label(main),
                                "modules": [m["title"] for m in mods], "must_pick": must_pick}).strip().lower()
        if a in ("q", "取消", "quit"):
            from ..realrun import Cancelled
            raise Cancelled("已取消：未调用主笔模型、未写入任何笔记（解析结果已缓存）")
        if a == "" and not must_pick:
            break
        if a.isdigit() and 1 <= int(a) <= len(cands):
            r, tier, note = cands[int(a) - 1]
            if r is main:   # typing the number of the current choice confirms it (review UX fix)
                if tier is None:
                    ui.say(f"  注意：{sel.label(r)} 不在本篇的合格范围（{note or '类型不符'}），按你的选择使用；科研合同与闸门不变")
                break
            if r is not main:
                main, override = r, True
                if mods_manual:   # keep the modules the user picked, if they fit the new main template
                    mods = [m for m in mods if "any_main" in (m.get("compatible_with") or []) or main["id"] in (m.get("compatible_with") or [])]
                else:
                    mods, skipped = sel.pick_modules(reg, snap, main, study["study_type"], study.get("secondary") or [])
                    ch.skipped_modules = skipped
            if tier is None:
                ui.say(f"  注意：{sel.label(r)} 不在本篇的合格范围（{note or '类型不符'}），按你的选择使用；科研合同与闸门不变")
            must_pick = False
            continue
        if a == "m":
            mods, mods_manual = _pick_modules(reg, snap, ui, mods), True
            continue
        ui.say("无效输入")
    main_t = reg.load_template(main)
    mod_t = [reg.load_template(m) for m in mods]
    from .layout import build
    warns = build(main_t, mod_t).warnings
    for w in warns:
        ui.say(f"  模板提示：{w}")
    return Frozen(main_t, main, mod_t, mods, study, ch.reason if not override else "用户手动选择", override, snap["n"], warns)


def _pick_modules(reg, snap, ui, current: list[dict]) -> list[dict]:
    from .select import _effective_records
    allm = sorted([r for r in _effective_records(reg, snap).values() if r["role"] == "MODULE" and r["status"] == "ACTIVE"],
                  key=lambda r: r["id"])
    if not allm:
        ui.say("  没有可用的专业模块")
        return current
    for i, r in enumerate(allm, 1):
        ui.say(f"  {i}. {sel.label(r)}  适用：{','.join(r['applies_to']['study_types'])}{' ← 已选' if r in current else ''}")
    from .. import events
    a = events.decide(ui, "modules", f"输入要用的模块序号（逗号分隔，最多 {sel.MAX_MODULES} 个；0 = 不用模块；回车 = 不变）：",
                      [events.opt("", "不变"), events.opt("0", "不用模块")]
                      + [events.opt(str(i), sel.label(r), "已选" if r in current else "") for i, r in enumerate(allm, 1)],
                      default="", allow_custom=True).strip()
    if not a:
        return current
    if a == "0":
        return []
    out = []
    for x in re.split(r"[,，\s]+", a):
        if x.isdigit() and 1 <= int(x) <= len(allm) and allm[int(x) - 1] not in out:
            out.append(allm[int(x) - 1])
    return out[:sel.MAX_MODULES]
