"""Interactive project flows (design §3, §4, §6): first-use question, title-only creation, import with the 5-item
screen or the diff screen, manual-edit sync, review, per-run resolution and freezing of ONE project snapshot.

Nothing here is sent to a model except (a) an imported file the user named, after its own estimate + y, and (b) the
frozen project summary for the Lens, listed in the run estimate (decision 3 = A)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..errors import Stop
from . import importer, model
from .registry import Ambiguous, ProjectRegistry
from .views import Views, archive_md, edits_vs, parse_archive

QUESTION = ("你目前研究的课题是什么？可以只说题目、给出开题报告/研究方案文件的路径（可以把文件拖进终端），"
            "或直接回车跳过（使用通用精读）。\n> ")
SKIP = {"", "跳过", "没有", "无", "暂无", "不用", "不需要", "skip", "s", "n", "no", "q", "不关联", "以后再说"}
NONE_RE = re.compile(r"(?:本次|这次|这一次)?(?:精读)?(?:不|无需|不用|不要)(?:关联|结合)(?:任何)?(?:课题|项目)[，,。；;\s]*")
USE_RE = re.compile(r"(?:请)?(?:用|从|以|按)[「《“\"]?(?P<p>[^」》”\"，,。]{1,40}?)[」》”\"]?(?:课题|项目)?的?(?:角度|视角)(?:来)?[，,\s]*")
# Lens estimate, calibrated on ONE real call (Zhong 2021 + example project: 3 537 in / 1 237 out, writer output
# estimate 8 767): in ≈ 0.25 × writer output + 0.7 × summary chars + 1 000; out ≈ 1 300. Circular on Zhong.
# recalibrated on DeepGaitLab (actual lens 3 066 in / 1 546 out with writer output 9 713)
LENS_IN_PER_WOUT, LENS_IN_FIXED, LENS_OUT = 0.19, 1000, 1550


@dataclass
class ProjectFrozen:
    rec: dict
    obj: dict
    summary: str
    registry_n: int
    temporary: bool
    reason: str

    @property
    def summary_sha256(self) -> str:
        return hashlib.sha256(self.summary.encode()).hexdigest()

    def view(self) -> dict:
        return {"project_id": self.rec["id"], "version": self.rec["version"], "title": self.rec["title"],
                "sha256": self.rec["sha256"], "obj": self.obj}

    def receipt(self) -> dict:
        return {"project_id": self.rec["id"], "project_version": self.rec["version"], "project_title": self.rec["title"],
                "project_snapshot_sha256": self.rec["sha256"], "summary_sha256": self.summary_sha256,
                "summary_chars": len(self.summary), "registry_snapshot": self.registry_n,
                "temporary": self.temporary, "reason": self.reason}

    def evidence(self) -> dict:
        return {**self.receipt(), "summary_sent_to_model": self.summary}


def context(cfg) -> tuple[ProjectRegistry, Views]:
    root = Path(cfg.data_dir) / "projects"
    return ProjectRegistry(root), Views(cfg.dry_run_root, root / "views.json")


def split_directive(command: str) -> tuple[tuple | None, str]:
    m = NONE_RE.search(command)
    if m:
        return ("none",), (command[:m.start()] + command[m.end():]).strip()
    m = USE_RE.search(command)
    if m and "模板" not in m.group("p"):
        return ("use", m.group("p").strip()), (command[:m.start()] + command[m.end():]).strip()
    return None, command


def _yes(ui, prompt) -> bool:
    while True:
        a = ui.ask(prompt).strip().lower()
        if a in ("y", "yes", "是", "好", "同意", "继续"):
            return True
        if a in ("n", "no", "否", "不", "q", "不同意"):
            return False
        ui.say("请输入 y 或 n")


def ensure_location(cfg, ui, views: Views) -> bool:
    """Decision 1 = A: the project library lives only under the dry-run folder; confirmed once at first creation."""
    if views.root.exists():
        return True
    return _yes(ui, f"将在 {views.root}/ 创建课题档案（只写这个文件夹；你的其他笔记不会被读取或改动）。同意？(y/n)：")


def looks_like_path(a: str) -> bool:
    s = a.strip().strip("'\"")
    return bool(re.search(r"\.(md|markdown|txt|docx|pptx|pdf|doc|ppt|wps)$", s, re.I)) or s.startswith(("/", "~/", "./"))


def is_title(a: str) -> bool:
    s = a.strip()
    return 4 <= len(s) <= 120 and not looks_like_path(s) and "\n" not in s and not s.lower().startswith(("http", "www."))


def create_title_only(cfg, ui, reg, views, title: str) -> dict | None:
    if not ensure_location(cfg, ui, views):
        ui.say("好的，未创建课题档案；本次使用通用精读")
        return None
    snap, rec = reg.create(title.strip())
    views.sync(reg, snap)
    c = model.counts(reg.load(rec))
    ui.say(f"✔ 已建立课题档案「{rec['title']}」（{rec['id']}）：题目已确认，其余 {c['UNDECIDED']} 项未定"
           f"{'；已设为默认课题' if snap['prefs'].get('default_project') == rec['id'] else ''}\n   位置：{views.root / rec['folder']}")
    return rec


def first_question(cfg, ui, reg, views, *, chain, transport, env, runs) -> dict | None:
    """T01/T02: asked once; Enter skips for good; a title builds a minimal archive; a path starts an import."""
    for attempt in (1, 2):
        from .. import events
        a = events.decide(ui, "project", QUESTION, [events.opt("", "跳过（通用精读）", "以后可随时新建课题")],
                          default="", allow_custom=True).strip()
        if a.lower() in SKIP:
            reg.set_prefs("FIRST_QUESTION", first_question="skipped")
            ui.say("好的，本次使用通用精读。以后可以随时说「新建课题：〈题目〉」或运行 litreader project init")
            return None
        if looks_like_path(a):
            rec = import_flow(cfg, ui, reg, views, a, chain=chain, transport=transport, env=env, runs=runs)
            if rec is None:
                ui.say("本次使用通用精读")
            return rec
        if is_title(a):
            return create_title_only(cfg, ui, reg, views, a)
        ui.say("没看懂：请直接输入课题题目，或文件路径，或回车跳过")
    ui.say("本次使用通用精读，下次精读时再问")
    return None


# ---------------------------------------------------------------- import
def import_estimate(src: importer.Source) -> tuple[int, int]:
    chunks = max(1, -(-sum(len(t) for _, t in src.segments) // importer.CHUNK_CHARS))
    return int(src.chars * 0.6) + 2000 * chunks, 3000 * chunks


def import_flow(cfg, ui, reg, views, path, *, project: dict | None = None, chain, transport, env, runs=None):
    src = importer.read_source(path)
    ui.say(f"读取《{src.name}》（本地读取，未上传）：{src.extent}，约 {src.chars:,} 字；"
           + (f"图片 {src.images} 张（图片中的文字未读取）" if src.images else "无图片"))
    for h in src.hints:
        ui.say(f"  版本提示：{h}（只作参考，不据此判断新旧）")
    if src.flags:
        ui.say("  ⚠ 文件中有类似指令/网址的文字（" + "、".join(c for c, _ in src.flags) + "）：只当作资料保存，不会执行")
    tin, tout = import_estimate(src)
    label = cfg.slot_label(chain[0].id) if chain else "?"
    if not _yes(ui, f"将把《{src.name}》全文约 {src.chars:,} 字发送给 {label}（云端）提取课题信息；"
                    f"输入 约 {tin:,}，输出 约 {tout:,} tokens（估算）。同意发送？(y/n)："):
        ui.say("已取消导入：文件没有发送给任何模型")
        return None
    if not ensure_location(cfg, ui, views):
        ui.say("未创建课题档案")
        return None
    ui.say("… 提取课题信息")
    cands, notes = importer.extract(src, chain, transport, env, runs)
    for n in notes:
        ui.say(f"  文件提示：{n}")
    snap = reg.snapshot()
    if project is None:
        t = next((c["value"] for c in cands if c["key"] in ("formal_title", "working_title")), None) or Path(src.name).stem
        folder = reg._folder(snap, t)
        draft = views.draft(folder, draft_md(src, cands, notes))
        ui.say(f"  草稿：{draft}")
        return _confirm_new(ui, reg, views, src, cands, folder)
    rec, obj = reg.current_obj(snap, project["id"])
    draft = views.draft(rec["folder"], draft_md(src, cands, notes))
    ui.say(f"  草稿：{draft}")
    return _update(ui, reg, views, src, cands, rec, obj)


def draft_md(src, cands, notes) -> str:
    L = [f"# 导入草稿：{src.name}", "", "> [!warning] 这是从文件提取的**候选**（全部为待确认），确认前不是正式课题方案。",
         f"> 文件 SHA-256：`{src.sha256}`；{src.extent}；约 {src.chars:,} 字；图片 {src.images} 张（未读取）。", ""]
    L += [f"- 提示：{n}" for n in notes] + ([""] if notes else [])
    for mid, mname, items in model.MODULES:
        L += [f"## {mid} {mname}", ""]
        for k, zh in items:
            for c in [c for c in cands if c["key"] == k]:
                q = f"　原文（{c['source'].get('locator')}）：「{c['source']['quote']}」" if c["source"].get("quote") else \
                    (f"（位置 {c['source'].get('locator')}）" if c["source"].get("locator") else "")
                L.append(f"- **{zh}**〔待确认·{c['source']['kind']}·{c['source']['role']}〕：{c['value']}{q}"
                         + (f" ⚠ {c['conflict']}" if c.get("conflict") else "") + (f"（{c['note']}）" if c.get("note") else ""))
        L.append("")
    return "\n".join(L)


def _group_cands(cands, keys):
    return [c for c in cands if c["key"] in keys]


def _confirm_new(ui, reg, views, src, cands, folder) -> dict | None:
    """Decision 5 = A: one screen with the five key items; the rest stays PENDING."""
    nexp = sum(1 for c in cands if c["source"]["kind"] == "文件明确写出")
    ui.say(f"从《{src.name}》（{src.extent}）提取到 {len(cands)} 条候选（明确写出 {nexp}，AI 归纳 {len(cands) - nexp}；"
           f"文件内冲突 {sum(1 for c in cands if c.get('conflict'))}）")
    choice: dict[str, dict] = {}   # gid -> {"cands": [...confirmed], "typed": str|None, "undecided": bool}
    groups = []
    for gid, zh, keys in model.KEY5:
        g = _group_cands(cands, keys)
        if gid == "title":
            g = g[:2] if any(c.get("conflict") for c in g) else g[:1]
        groups.append((gid, zh, keys, g))
    while True:
        ui.say("请确认以下关键信息（其余条目保存为“待确认”，可稍后用 litreader project review 逐条处理）：")
        for i, (gid, zh, keys, g) in enumerate(groups, 1):
            ch = choice.get(gid)
            if ch and ch.get("typed"):
                ui.say(f"  {i}. {zh}：{ch['typed']}（你输入）")
            elif ch and ch.get("undecided"):
                ui.say(f"  {i}. {zh}：未定（你标记）")
            elif ch and ch.get("cands"):
                ui.say(f"  {i}. {zh}：{ch['cands'][0]['value']}（你选择）")
            elif not g:
                ui.say(f"  {i}. {zh}：文件中未找到（保持未定）")
            elif any(c.get("conflict") for c in g) and len(g) > 1:
                ui.say(f"  {i}. {zh}：⚠ 文件内冲突：" + " / ".join(f"{c['source'].get('locator') or '?'}「{c['value']}」" for c in g))
            else:
                c = g[0]
                ui.say(f"  {i}. {zh}：{c['value']}（{c['source'].get('locator') or '位置不明'}，{c['source']['kind']}）"
                       + (" ⚠ " + c["conflict"] if c.get("conflict") else ""))
        a = ui.ask("回车 = 确认以上无冲突的项；输入序号 = 修改该项 / 标为未定；s = 先存草稿不确认；q = 放弃导入：").strip().lower()
        if a in ("q", "取消"):
            ui.say("已放弃导入；草稿保留，未形成课题版本")
            return None
        if a == "s":
            ui.say("草稿已保存，尚未形成课题版本（确认前不是正式方案）")
            return None
        if a.isdigit() and 1 <= int(a) <= len(groups):
            gid, zh, keys, g = groups[int(a) - 1]
            for j, c in enumerate(g, 1):
                ui.say(f"    {j}. 「{c['value']}」")
            b = ui.ask(f"    {zh}：输入候选序号选用 / 直接输入新内容 / u = 标为未定 / 回车 = 不变：").strip()
            if b.lower() == "u":
                choice[gid] = {"undecided": True}
            elif b.isdigit() and 1 <= int(b) <= len(g):
                choice[gid] = {"cands": [g[int(b) - 1]]}
            elif b:
                choice[gid] = {"typed": b}
            continue
        if a == "":
            break
        ui.say("无效输入")
    obj = model.blank("", folder)
    snap = reg.snapshot()
    pid = model.new_id()
    while reg.latest(snap, pid):
        pid = model.new_id()
    obj["project_id"] = pid
    confirmed_ids, dropped_keys = set(), set()
    for gid, zh, keys, g in groups:
        ch = choice.get(gid) or {}
        if ch.get("undecided"):
            dropped_keys |= set(keys)
        elif ch.get("typed"):
            k = keys[0] if gid != "title" else "working_title"
            obj["items"].setdefault(k, []).append(model.value(ch["typed"], "CONFIRMED", "用户输入", "用户确认"))
            dropped_keys.add(k)
        elif ch.get("cands"):
            confirmed_ids.add(id(ch["cands"][0]))
        elif g and not (any(c.get("conflict") for c in g) and len(g) > 1) and not g[0].get("conflict"):
            confirmed_ids.add(id(g[0]))
    for c in cands:
        if c["key"] in dropped_keys:
            continue
        v = importer.strip_key(c)
        if id(c) in confirmed_ids:
            v = {**v, "state": "CONFIRMED", "confirmed_at": model.now_iso(),
                 "source": {**v["source"], "confirmed_by": "user"}}
        obj["items"].setdefault(c["key"], []).append(v)
    if not any(obj["items"].get(k) for k in ("formal_title", "working_title")):
        t = ui.ask("文件中没有确定的课题题目，请输入题目（回车 = 用文件名）：").strip() or Path(src.name).stem
        obj["items"]["working_title"] = [model.value(t, "CONFIRMED", "用户输入", "用户确认")]
    make_default = not snap["prefs"].get("default_project")
    snap2, rec = reg.commit(obj, "IMPORT", f"从《{src.name}》新建（{src.sha256[:12]}）", set_default=make_default,
                            prefs={"first_question": "answered"})
    views.sync(reg, snap2)
    c = model.counts(reg.load(rec))
    ui.say(f"✔ 已形成课题档案 v{rec['version']}「{rec['title']}」：已确认 {c['CONFIRMED']}，待确认 {c['PENDING']}，未定 {c['UNDECIDED']}"
           f"{'；已设为默认课题' if make_default else ''}\n   位置：{views.root / rec['folder']}")
    return rec


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _update(ui, reg, views, src, cands, rec, obj) -> dict | None:
    """Spec §6.3.5/§6.4: show differences item by item; never adopt the newer file silently."""
    prior = {v["source"]["file"]["sha256"]: v["source"]["file"]["name"] for vals in obj["items"].values() for v in vals
             if v["source"].get("file")}
    if src.sha256 in prior:
        ui.say("这份文件之前已经导入过（内容完全相同），无需再导入")
        return None
    relation = "current"
    if prior:
        ui.say(f"这份《{src.name}》与之前导入的《{'》《'.join(sorted(set(prior.values())))}》是什么关系？")
        while True:
            a = ui.ask("  1 = 这是我现在的方案（与当前档案逐条比对） / 2 = 只是补充材料（只补充目前“未定”的条目） / 3 = 说不清（先存草稿，不形成新版本）：").strip()
            if a in ("1", "2", "3"):
                break
        if a == "3":
            ui.say("好的：草稿已保存，课题档案保持 v%d 不变。弄清楚哪份是现行方案后再导入" % rec["version"])
            return None
        relation = "current" if a == "1" else "supplement"
    adds, diffs = [], []
    for k in model.KEYS:
        new = [c for c in cands if c["key"] == k]
        if not new:
            continue
        cur = [v for v in obj["items"].get(k) or [] if v["state"] != "SUGGESTION"]
        if not cur:
            adds += new
        elif relation == "current" and {_norm(v["value"]) for v in cur} != {_norm(c["value"]) for c in new}:
            diffs.append((k, cur, new))
    if not adds and not diffs:
        ui.say("新文件与当前档案没有差异，课题档案保持不变")
        return None
    decisions: dict[str, str] = {}
    core = [d for d in diffs if d[0] in model.CORE]
    other = [d for d in diffs if d[0] not in model.CORE]
    if diffs:
        ui.say(f"与当前档案（v{rec['version']}）相比，新文件有 {len(diffs)} 处不同：")
    for k, cur, new in core:
        ui.say(f"  [影响研究方向] {model.KEYS[k][0]} {model.KEYS[k][2]}")
        ui.say("     当前（v%d）：%s" % (rec["version"], "；".join(f"{v['value']}〔{model.STATE_ZH[v['state']]}〕" for v in cur)))
        ui.say(f"     新文件（{src.name}）：" + "；".join(f"{c['value']}（{c['source'].get('locator') or '?'}，{c['source']['kind']}）" for c in new))
        while True:
            a = ui.ask("     1 保留当前 / 2 改用新文件 / 3 标为未定：").strip()
            if a in ("1", "2", "3"):
                decisions[k] = a
                break
    if other:
        for i, (k, cur, new) in enumerate(other, 1):
            ui.say(f"  {i}. {model.KEYS[k][2]}  当前：{'；'.join(v['value'] for v in cur)}  新文件：{'；'.join(c['value'] for c in new)}")
        a = ui.ask(f"其余 {len(other)} 处（非核心）：回车 = 全部改用新文件 / n = 全部保留当前 / 序号（逗号分隔）= 只改用这些：").strip().lower()
        pick = set(range(1, len(other) + 1)) if a == "" else (set() if a == "n" else
                                                               {int(x) for x in re.split(r"[,，\s]+", a) if x.isdigit()})
        for i, (k, _, _) in enumerate(other, 1):
            decisions[k] = "2" if i in pick else "1"
    new_obj = {**obj, "items": {k: list(v) for k, v in obj["items"].items()}}
    changed = []
    for k, cur, new in diffs:
        d = decisions.get(k, "1")
        if d == "2":
            new_obj["items"][k] = [{**importer.strip_key(c), "state": "CONFIRMED", "confirmed_at": model.now_iso(),
                                    "source": {**c["source"], "confirmed_by": "user"}} for c in new]
            changed.append(f"{model.KEYS[k][2]}改用新文件")
        elif d == "3":
            new_obj["items"][k] = []
            changed.append(f"{model.KEYS[k][2]}标为未定")
    for c in adds:
        new_obj["items"].setdefault(c["key"], []).append(importer.strip_key(c))
    if adds:
        changed.append(f"新增待确认 {len(adds)} 条")
    if not changed:
        ui.say("你选择了全部保留当前内容；课题档案保持不变")
        return None
    snap2, rec2 = reg.commit(new_obj, "IMPORT", f"《{src.name}》（{src.sha256[:12]}）：" + "；".join(changed))
    views.sync(reg, snap2)
    ui.say(f"✔ 课题档案更新为 v{rec2['version']}（旧版本保留在 历史版本/）：" + "；".join(changed))
    return rec2


# ---------------------------------------------------------------- manual edits / review / set
def sync_manual_edits(ui, reg, views, snap) -> dict:
    for rel in views.manual_edits(reg, snap):
        folder = rel.split("/")[1]
        rec = next(r for r in reg.projects(snap) if r["folder"] == folder)
        obj = reg.load(rec)
        text = (views.dry_root / rel).read_text("utf-8", errors="replace")
        parsed, unknown = parse_archive(text)
        _, ours = parse_archive(archive_md(obj, default=snap["prefs"].get("default_project") == rec["id"]))
        unknown = [u for u in unknown if u not in ours]
        diffs = edits_vs(obj, parsed)
        if not diffs and not unknown:
            views.save_edited_copy(rel, datetime.now().strftime("%Y%m%dT%H%M%S"))
            continue
        ui.say(f"发现你在 Obsidian 中修改了「{rel}」：")
        for d in diffs:
            old = "；".join(f"{v}〔{model.STATE_ZH[s]}〕" for v, s in d["old"]) or "未定"
            new = "；".join(f"{v}〔{model.STATE_ZH[s]}〕" for v, s in d["new"]) or "未定"
            ui.say(f"  {model.KEYS[d['key']][2]}：{old} → {new}")
        if unknown:
            ui.say("  以下改动未能识别，未采用（请用固定格式的条目行，或 litreader project set）：")
            for u in unknown[:5]:
                ui.say(f"    {u[:80]}")
        if diffs and _yes(ui, "采用这些修改并形成新版本？(y/n)："):
            new_obj = {**obj, "items": {k: list(v) for k, v in obj["items"].items()}}
            for d in diffs:
                keep_sugg = [v for v in obj["items"].get(d["key"]) or [] if v["state"] == "SUGGESTION"]
                old_map = {(v["value"], v["state"]): v for v in obj["items"].get(d["key"]) or []}
                new_obj["items"][d["key"]] = keep_sugg + [old_map.get((v, s)) or model.value(v, s, "用户编辑", "用户确认")
                                                          for v, s in d["new"]]
            snap, rec2 = reg.commit(new_obj, "EDIT", "你在 Obsidian 中的手动修改：" + "、".join(model.KEYS[d["key"]][2] for d in diffs))
            kept = views.save_edited_copy(rel, datetime.now().strftime("%Y%m%dT%H%M%S"))
            views.sync(reg, snap)
            ui.say(f"✔ 已形成 v{rec2['version']}；你改过的原文件已存为 {kept}")
        else:
            ui.say(f"已保留你的文件不变；本次使用已确认的 v{rec['version']}（可运行 litreader project sync 再处理）")
    return snap


def review(ui, reg, views, rec) -> dict | None:
    obj = reg.load(rec)
    new_obj = {**obj, "items": {k: [dict(v) for v in vals] for k, vals in obj["items"].items()}}
    n = 0
    for k, vals in new_obj["items"].items():
        out = []
        for v in vals:
            if v["state"] != "PENDING":
                out.append(v); continue
            q = f"　原文（{v['source'].get('locator')}）：「{v['source']['quote']}」" if v["source"].get("quote") else ""
            ui.say(f"{model.KEYS[k][2]}：{v['value']}（{v['source']['kind']}）{q}" + (f" ⚠ {v['conflict']}" if v.get("conflict") else ""))
            a = ui.ask("  1 确认 / 2 修改 / 3 标为未定（删除此候选） / 回车 跳过 / q 结束：").strip().lower()
            if a == "q":
                out.append(v); out += vals[vals.index(v) + 1:]; break
            if a == "1":
                v = {**v, "state": "CONFIRMED", "confirmed_at": model.now_iso(), "source": {**v["source"], "confirmed_by": "user"}}
                n += 1
            elif a == "2":
                t = ui.ask("  新内容：").strip()
                if t:
                    v = model.value(t, "CONFIRMED", "用户输入", "用户确认"); n += 1
            elif a == "3":
                n += 1; continue
            out.append(v)
        new_obj["items"][k] = out
    if not n:
        ui.say("没有改动")
        return None
    snap, rec2 = reg.commit(new_obj, "REVIEW", f"逐条处理待确认 {n} 条")
    views.sync(reg, snap)
    ui.say(f"✔ 已形成 v{rec2['version']}")
    return rec2


TITLE_ALIASES = {"题目", "课题题目", "题名", "标题", "名称", "课题名称", "title"}


def set_item(reg, views, rec, label: str, text: str | None) -> dict:
    obj0 = reg.load(rec)
    if label.strip().lower() in TITLE_ALIASES:
        # "the title" = whichever item the archive currently shows as its title (正式题目 if set, else 工作题目)
        label = "formal_title" if any(v["state"] == "CONFIRMED" for v in obj0["items"].get("formal_title") or []) else "working_title"
    k = model.ZH2KEY.get(label.strip()) or (label.strip() if label.strip() in model.KEYS else None)
    if not k:
        alts = [zh for zh in model.ZH2KEY if label.strip() in zh]
        if len(alts) == 1:
            k = model.ZH2KEY[alts[0]]
        else:
            raise Stop(f"没有条目「{label}」；可用条目：{'、'.join(model.ZH2KEY)}")
    obj = reg.load(rec)
    new_obj = {**obj, "items": dict(obj["items"])}
    keep = [v for v in obj["items"].get(k) or [] if v["state"] == "SUGGESTION"]
    new_obj["items"][k] = keep + ([model.value(text, "CONFIRMED", "用户输入", "用户确认")] if text else [])
    snap, rec2 = reg.commit(new_obj, "SET", f"{model.KEYS[k][2]}：{'改为 ' + text if text else '标为未定'}")
    views.sync(reg, snap)
    return rec2


# ---------------------------------------------------------------- per-run resolution
def resolve(cfg, ui, directive, *, chain, transport, env, runs=None) -> ProjectFrozen | None:
    reg, views = context(cfg)
    snap = reg.snapshot()
    snap = sync_manual_edits(ui, reg, views, snap)
    if directive and directive[0] == "none":
        ui.say("课题：本次不关联课题（默认课题不变）")
        return None
    temporary, reason = False, "默认课题"
    if directive and directive[0] == "use":
        try:
            rec = reg.find(snap, directive[1])
        except Ambiguous as e:
            rec = _pick(ui, e.matches, f"「{directive[1]}」对应多个课题，本次用哪个？")
        if rec is None:
            return None
        temporary, reason = rec["id"] != snap["prefs"].get("default_project"), "你本次指定"
    else:
        d = snap["prefs"].get("default_project")
        drec = reg.latest(snap, d) if d else None
        active = reg.projects(snap, include_archived=False)
        if drec and drec["status"] == "ACTIVE":
            rec = drec
        elif active:
            rec = _pick(ui, active, "没有默认课题。本次关联哪个课题？", allow_default=True, reg=reg)
            if rec is None:
                return None
            reason = "你本次选择"
        elif snap["prefs"].get("first_question") is None:
            rec = first_question(cfg, ui, reg, views, chain=chain, transport=transport, env=env, runs=runs)
            if rec is None:
                return None
            reason = "刚建立的课题"
        else:
            return None
    snap = reg.snapshot()
    rec = reg.latest(snap, rec["id"])
    obj = reg.load(rec)
    fr = ProjectFrozen(rec, obj, model.summary(obj), snap["n"], temporary, reason)
    c = model.counts(obj)
    ui.say(f"课题：《{rec['title']}》v{rec['version']}（{reason}{'，只用于本次，默认不变' if temporary else ''}；"
           f"已确认 {c['CONFIRMED']} 项，未定 {c['UNDECIDED']} 项）")
    return fr


def _pick(ui, recs, prompt, *, allow_default=False, reg=None):
    ui.say(prompt)
    for i, r in enumerate(recs, 1):
        ui.say(f"  {i}. {r['title']}（{r['id']}）")
    ui.say("  0. 不关联（通用精读）")
    while True:
        a = ui.ask("输入序号" + ("（加 * 同时设为默认，如 1*）" if allow_default else "") + "：").strip()
        star = a.endswith("*")
        a = a.rstrip("*").strip()
        if a == "0":
            return None
        if a.isdigit() and 1 <= int(a) <= len(recs):
            r = recs[int(a) - 1]
            if star and allow_default and reg is not None:
                reg.set_prefs("SET_DEFAULT", default_project=r["id"])
                ui.say(f"  已把《{r['title']}》设为默认课题")
            return r
        ui.say("无效输入")


def lens_estimate(fr: ProjectFrozen | None, writer_out: int) -> dict | None:
    if not fr:
        return None
    return {"in": int(writer_out * LENS_IN_PER_WOUT + len(fr.summary) * 0.7 + LENS_IN_FIXED), "out": LENS_OUT,
            "summary_chars": len(fr.summary), "confirmed": model.counts(fr.obj)["CONFIRMED"]}
