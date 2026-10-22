"""Data for the 模板库 & 项目库 page (G4 read-only; G6 adds 新建模板 / 新建项目). Qt-free; reuses the same registries and formatting rules as
`litreader templates list/show` and `litreader project list/show`. No new storage.

The only write is the explicit 刷新模板库 button = `templates refresh` (registers templates in the app-data registry;
the template library folder in the vault is only read). Project data is read as-is: unlike the CLI, the GUI does not
run the manual-edit sync (that may create a new version), so this page never changes a project."""
from __future__ import annotations

from ..templates import builtin, vocab
from ..templates.registry import STATUS_ZH
from ..templates.session import registry_for

SOURCE_ZH = {"builtin": "内置", "library": "模板库", "ai_draft": "AI 草稿", "user": "界面新建"}
LISTED = ("ACTIVE", "NEEDS_REVIEW", "CONFLICT")


def _lib(cfg):
    return cfg.vault_root / cfg.templates_dir if cfg.templates_dir else None


def template_rows(cfg, *, show_all: bool = False) -> dict:
    """Same rows/flags as `templates list` (first use registers built-ins, like the CLI)."""
    reg = registry_for(cfg)
    snap = reg.snapshot()
    if not snap["n"]:
        snap, _, _ = reg.refresh()
    prefs = snap["prefs"]
    default_id = prefs.get("default_main") or builtin.FALLBACK
    rows = []
    for r in sorted(snap["records"], key=lambda r: (r["role"] or "Z", r["id"], r["registry_version"])):
        if not show_all and r["status"] not in LISTED:
            continue
        flags = []
        if prefs["pins"].get(r["id"]) == r["registry_version"]:
            flags.append("已固定")
        flags += [f"{vocab.STUDY_TYPES[t]}首选" for t, i in prefs["prefer_for"].items() if i == r["id"]]
        rows.append({
            "id": r["id"], "version": r["registry_version"], "title": r["title"], "role": r["role"],
            "role_zh": vocab.ROLE_ZH.get(r["role"], "未知"), "status": r["status"], "status_zh": STATUS_ZH[r["status"]],
            "source_zh": SOURCE_ZH.get(r["source"], r["source"]),
            "study_types": [vocab.STUDY_TYPES.get(t, t) for t in r["applies_to"]["study_types"]],
            "default": r["role"] == "MAIN_NOTE" and r["id"] == default_id,
            "default_explicit": prefs.get("default_main") == r["id"],
            "flags": flags,
            "warnings": len(r.get("review_reasons") or []) + len(r.get("warnings") or []) + len(r.get("errors") or []),
        })
    return {"registry": str(reg.root), "library": str(_lib(cfg)) if _lib(cfg) else None,
            "library_exists": bool(_lib(cfg) and _lib(cfg).is_dir()), "snapshot": snap["n"], "rows": rows}


def template_detail(cfg, tid: str, version: int | None = None) -> dict:
    """Same facts as `templates show`: metadata, section outline, module additions, issues, version history."""
    reg = registry_for(cfg)
    snap = reg.snapshot()
    r = reg.find(snap, tid, version)
    t = reg.load_template(r)
    sections = [{"level": s.level, "title": (s.title or "（标题取自模型小标题）") + (f"〈按论文补充：{s.suffix_default or '小标题'}〉"
                                                                   if s.suffix != "none" else ""), "id": s.id, "blocks": list(s.blocks)}
                for s in t.sections]
    sections += [{"level": 2, "title": f"＋ 模块章节 {s.title}", "id": s.id, "blocks": list(s.blocks)} for s in t.adds_sections]
    issues = [(lab, x) for k, lab in (("errors", "错误"), ("review_reasons", "待审"), ("warnings", "提示"))
              for x in r.get(k) or []]
    hist = sorted([x for x in snap["records"] if x["id"] == r["id"]], key=lambda x: x["registry_version"])
    return {
        "id": r["id"], "version": r["registry_version"], "title": r["title"], "status_zh": STATUS_ZH[r["status"]],
        "source_zh": SOURCE_ZH.get(r["source"], r["source"]), "path": r["path"], "sha": r["sha256"][:12],
        "size": r["size_bytes"], "role_zh": vocab.ROLE_ZH.get(r["role"], "未知"),
        "study_types": [("不限" if x == vocab.ANY else vocab.STUDY_TYPES.get(x, x)) for x in r["applies_to"]["study_types"]] or ["未声明"],
        "levels": list(r["applies_to"]["reading_levels"]), "priority": r["priority"], "features": list(r["features"]),
        "compatible_with": list(r.get("compatible_with") or []), "sections": sections,
        "fields": [f"{f['name']}（{f['label']}）" for f in t.adds_fields], "issues": issues,
        "history": [f"v{x['registry_version']} {STATUS_ZH[x['status']]}" for x in hist],
    }


def refresh_templates(cfg) -> dict:
    """`templates refresh` (no AI tagging): returns snapshot number + human-readable changes."""
    reg = registry_for(cfg)
    snap, events, notes = reg.refresh(None)
    changes = []
    for e in events:
        if e["op"] == "REFRESH":
            continue
        if e["op"] == "MOVED":
            changes.append(f"{e['id']} v{e['version']} 改名/移动（内容不变）")
        else:
            changes.append(f"{e['op']} {e.get('id')} v{e.get('version')}：{STATUS_ZH.get(e.get('from'), e.get('from') or '新')}"
                           f" → {STATUS_ZH.get(e.get('to'), e.get('to'))}")
    return {"snapshot": snap["n"], "changes": changes, "notes": list(notes)}


def template_bases(cfg) -> list[dict]:
    """Templates a new one can be based on: live main templates and modules."""
    return [r for r in template_rows(cfg)["rows"] if r["role"] in ("MAIN_NOTE", "MODULE") and r["status"] == "ACTIVE"]


def base_outline(cfg, tid: str | None, role: str) -> list[str]:
    """Section titles to prefill the editor with (blank -> a short starter list)."""
    from ..templates import create
    if tid:
        reg = registry_for(cfg)
        snap = reg.snapshot()
        if not snap["n"]:
            snap, _, _ = reg.refresh()
        t = reg.load_template(reg.find(snap, tid))
        return create.section_titles(t)
    return ["一、研究背景与问题", "二、研究设计与对象", "三、核心结果", "四、作者结论与我的评价"] if role == "MAIN_NOTE" \
        else ["专项评价（专业模块）"]


def create_template(cfg, *, title: str, role: str, base_id: str | None, sections: list[str],
                    study_types: list[str] | None = None) -> dict:
    """新建模板: build template Markdown (copy of `base_id`'s structure, or blank), lint it with the normal rules and
    register it in the app-data registry only (source "user"). Never writes the vault 模板库 folder or a built-in."""
    from ..templates import create
    reg = registry_for(cfg)
    snap = reg.snapshot()
    if not snap["n"]:
        snap, _, _ = reg.refresh()
    base = reg.load_template(reg.find(snap, base_id)) if base_id else None
    if base is not None and base.role != role:
        raise ValueError("基础模板的类型与所选类型不同")
    types = study_types or (list(base.study_types) if base else [vocab.ANY])
    tid = create.new_id({r["id"] for r in snap["records"]}, role)
    raw = create.build(tid=tid, title=title, role=role, study_types=types,
                       sections=create.plan_sections(base, sections, role), base=base)
    t = create.preview(raw)
    snap2, rec = reg.add_user(raw, f"界面新建：基于 {base.id}" if base else "界面新建：空白")
    return {"id": rec["id"], "version": rec["registry_version"], "status": rec["status"],
            "status_zh": STATUS_ZH[rec["status"]], "snapshot": snap2["n"], "review": list(t.review),
            "registry": str(reg.root)}


# ---------- projects ----------
def _projects(cfg):
    from ..project.session import context
    return context(cfg)


def project_rows(cfg) -> dict:
    """Same rows as `project list` (★ = default project)."""
    from ..project import model
    from ..project.views import LIB
    reg, views = _projects(cfg)
    snap = reg.snapshot()
    d = snap["prefs"].get("default_project")
    rows = []
    for r in reg.projects(snap):
        c = model.counts(reg.load(r))
        rows.append({"id": r["id"], "title": r["title"], "version": r["version"], "default": r["id"] == d,
                     "archived": r["status"] == "ARCHIVED", "counts": c, "folder": f"{LIB}/{r['folder']}"})
    return {"registry": str(reg.root), "views": str(views.root), "snapshot": snap["n"], "rows": rows}


def project_detail(cfg, pid: str) -> dict:
    """Same content as `project show`: modules → items with state and source, plus version history."""
    from ..project import model
    reg, _ = _projects(cfg)
    snap = reg.snapshot()
    rec = reg.latest(snap, pid)
    if rec is None:
        raise KeyError(pid)
    obj = reg.load(rec)
    modules = []
    for mid, mn, items in model.MODULES:
        rows = []
        for k, zh in items:
            vals = obj["items"].get(k) or []
            if not vals:
                rows.append({"key": k, "idx": -1, "label": zh, "state": "UNDECIDED", "state_zh": "未定", "value": "",
                             "source": ""})
            for vi, v in enumerate(vals):
                src = v["source"]
                rows.append({"key": k, "idx": vi, "label": zh, "state": v["state"], "state_zh": model.STATE_ZH[v["state"]], "value": v["value"],
                             "source": "·".join(x for x in (src.get("kind"), src.get("role"),
                                                            (src.get("file") or {}).get("name"), src.get("locator")) if x)})
        modules.append({"id": mid, "name": mn, "items": rows})
    hist = sorted([x for x in snap["records"] if x["id"] == rec["id"]], key=lambda x: x["version"])
    return {"id": rec["id"], "title": model.title_of(obj), "version": rec["version"], "sha": rec["sha256"][:16],
            "counts": model.counts(obj), "archived": rec["status"] == "ARCHIVED", "modules": modules,
            "history": [{"version": h["version"], "created": (h.get("created") or "")[:16].replace("T", " "),
                         "op": h.get("op") or "", "summary": h.get("summary") or ""} for h in hist]}


PROJECT_FIELDS = [("discipline", "学科"), ("core_question", "核心问题"), ("population", "目标人群"), ("design", "研究设计"),
                  ("primary_outcomes", "主要指标")]


def create_project(cfg, title: str, fields: dict[str, str] | None = None, make_default: bool | None = None) -> dict:
    """新建项目: the project registry's own create (version 1, 题目已确认), then — if any key field was filled — one
    more version with those items (用户输入, 已确认), then the 课题档案 views under the trial folder are regenerated.
    Same storage and rules as `project init` / `project set`."""
    from ..project import model
    title = (title or "").strip()
    if not 2 <= len(title) <= 120 or "\n" in title:
        raise ValueError("课题题目需要 2–120 个字，且只占一行")
    reg, views = _projects(cfg)
    snap, rec = reg.create(title, make_default=make_default)
    filled = {k: v.strip()[:model.MAX_VALUE] for k, v in (fields or {}).items() if k in model.KEYS and (v or "").strip()}
    if filled:
        obj = reg.load(rec)
        new = {**obj, "items": dict(obj["items"])}
        for k, v in filled.items():
            new["items"][k] = [model.value(v, "CONFIRMED", "用户输入", "用户确认")]
        snap, rec = reg.commit(new, "SET", "新建时填写：" + "、".join(model.KEYS[k][2] for k in filled))
    views.sync(reg, snap)
    return {"id": rec["id"], "title": rec["title"], "version": rec["version"], "default":
            snap["prefs"].get("default_project") == rec["id"], "folder": str(views.root / rec["folder"])}


def projects_location(cfg) -> tuple[str, bool]:
    _, views = _projects(cfg)
    return str(views.root), views.root.exists()


# ---------- G7-5: context-menu actions (all soft / versioned; the vault 模板库 folder is never written) ----------
def template_source(cfg, tid: str) -> str:
    reg = registry_for(cfg)
    return reg.find(reg.snapshot(), tid)["source"]


def can_edit_template(cfg, tid: str) -> tuple[bool, str]:
    """Only templates created in the app (source "user") can be edited / renamed / deleted."""
    src = template_source(cfg, tid)
    if src == "user":
        return True, ""
    if src == "builtin":
        return False, "内置模板（含冻结的主模板）不能修改或删除；可以「复制为新模板」后再改"
    return False, "这个模板来自 Obsidian 模板库文件夹（本程序只读）；可以「复制为新模板」，或在 Obsidian 里改原文件"


def copy_template(cfg, tid: str, title: str | None = None) -> dict:
    reg = registry_for(cfg)
    r = reg.find(reg.snapshot(), tid)
    return create_template(cfg, title=(title or f"{r['title']}（副本）"), role=r["role"], base_id=tid,
                           sections=base_outline(cfg, tid, r["role"]))


def _retire_template(cfg, tid: str) -> None:
    from ..errors import Stop
    reg = registry_for(cfg)
    r = reg.find(reg.snapshot(), tid)
    if r["status"] == "ACTIVE":
        reg.set_status(tid, r["registry_version"], "DISABLED", "disable")
    elif r["status"] in ("NEEDS_REVIEW", "CONFLICT"):
        reg.set_status(tid, r["registry_version"], "REJECTED", "reject")
    elif r["status"] not in ("DISABLED", "REJECTED"):
        raise Stop(f"当前状态「{STATUS_ZH[r['status']]}」不能删除")


def replace_template(cfg, old_id: str, new: dict) -> dict:
    """修改 / 重命名 = a new user template (already created from the edited outline) + the old one disabled
    (soft: it stays in the registry history and can be re-enabled with `litreader templates enable`)."""
    ok, why = can_edit_template(cfg, old_id)
    if not ok:
        raise ValueError(why)
    _retire_template(cfg, old_id)
    return new


def rename_template(cfg, tid: str, title: str) -> dict:
    ok, why = can_edit_template(cfg, tid)
    if not ok:
        raise ValueError(why)
    title = (title or "").strip()
    if not title:
        raise ValueError("请填写新名称")
    new = copy_template(cfg, tid, title)
    _retire_template(cfg, tid)
    return new


def delete_template(cfg, tid: str) -> None:
    """软删除：停用（登记与历史全部保留，可用 `litreader templates enable` 恢复）。"""
    ok, why = can_edit_template(cfg, tid)
    if not ok:
        raise ValueError(why)
    _retire_template(cfg, tid)


def rename_project(cfg, pid: str, title: str) -> dict:
    from ..project import model
    title = (title or "").strip()
    if not 2 <= len(title) <= 120 or "\n" in title:
        raise ValueError("课题题目需要 2–120 个字，且只占一行")
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    new = {**obj, "items": dict(obj["items"])}
    new["items"]["working_title"] = [model.value(title, "CONFIRMED", "用户输入", "用户确认")]
    snap, rec2 = reg.commit(new, "SET", f"重命名：{title}")
    views.sync(reg, snap)
    return {"id": rec2["id"], "title": rec2["title"], "version": rec2["version"]}


def delete_project(cfg, pid: str) -> dict:
    """软删除 = 归档（新版本，状态 ARCHIVED；所有版本与档案文件保留，可恢复）。"""
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    if obj["status"] == "ARCHIVED":
        return {"id": pid, "version": rec["version"], "archived": True}
    snap, rec2 = reg.commit({**obj, "status": "ARCHIVED"}, "ARCHIVE", "归档（界面删除）", set_default=False)
    views.sync(reg, snap)
    return {"id": pid, "version": rec2["version"], "archived": True}


def restore_project(cfg, pid: str) -> dict:
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    snap, rec2 = reg.commit({**obj, "status": "ACTIVE"}, "UNARCHIVE", "取消归档")
    views.sync(reg, snap)
    return {"id": pid, "version": rec2["version"]}


def copy_project(cfg, pid: str) -> dict:
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    snap, new = reg.create(f"{rec['title']}（副本）"[:120], make_default=False)
    o2 = reg.load(new)
    items = {k: v for k, v in obj["items"].items() if k != "working_title"}
    snap, new = reg.commit({**o2, "items": {**o2["items"], **items}}, "SET", f"复制自 {pid}")
    views.sync(reg, snap)
    return {"id": new["id"], "title": new["title"], "version": new["version"]}


# ---------- G7-8: inline edit + 批量填写 (all through the versioned project registry) ----------
def set_project_field(cfg, pid: str, key: str, text: str) -> dict:
    """Click-to-edit: the typed value becomes the item's CONFIRMED value (用户编辑); empty = 未定."""
    from ..project import session as ps
    reg, views = _projects(cfg)
    rec = reg.latest(reg.snapshot(), pid)
    r2 = ps.set_item(reg, views, rec, key, (text or "").strip() or None)
    return {"id": pid, "version": r2["version"]}


def bulk_fill(cfg, pid: str, text: str, *, chain, transport, env, runs=None) -> dict:
    """批量填写: pasted text -> the model splits it into project fields (same extractor + verbatim rules as a file
    import) -> stored as 待确认 (never 已确认); the user confirms each in the detail pane."""
    import hashlib
    from pathlib import Path as _P
    from ..project import importer, model
    text = (text or "").strip()
    if not text:
        raise ValueError("请先粘贴文字")
    paras = [p.strip() for p in text.replace("\r", "").split("\n") if p.strip()]
    src = importer.Source(path=_P("粘贴的文字"), name="粘贴的文字", sha256=hashlib.sha256(text.encode()).hexdigest(),
                          kind="txt", segments=[(f"第{i}段", p) for i, p in enumerate(paras, 1)])
    cands, notes = importer.extract(src, chain, transport, env, runs)
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    items = {k: list(v) for k, v in obj["items"].items()}
    added = 0
    for c in cands:
        k = c["key"]
        have = {" ".join(v["value"].split()) for v in items.get(k) or []}
        if " ".join(c["value"].split()) in have:
            continue
        items.setdefault(k, []).append(importer.strip_key(c))
        added += 1
    if not added:
        return {"id": pid, "added": 0, "notes": notes, "version": rec["version"]}
    snap, rec2 = reg.commit({**obj, "items": items}, "IMPORT", f"批量填写：{added} 条建议（待确认）")
    views.sync(reg, snap)
    return {"id": pid, "added": added, "notes": notes, "version": rec2["version"]}


def decide_project_value(cfg, pid: str, key: str, idx: int, accept: bool) -> dict:
    """确认 (PENDING -> CONFIRMED, confirmed_by user) or 忽略 (remove that pending value). New version either way."""
    from ..project import model
    reg, views = _projects(cfg)
    rec, obj = reg.current_obj(reg.snapshot(), pid)
    vals = [dict(v) for v in obj["items"].get(key) or []]
    if not 0 <= idx < len(vals) or vals[idx]["state"] != "PENDING":
        raise ValueError("这一条不是待确认状态")
    v = vals[idx]
    if accept:
        v["state"] = "CONFIRMED"
        v["source"] = {**v["source"], "confirmed_by": "user"}
        v["confirmed_at"] = v["updated_at"] = model.now_iso()
        from ..project.importer import SINGLE
        if key in SINGLE:      # single-valued item: the confirmed one replaces earlier confirmed values
            vals = [x for i, x in enumerate(vals) if i == idx or x["state"] != "CONFIRMED"]
            idx = vals.index(v)
        vals[idx] = v
    else:
        vals.pop(idx)
    snap, rec2 = reg.commit({**obj, "items": {**obj["items"], key: vals}}, "SET",
                            f"{model.KEYS[key][2]}：{'确认' if accept else '忽略'}一条建议")
    views.sync(reg, snap)
    return {"id": pid, "version": rec2["version"]}
