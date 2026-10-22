"""`litreader project …` and the natural-language project commands (Stage 7; PROJECT_LIBRARY §10).
Writes only: <app data>/projects/ and <vault>/<output_dir>/科研项目库/ (decision 1 = A)."""
from __future__ import annotations

import re

from .errors import Stop
from .project import model
from .project import session as ps
from .project.registry import Ambiguous, rebuild
from .project.views import LIB, blocks_in

ACTIONS = ["init", "import", "list", "show", "switch", "review", "set", "undecide", "diff", "revert", "sync",
           "archive", "unarchive", "summary", "recover"]

NL = [
    ("create", re.compile(r"^\s*(?:请)?新建(?:一个)?课题\s*[:：]\s*(?P<t>.+?)\s*$")),
    ("import_new", re.compile(r"^\s*我的课题是(?P<t>.+?)[，,。]\s*(?:开题报告|研究方案|方案)(?:在|是)\s*[:：]?\s*(?P<p>\S.*?)\s*$")),
    ("import_update", re.compile(r"更新(?:我的)?课题档案.*?(?:新版)?(?:方案|开题报告|文件)\s*[:：]?\s*(?P<p>(?:/|~|\./)\S.*?)\s*$")),
    ("switch", re.compile(r"^\s*(?:请)?(?:把|将)?默认课题(?:切换|改|设)(?:为|成)\s*[「《“]?(?P<p>.+?)[」》”]?\s*$")),
    ("set", re.compile(r"^\s*(?:请)?(?:把|将)(?:我的)?(?:默认)?课题(?:档案)?(?:的|中的)?(?P<k>[^，,。]{2,12}?)(?:改为|改成|设为|更新为)\s*(?P<v>.+?)\s*$")),
    ("sync", re.compile(r"^\s*(?:请)?刷新(?:一下)?课题档案\s*$")),
]


def nl_match(text: str):
    for name, rx in NL:
        m = rx.search(text or "")
        if m:
            return name, m
    return None


def _ctx(cfg):
    return ps.context(cfg)


def _default(reg, snap):
    d = snap["prefs"].get("default_project")
    r = reg.latest(snap, d) if d else None
    if not r:
        raise Stop("还没有默认课题（litreader project list 查看；litreader project switch 〈课题〉设置）")
    return r


def _target(reg, snap, text):
    if not text:
        return _default(reg, snap)
    try:
        return reg.find(snap, text, include_archived=True)
    except Ambiguous as e:
        raise Stop(f"{e}：" + "、".join(f"{r['title']}（{r['id']}）" for r in e.matches) + "；请写更完整的题目或 ID")


def run_nl(cfg, text: str, ui, transport=None, env=None) -> int:
    name, m = nl_match(text)
    reg, views = _ctx(cfg)
    snap = ps.sync_manual_edits(ui, reg, views, reg.snapshot())
    chain = cfg.llm.chain("extract") if cfg.llm else []
    tx = transport or _tx()
    if name == "create":
        ps.create_title_only(cfg, ui, reg, views, m.group("t"))
    elif name == "import_new":
        rec = ps.import_flow(cfg, ui, reg, views, m.group("p"), chain=chain, transport=tx, env=env)
        if rec is None:
            ui.say("未从文件建立课题；如只想用题目建立，可说：新建课题：" + m.group("t").strip())
    elif name == "import_update":
        r = _default(reg, snap)
        ps.import_flow(cfg, ui, reg, views, m.group("p"), project=r, chain=chain, transport=tx, env=env)
    elif name == "switch":
        r = _target(reg, snap, m.group("p"))
        reg.set_prefs("SET_DEFAULT", default_project=r["id"])
        views.sync(reg, reg.snapshot())
        ui.say(f"✔ 默认课题：《{r['title']}》（{r['id']}）；其他课题档案未改动")
    elif name == "set":
        r = _default(reg, snap)
        v = m.group("v").strip()
        und = v in ("未定", "待定", "不确定")
        r2 = ps.set_item(reg, views, r, m.group("k"), None if und else v)
        ui.say(f"✔ 《{r2['title']}》v{r2['version']}：{m.group('k')}{'标为未定' if und else '改为「' + v + '」（来源：你的原话，已确认）'}")
    elif name == "sync":
        n = views.sync(reg, reg.snapshot())
        ui.say("✔ 课题档案已检查" + ("；" + "；".join(n) if n else "，没有未处理的修改"))
    return 0


def _tx():
    from .llm.client import urllib_transport
    return urllib_transport


def cmd_project(a, ui=None, transport=None) -> int:
    from . import appconfig
    from .cli import ConsoleUI
    ui = ui or ConsoleUI()
    cfg = appconfig.load(a.config)
    reg, views = _ctx(cfg)
    act = a.action
    if act == "recover":
        if a.from_vault:
            vs = []
            for p in sorted(views.root.glob("*/历史版本/v*.md")) if views.root.is_dir() else []:
                vs += blocks_in(p.read_text("utf-8"))
            snap = rebuild(reg, vs)
            ui.say(f"✔ 已从 {views.root} 的历史版本重建课题登记：{len({r['id'] for r in snap['records']})} 个课题，"
                   f"{len(snap['records'])} 个版本（逐个校验 SHA 与版本链）")
            return 0
        rep = reg.recover(apply=False, to=a.to)
        ui.say(f"课题登记：{reg.root}；锁：{rep['lock']['state']}；CURRENT：{rep.get('current')}")
        for p in rep["problems"]:
            ui.say(f"  问题：{p}")
        for r in rep["residue"]:
            ui.say(f"  残留（将移入 quarantine/，不删除）：{r}")
        if rep.get("hint"):
            ui.say(f"  {rep['hint']}")
        if not rep["ok"]:
            return 1
        if not rep["residue"] and a.to is None:
            ui.say("✔ 无需恢复")
            return 0
        if a.yes or ps._yes(ui, "按上面的计划执行？(y/n)："):
            rep = reg.recover(apply=True, to=a.to)
            ui.say("✔ " + "；".join(rep["actions"]))
        return 0
    snap = ps.sync_manual_edits(ui, reg, views, reg.snapshot())
    chain = cfg.llm.chain("extract") if cfg.llm else []
    tx = transport or _tx()
    if act == "init":
        if a.title:
            ps.create_title_only(cfg, ui, reg, views, a.title)
        else:
            ps.first_question(cfg, ui, reg, views, chain=chain, transport=tx, env=None, runs=None)
        return 0
    if act == "import":
        if not a.target:
            raise Stop("用法：litreader project import 文件路径 [--project 课题]")
        proj = _target(reg, snap, a.project) if a.project else None
        ps.import_flow(cfg, ui, reg, views, a.target, project=proj, chain=chain, transport=tx, env=None)
        return 0
    if act == "list":
        d = snap["prefs"].get("default_project")
        ui.say(f"课题登记：{reg.root}（快照 #{snap['n']}）；可读档案：{views.root}")
        if not snap["records"]:
            ui.say("  （还没有课题）→ litreader project init 或说：新建课题：〈题目〉")
        for r in reg.projects(snap):
            c = model.counts(reg.load(r))
            ui.say(f"  {'★' if r['id'] == d else ' '} {r['title']}  {r['id']}  v{r['version']}  "
                   f"{'已归档' if r['status'] == 'ARCHIVED' else '进行中'}  已确认 {c['CONFIRMED']}·待确认 {c['PENDING']}·未定 {c['UNDECIDED']}"
                   f"  文件夹 {LIB}/{r['folder']}")
        return 0
    if act in ("show", "summary", "diff", "revert"):
        tgt, ver = (a.target or ""), None
        m = re.fullmatch(r"(.*?)@v?(\d+)", tgt)
        if m:
            tgt, ver = m.group(1), int(m.group(2))
        r = _target(reg, snap, tgt)
        if act == "summary":
            ui.say(model.summary(reg.load(r if ver is None else reg.version_rec(snap, r["id"], ver))))
            return 0
        if act == "diff":
            v1, v2 = a.v1, a.v2
            if v1 is None or v2 is None:
                raise Stop("用法：litreader project diff 〈课题〉 --v1 1 --v2 2")
            o1, o2 = reg.load(reg.version_rec(snap, r["id"], v1)), reg.load(reg.version_rec(snap, r["id"], v2))
            n = 0
            for k, (mid, mn, zh) in model.KEYS.items():
                x1 = [(v["value"], v["state"]) for v in o1["items"].get(k) or []]
                x2 = [(v["value"], v["state"]) for v in o2["items"].get(k) or []]
                if x1 != x2:
                    n += 1
                    ui.say(f"  {mid} {zh}：v{v1} {'；'.join(f'{a}〔{model.STATE_ZH[b]}〕' for a, b in x1) or '未定'}"
                           f" → v{v2} {'；'.join(f'{a}〔{model.STATE_ZH[b]}〕' for a, b in x2) or '未定'}")
            ui.say(f"共 {n} 处不同")
            return 0
        if act == "revert":
            if ver is None:
                raise Stop("用法：litreader project revert 〈课题〉@版本（以旧版本内容建立新版本，历史不删）")
            old = reg.load(reg.version_rec(snap, r["id"], ver))
            s2, r2 = reg.commit({**old, "status": r["status"]}, "REVERT", f"以 v{ver} 的内容建立新版本")
            views.sync(reg, s2)
            ui.say(f"✔ 已建立 v{r2['version']}（内容同 v{ver}；之前的版本全部保留）")
            return 0
        rec = r if ver is None else reg.version_rec(snap, r["id"], ver)
        obj = reg.load(rec)
        c = model.counts(obj)
        ui.say(f"《{model.title_of(obj)}》 {rec['id']} v{rec['version']}  SHA {rec['sha256'][:16]}…  "
               f"已确认 {c['CONFIRMED']}·待确认 {c['PENDING']}·未定 {c['UNDECIDED']}·建议 {c['SUGGESTION']}")
        for mid, mn, items in model.MODULES:
            ui.say(f"  {mid} {mn}")
            for k, zh in items:
                vals = obj["items"].get(k) or []
                if not vals:
                    ui.say(f"    {zh}：未定")
                for v in vals:
                    loc = v["source"].get("locator")
                    ui.say(f"    {zh}〔{model.STATE_ZH[v['state']]}〕：{v['value']}（{v['source']['kind']}·{v['source']['role']}"
                           f"{'·' + v['source']['file']['name'] if v['source'].get('file') else ''}{'·' + loc if loc else ''}）")
        ui.say("  版本历史：")
        for h in sorted([x for x in snap["records"] if x["id"] == rec["id"]], key=lambda x: x["version"]):
            ui.say(f"    v{h['version']}  {h['created']}  {h.get('op')}  {h.get('summary')}")
        return 0
    if act == "switch":
        r = _target(reg, snap, a.target)
        reg.set_prefs("SET_DEFAULT", default_project=r["id"])
        views.sync(reg, reg.snapshot())
        ui.say(f"✔ 默认课题：《{r['title']}》（{r['id']}）")
        return 0
    if act == "review":
        ps.review(ui, reg, views, _target(reg, snap, a.target))
        return 0
    if act in ("set", "undecide"):
        r = _target(reg, snap, a.project)
        if not a.target:
            raise Stop("用法：litreader project set 条目 \"内容\"（如：project set 主要指标 \"步速\"）")
        r2 = ps.set_item(reg, views, r, a.target, a.value if act == "set" else None)
        ui.say(f"✔ 《{r2['title']}》v{r2['version']}")
        return 0
    if act == "sync":
        n = views.sync(reg, reg.snapshot())
        ui.say("✔ 已检查" + ("；" + "；".join(n) if n else ""))
        return 0
    if act in ("archive", "unarchive"):
        r = _target(reg, snap, a.target)
        obj = reg.load(r)
        st = "ARCHIVED" if act == "archive" else "ACTIVE"
        if obj["status"] == st:
            ui.say("状态未变")
            return 0
        s2, r2 = reg.commit({**obj, "status": st}, act.upper(), "归档" if st == "ARCHIVED" else "取消归档",
                            set_default=False if st == "ARCHIVED" else None)
        views.sync(reg, s2)
        ui.say(f"✔ 《{r2['title']}》{'已归档（不再作为默认或本次课题；文件全部保留）' if st == 'ARCHIVED' else '已恢复'}")
        return 0
    raise Stop(f"未知操作 {act}")
