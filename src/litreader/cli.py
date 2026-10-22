"""`litreader` command line (Chinese messages; beginner-friendly).

  litreader "精读zotero中的<题名或关键词>，并将精读笔记存入obsidian中"   一句话指令（一次一篇）
  litreader                                   交互模式：逐条输入指令
  litreader gui                               图形界面（PySide6；pip install -e ".[gui]"）
  litreader doctor                            环境自检（不写文件、不上传、不调用收费接口）
  litreader models list | set 角色 [序号] | test [角色] [序号] | remove 角色 序号 | migrate
  litreader key set 名称 | key test           钥匙串
  litreader find "题名"                        在 Zotero 中查找（只读）
  litreader templates refresh|list|show|lint|export|approve|reject|disable|enable|prefer|pin|unpin|rollback|recover|draft
  litreader inspect-parse [任务]                 已缓存解析结果的每页块类型统计（排查“抽取完整度”用）
  litreader inspect-parse [任务] --page 20-22    逐块列出这几页的图片块（类型、位置、图片文件、归入哪张图）
  litreader project init|import|list|show|switch|review|set|undecide|diff|revert|sync|archive|unarchive|summary|recover
"""
from __future__ import annotations

import argparse
import json
import getpass
import sys

from . import secrets
from .events import BusUI, CliAdapter, EventBus
from .errors import LitError

COMMANDS = {"gui", "setup", "doctor", "key", "models", "find", "read", "templates", "project", "inspect-parse", "help", "-h", "--help"}
REFRESH_RE = r"^\s*(请)?(刷新|更新|重新扫描)(一下)?模板库\s*$|我把新模板放进模板库了"
EXAMPLE = "精读zotero中的 <题名或关键词>，并将精读笔记存入obsidian中"


def _ok(b: bool) -> str:
    return "✅" if b else "❌"


class ConsoleUI(BusUI):
    """Terminal front end = event bus + CLI adapter (prints log text, answers decisions with input(prompt)).
    Output and prompts are exactly those of the pre-bus ConsoleUI."""

    def __init__(self, bus: EventBus | None = None, out=None, inp=None):
        super().__init__(bus)
        self.adapter = CliAdapter(out, inp if inp is not None else (lambda p: input(p))).attach(self.bus)


# ---------------- doctor ----------------
def cmd_doctor(a) -> int:
    from . import appconfig
    from .llm.models import ROLES, SLOT_NAMES
    from .zotero.client import ZoteroClient, ZoteroUnavailable
    print(f"{_ok(sys.version_info >= (3, 11))} Python {sys.version.split()[0]}（需要 3.11 或更高）")
    try:
        cfg = appconfig.load(a.config)
    except LitError as e:
        print(f"❌ 配置：{e}")
        return 1
    print(f"✅ 配置文件：{cfg.path}")
    print(f"{_ok(cfg.vault_root.is_dir())} Obsidian 库：{cfg.vault_root}")
    print(f"   笔记只会写入：{cfg.dry_run_root}{'（已存在）' if cfg.dry_run_root.exists() else '（首次精读时创建）'}")
    try:
        z = ZoteroClient(base=cfg.zotero_api)
        recent = z.recent(1)
        print(f"✅ Zotero 本地接口可用（最近条目：{recent[0].title[:40] if recent else '无'}）")
    except (ZoteroUnavailable, OSError) as e:
        print(f"❌ Zotero 本地接口：{e}\n   → 确认 Zotero 已打开；并在 Zotero 设置 → 高级 勾选“允许此计算机上的其他应用程序与 Zotero 通讯”")
    print(f"{_ok((cfg.zotero_data_dir / 'storage').is_dir())} Zotero 附件目录：{cfg.zotero_data_dir / 'storage'}")
    if not (cfg.zotero_data_dir / "storage").is_dir():
        print("   → 运行 litreader setup zotero 自动查找 Zotero 数据目录（只读，不修改 Zotero）")
    ok, backend = secrets.selftest()
    print(f"{_ok(ok)} 钥匙串（keyring）：{backend}")
    print(f"{_ok(bool(secrets.get(cfg.mineru_token_name)))} MinerU Token（{cfg.mineru_token_name}）："
          f"{'已保存' if secrets.get(cfg.mineru_token_name) else '未找到 → litreader key set ' + cfg.mineru_token_name}")
    if cfg.llm_error:
        print(f"❌ 模型设置：{cfg.llm_error}")
    elif cfg.legacy_models:
        print("⚠️ 模型设置仍在旧格式（config.local.toml 的 [providers]）→ 运行 litreader models migrate")
    else:
        print(f"✅ 模型设置：{cfg.models_path}")
    if cfg.models:
        for role, label in ROLES.items():
            slots = cfg.models.roles[role]
            if not slots:
                print(f"{'❌' if role == 'writer' else '➖'} {label}：未设置{'（必需）' if role == 'writer' else '（可选）'}")
            for i, s in enumerate(slots):
                has = bool(secrets.get(s.key_ref))
                print(f"{_ok(has)} {label}·{SLOT_NAMES[i]}：{s.vendor} / {s.model}  Key {s.key_ref}：{'已保存' if has else '未找到'}")
    try:
        from .templates.session import registry_for
        lib = cfg.vault_root / cfg.templates_dir if cfg.templates_dir else None
        reg = registry_for(cfg)
        state, _ = reg.lock_state()
        snap = reg.snapshot()
        mains = sum(1 for r in snap["records"] if r["role"] == "MAIN_NOTE" and r["status"] == "ACTIVE")
        rev = sum(1 for r in snap["records"] if r["status"] in ("NEEDS_REVIEW", "CONFLICT"))
        print(f"{'✅' if lib and lib.is_dir() else '➖'} 模板库（只读）：{lib}{'' if lib and lib.is_dir() else '（不存在：只用内置模板）'}")
        print(f"{'✅' if state == 'free' else '⚠️'} 模板登记：{reg.root}（快照 #{snap['n']}，可用主模板 {mains}，待审 {rev}，锁 {state}）"
              + ("" if snap["n"] else " → 首次精读或 litreader templates refresh 时登记"))
    except LitError as e:
        print(f"❌ 模板登记：{e}")
    try:
        from .project.session import context
        preg, pviews = context(cfg)
        pstate, _ = preg.lock_state()
        psnap = preg.snapshot()
        d = psnap["prefs"].get("default_project")
        drec = preg.latest(psnap, d) if d else None
        edits = pviews.manual_edits(preg, psnap)
        print(f"{'✅' if pstate == 'free' else '⚠️'} 课题登记：{preg.root}（快照 #{psnap['n']}，课题 {len(preg.projects(psnap))} 个，"
              f"默认：{drec['title'] + ' v' + str(drec['version']) if drec else '无'}，锁 {pstate}）")
        print(f"   课题档案位置：{pviews.root}" + (f"；⚠️ 有 {len(edits)} 个手动修改待确认 → litreader project sync" if edits else ""))
    except LitError as e:
        print(f"❌ 课题登记：{e}")
    print("   （doctor 不调用模型；要实际测试连通请运行 litreader models test）")
    return 0


# ---------------- key ----------------
def cmd_key(a) -> int:
    if a.action == "test":
        ok, backend = secrets.selftest()
        print(f"{_ok(ok)} 钥匙串自检：{backend}")
        return 0 if ok else 1
    if not a.name:
        print("用法：litreader key set 名称（例如 MINERU_API_TOKEN）")
        return 2
    v = getpass.getpass(f"请粘贴 {a.name} 后按回车（屏幕上不会显示）：").strip()
    if not v:
        print("❌ 没有输入内容，未保存")
        return 1
    secrets.set_secret(a.name, v)
    print(f"✅ {a.name} 已保存到钥匙串（长度 {len(v)}）")
    return 0


# ---------------- models ----------------
def _load_models(a):
    from . import appconfig
    from .llm import models as M
    cfg = appconfig.load(a.config)
    if cfg.models_path.is_file():
        ms = M.load(cfg.models_path)
    elif cfg.legacy_models:
        raise LitError("模型设置仍在旧格式，请先运行 litreader models migrate")
    else:
        ms = M.ModelSettings()
    return cfg, ms


def _role(name: str) -> str:
    from .llm.models import ROLE_ALIASES
    r = ROLE_ALIASES.get((name or "").strip().lower()) or ROLE_ALIASES.get((name or "").strip())
    if not r:
        raise LitError(f"未知角色「{name}」：可用 主笔 / 看图 / 交叉核对")
    return r


def cmd_models(a) -> int:
    from .llm import models as M
    from .llm import presets
    from .llm.client import urllib_transport
    if a.action == "migrate":
        from . import appconfig
        import tomllib
        cfg = appconfig.load(a.config)
        if cfg.models_path.exists():
            print(f"ℹ️ 已存在 {cfg.models_path}，无需迁移（未改动）")
            return 0
        d = tomllib.loads(cfg.path.read_text("utf-8"))
        ms = M.migrate_legacy(d)
        M.save(ms, cfg.models_path)
        print(f"✅ 已把旧的模型设置迁移到 {cfg.models_path}（Key 仍在钥匙串原名称下）。")
        print("   config.local.toml 里的 [providers]/[stations] 已不再使用，可保留或删除。")
        return 0
    cfg, ms = _load_models(a)
    if a.action == "list":
        print(f"模型设置：{cfg.models_path}")
        from . import calibration
        try:
            store = calibration.Store(cfg.data_dir, cfg.vault_root)
        except (ValueError, AttributeError):
            store = None
        for role, label in M.ROLES.items():
            print(f"【{label}】")
            if not ms.roles[role]:
                print("   （未设置）")
            for i, s in enumerate(ms.roles[role]):
                price = (f"  单价 {s.price_in}/{s.price_out} 元/百万" if s.price_in is not None and s.price_out is not None
                         else "  单价 未填")
                print(f"   {i + 1}. {M.SLOT_NAMES[i]}  {s.vendor} | {s.model} | {s.url} | Key {s.key_ref}："
                      f"{'已保存' if secrets.get(s.key_ref) else '未保存'}{price}")
                if store:
                    print(f"      估算校准：{calibration.slot_line(store.records(calibration.key(s.vendor, s.model, role)))}")
        return 0
    if a.action == "remove":
        role = _role(a.role)
        i = int(a.index) - 1
        if not 0 <= i < len(ms.roles[role]):
            print("❌ 序号不存在")
            return 1
        s = ms.roles[role].pop(i)
        M.save(ms, cfg.models_path)
        print(f"✅ 已删除 {M.ROLES[role]} 第 {i + 1} 个（{s.vendor} {s.model}）；钥匙串中的 Key 未删除")
        return 0
    if a.action == "set":
        return _models_set(a, cfg, ms)
    if a.action == "test":
        llm = ms.to_llm_config(require_writer=False)
        roles = [_role(a.role)] if a.role else list(M.ROLES)
        env = secrets.SecretEnv()
        allok = True
        for role in roles:
            for i, s in enumerate(ms.roles[role]):
                if a.index and int(a.index) != i + 1:
                    continue
                p = llm.providers[ms.slot_id(role, i)]
                r = M.test_slot(p, role, a._transport or urllib_transport, env)
                allok &= r["ok"]
                extra = f"，{r['latency_s']}s" if r.get("latency_s") is not None else ""
                print(f"{_ok(r['ok'])} {M.ROLES[role]}·{M.SLOT_NAMES[i]}（{s.vendor} {s.model}）：{r['category']}"
                      f"{('，' + r['detail']) if r.get('detail') else ''}{extra}")
                if r.get("hint"):
                    print(f"   提示：{r['hint']}")
                if getattr(a, "verbose", False):
                    if r.get("request"):
                        print("   请求（与正式精读相同的构造；不含消息正文与 Key）：" + json.dumps(r["request"], ensure_ascii=False))
                    if r.get("usage"):
                        u = r["usage"]
                        print(f"   用量：输入 {u.get('prompt_tokens', '?')}，输出 {u.get('completion_tokens', '?')} tokens")
                    if "raw" in r:
                        print("   原始回复（已隐去 Key，最多 300 字）：" + json.dumps(r["raw"], ensure_ascii=False))
                if r["category"] == "KEY_MISSING":
                    print(f"   → litreader models set {M.ROLES[role]} {i + 1}（或 litreader key set {s.key_ref}）")
        return 0 if allok else 1
    return 2


def _ask(prompt, default=None):
    v = input(f"{prompt}{f'［回车=保留 {default}］' if default else ''}：").strip()
    return v or (default or "")


def _models_set(a, cfg, ms) -> int:
    from .llm import models as M
    from .llm import presets
    role = _role(a.role)
    slots = ms.roles[role]
    i = (int(a.index) - 1) if a.index else len(slots)
    if not 0 <= i <= len(slots) or i >= 4:
        print(f"❌ 序号应为 1–{min(len(slots) + 1, 4)}（{M.ROLES[role]}最多 1 个主用 + 3 个备用）")
        return 1
    cur = slots[i] if i < len(slots) else None
    print(f"设置 {M.ROLES[role]}·{M.SLOT_NAMES[i]}（直接回车保留方括号里的值）")
    vendor = a.vendor or _ask("厂商名称（随便写，例如 DeepSeek / Gemini / 通义）", cur.vendor if cur else None)
    pre = presets.by_vendor(vendor)
    url_default = (cur.url if cur else None) or (pre["url"] if pre else None)
    if pre and not (cur and cur.url):
        print(f"   已知厂商：URL 预填为 {pre['url']}（已核实）")
    elif not pre and not url_default:
        print("   这个厂商没有预设 URL：请从厂商文档找到 “OpenAI 兼容” 的 Base URL（通常以 /v1 结尾）")
    url = a.url or _ask("URL（OpenAI 兼容 Base URL）", url_default)
    model = a.model or _ask("模型名（从厂商文档/控制台复制模型 ID）", cur.model if cur else None)
    key_ref = a.key_ref or (cur.key_ref if cur else M.default_key_ref(vendor, url, role, i))
    pin = a.price_in if a.price_in is not None else (cur.price_in if cur else None)
    pout = a.price_out if a.price_out is not None else (cur.price_out if cur else None)
    if a.price_in is None and a.price_out is None and not a.no_prompt_price:
        t = input("（可选）单价：输入“输入价 输出价”（元/百万 tokens），例如 2 8；直接回车跳过：").strip()
        if t:
            try:
                pin, pout = (float(x) for x in t.replace("，", " ").replace(",", " ").split()[:2])
            except ValueError:
                print("   单价格式不对，已跳过")
    new = M.Slot(vendor=vendor, model=model, url=url, key_ref=key_ref, price_in=pin, price_out=pout,
                 json_mode=cur.json_mode if cur else None, max_tokens=cur.max_tokens if cur else None,
                 timeout_s=cur.timeout_s if cur else None, extra_body=cur.extra_body if cur else None)
    new.validate(f"{M.ROLES[role]}·{M.SLOT_NAMES[i]}")
    has = bool(secrets.get(key_ref))
    if not a.no_key:
        k = getpass.getpass(f"API Key（存入钥匙串，名称 {key_ref}；屏幕不显示"
                            f"{'；直接回车=保留已有' if has else ''}）：").strip()
        if k:
            secrets.set_secret(key_ref, k)
            has = True
    if i < len(slots):
        slots[i] = new
    else:
        slots.append(new)
    M.save(ms, cfg.models_path)
    print(f"✅ 已保存 {M.ROLES[role]}·{M.SLOT_NAMES[i]}：{vendor} / {model} / {url}；Key {key_ref}：{'已保存' if has else '未保存'}")
    print(f"   下一步：litreader models test {M.ROLES[role]} {i + 1}")
    return 0


# ---------------- find / run ----------------
def cmd_find(a) -> int:
    from . import appconfig
    from .zotero.client import ZoteroClient
    cfg = appconfig.load(a.config)
    z = ZoteroClient(base=cfg.zotero_api)
    cands = z.search(a.title) or z.search(a.title, qmode="everything")
    print(f"找到 {len(cands)} 篇")
    mt = {}
    if len(cands) > 0 and cfg.llm is not None:
        from .llm.client import urllib_transport
        from .realrun import translate_candidates
        mt = translate_candidates(cfg, cands, urllib_transport, None, None, ConsoleUI())
    for i, c in enumerate(cands, 1):
        zh = "｜" + c.title_zh if c.title_zh else ("｜" + mt[c.parent_key] + "（机翻）" if mt.get(c.parent_key) else "")
        print(f"  {i}. {c.title}{zh} · {c.year or '?'} · "
              f"加入 {(c.date_added or '')[:10]} · 条目 {c.parent_key}")
    return 0


def cmd_inspect(a) -> int:
    from . import appconfig
    from .cli_inspect import run
    return run(appconfig.load(a.config), a.job, pages=getattr(a, "page", None), show_text=getattr(a, "text", False))


def run_command(text: str, config: str | None, ui=None, **kw) -> int:
    import re
    from . import appconfig, realrun
    ui = ui or ConsoleUI()
    if re.search(REFRESH_RE, text):   # spec §8: refresh only, never runs a paper
        from types import SimpleNamespace
        from .cli_templates import cmd_templates
        return cmd_templates(SimpleNamespace(action="refresh", config=config, ai=False))
    cfg = appconfig.load(config)
    from .cli_project import nl_match, run_nl
    if nl_match(text):   # project commands (spec §8): never run a paper
        return run_nl(cfg, text, ui, transport=kw.get("llm_tx"), env=kw.get("env"))
    try:
        res = realrun.run(cfg, text, ui, **kw)
    except realrun.Cancelled as e:
        ui.say(f"⏹ {e}")
        return 3
    ui.say(f"✅ 精读完成\n   笔记：{res['note']}\n   证据档案：{res['evidence']}\n   回执：{res['receipt']}")
    return 0


def interactive(config: str | None, ui=None) -> int:
    ui = ui or ConsoleUI()
    ui.say(f"litreader 交互模式。一次精读一篇。示例：{EXAMPLE}\n输入 q 退出。")
    while True:
        t = ui.ask("指令> ").strip()
        if t.lower() in ("q", "quit", "exit", "退出"):
            return 0
        if not t:
            continue
        try:
            run_command(t, config, ui)
        except LitError as e:
            ui.say(f"⛔ 已停止：{e}")


def cmd_setup(a) -> int:
    """litreader setup zotero: read-only detection + local API probe; saving to config.local.toml only after y."""
    from . import appconfig
    from .zotero import setup as zs
    d, pr = zs.check(a.data_dir, opener=getattr(a, "_opener", None))
    print("Zotero 一键设置（只读检测，不修改 Zotero）")
    for line in zs.report(d, pr):
        print(line)
    try:
        cfgp = appconfig.find_config(a.config)
    except LitError:
        print("ℹ️ 还没有 config.local.toml：按指南第 2 节复制 config.example.toml 后再运行本命令即可保存。")
        return 0 if d["valid"] and pr["status"] == "OK" else 1
    if not d["valid"]:
        print("（数据目录未通过检查，不提供保存）")
        return 1
    text = cfgp.read_text("utf-8")
    new, changes = zs.config_updates(text, d["data_dir"], f"http://localhost:{d['port']}/api")
    if not changes:
        print(f"✅ {cfgp} 中的 Zotero 设置已与检测结果一致，无需修改")
        return 0 if pr["status"] == "OK" else 1
    print(f"将修改 {cfgp}：")
    for c in changes:
        print(f"   {c}")
    ans = (getattr(a, "_input", None) or input)("保存吗？会先把原文件备份为 .bak-时间戳 (y/n)：").strip().lower()
    if ans not in ("y", "yes", "是"):
        print("未保存（没有改动任何文件）")
        return 0
    bak = zs.save_config(cfgp, new)
    print(f"✅ 已保存；原文件备份在 {bak}")
    return 0 if pr["status"] == "OK" else 1


def cmd_gui(a) -> int:
    """litreader gui: the desktop window (optional extra: pip install -e ".[gui]")."""
    try:
        from .gui.app import main as gui_main
    except ImportError as e:
        print(f"❌ 还没有安装图形界面组件（PySide6：{e}）。在 litreader 文件夹里运行：\n"
              f"   ./.venv/bin/python -m pip install -e \".[mac,gui]\"\n然后再运行 ./.venv/bin/litreader gui")
        return 1
    return gui_main([sys.argv[0]], config=a.config)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config = None
    if len(argv) >= 2 and argv[0] == "--config":
        config, argv = argv[1], argv[2:]
    try:
        if not argv:
            return interactive(config)
        if argv[0] not in COMMANDS:
            return run_command(" ".join(argv), config)
        ap = argparse.ArgumentParser(prog="litreader", description="Zotero → AI 精读 → Obsidian。"
                                     f"也可以直接：litreader \"{EXAMPLE}\"")
        sub = ap.add_subparsers(dest="cmd", required=True)
        sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
        sub.add_parser("gui", help="打开图形界面（需要先安装 .[gui]）").set_defaults(fn=cmd_gui)
        su = sub.add_parser("setup", help="一键设置：litreader setup zotero（只读检测 Zotero 数据目录与本地接口）")
        su.add_argument("target", choices=["zotero"]); su.add_argument("--data-dir", dest="data_dir")
        su.set_defaults(fn=cmd_setup)
        k = sub.add_parser("key"); k.add_argument("action", choices=["set", "test"]); k.add_argument("name", nargs="?")
        k.set_defaults(fn=cmd_key)
        m = sub.add_parser("models", help="模型设置")
        m.add_argument("action", choices=["list", "set", "test", "remove", "migrate"])
        m.add_argument("role", nargs="?"); m.add_argument("index", nargs="?")
        for f in ("vendor", "model", "url", "key-ref"):
            m.add_argument(f"--{f}")
        m.add_argument("--price-in", type=float); m.add_argument("--price-out", type=float)
        m.add_argument("--no-key", action="store_true", help="不询问 Key")
        m.add_argument("--no-prompt-price", action="store_true")
        m.add_argument("--verbose", "-v", action="store_true", help="models test：显示请求设置与原始回复（已隐去 Key）")
        m.set_defaults(fn=cmd_models, _transport=None)
        f = sub.add_parser("find"); f.add_argument("title"); f.set_defaults(fn=cmd_find)
        from .cli_templates import ACTIONS, cmd_templates
        t = sub.add_parser("templates", help="模板库")
        t.add_argument("action", choices=ACTIONS); t.add_argument("target", nargs="?")
        t.add_argument("--all", action="store_true"); t.add_argument("--for", dest="for_type")
        t.add_argument("--clear", action="store_true"); t.add_argument("--role"); t.add_argument("--types")
        t.add_argument("--yes", action="store_true"); t.add_argument("--to", type=int)
        t.add_argument("--ai", action="store_true", help="refresh 时让模型为缺少 front matter 的模板建议标签（仍需批准）")
        t.add_argument("--id"); t.add_argument("--title")
        t.add_argument("--project", help="templates prefer 〈模板〉 --project 〈课题〉：该课题优先用这个主模板（第 3 级）")
        t.set_defaults(fn=lambda a: cmd_templates(a, getattr(a, "_transport", None)))
        ip = sub.add_parser("inspect-parse", help="查看已缓存的 MinerU 解析结果的每页块类型统计（不上传、不含内容）")
        ip.add_argument("job", nargs="?", help="任务名或其中一部分（如 Zotero 条目 Key）；省略 = 最近一次")
        ip.add_argument("--page", help="逐块列出这些物理页（如 21、20-22）：类型、位置、图片文件、归入哪张图")
        ip.add_argument("--text", action="store_true", help="配合 --page：同时显示每个正文块开头 40 字（含论文内容）")
        ip.set_defaults(fn=cmd_inspect)
        from .cli_project import ACTIONS as PACTIONS, cmd_project
        pj = sub.add_parser("project", help="科研项目库（课题档案）")
        pj.add_argument("action", choices=PACTIONS); pj.add_argument("target", nargs="?"); pj.add_argument("value", nargs="?")
        pj.add_argument("--title"); pj.add_argument("--project"); pj.add_argument("--yes", action="store_true")
        pj.add_argument("--to", type=int); pj.add_argument("--from-vault", dest="from_vault", action="store_true")
        pj.add_argument("--v1", type=int); pj.add_argument("--v2", type=int)
        pj.set_defaults(fn=lambda a: cmd_project(a))
        r = sub.add_parser("read", help="同一句话指令：litreader read \"题名\"")
        r.add_argument("title"); r.add_argument("--dry-run", action="store_true")
        r.set_defaults(fn=lambda a: run_command(f"精读{a.title}", a.config))
        sub.add_parser("help").set_defaults(fn=lambda a: (ap.print_help(), 0)[1])
        a = ap.parse_args(argv)
        a.config = config
        return a.fn(a)
    except LitError as e:
        print(f"⛔ 已停止：{e}")
        return 1
    except KeyboardInterrupt:
        print("\n已取消")
        return 130


if __name__ == "__main__":
    sys.exit(main())
