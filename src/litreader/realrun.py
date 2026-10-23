"""Real single-paper run (Stage 4/5 on the user's Mac), driven by a natural-language command. DRY-RUN ONLY:
every write goes through the safe writer into <vault>/<output_dir>/ (the sandbox root, default litreader/), nothing else in the vault.

Flow: intent (regex, LLM fallback) -> Zotero search + numbered pick -> PDF via /file/view/url (fallback storage path),
hash before/after, isolated copy -> ESTIMATE (local only) + y/n -> MinerU (cached per identity) -> E-level gate ->
vision / writer / validator / cross-check / wording judge -> topic folder (reuse similar; new needs confirmation)
-> exclusive-create writes -> actual tokens / cost. Zotero: read-only GETs.
"""
from __future__ import annotations

from litreader.platform_words import keystore_name as _kn, keystore_prompt_hint
import json
import re
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from . import calibration
from . import estimate as est_mod
from . import events
from . import secrets
from .analysis import wording_judge
from .analysis.crosscheck import judge
from .analysis.extract import extract_v2
from .analysis.validator_v2 import validate_v2
from .analysis.vision import cached_observe, observe  # noqa: F401
from .appconfig import AppConfig
from .errors import Stop
from .hashing import sha256_file
from .intent import parse as parse_intent, parse_regex
from .llm.client import urllib_transport as llm_transport
from .llm.models import ROLES
from .parse import figures, mineru
from .parse.blocks import cjk_ratio
from .parse import extraction_level
from .parse.extraction_level import assess
from .parse.mineru_api import parse_pdf
from .permissions import Sandbox
from .render.l2_note_v2 import render, render_evidence
from .project import lens as lens_mod
from .project import session as psession
from .templates import session as tsession
from .vault import naming, topics
from .vault.writer import VaultWriter
from .zotero.client import ZoteroClient, norm_title, storage_path
from .zotero.identity import build_identity, detect_source_version, isolate_copy
from .zotero import translate as title_tr
from .zotero.metadata import author_order_check, from_item
from .analysis import unknown_rank


class UI(Protocol):
    def say(self, msg: str) -> None: ...
    def ask(self, prompt: str) -> str: ...


class Cancelled(Stop):
    pass


def _pdf_pages(pdf: Path) -> int:
    return est_mod.pdf_stats(pdf).get("pages") or 0


STATION = {"writer": "extract", "vision": "vision", "judge": "judge"}


def _vm(cfg: AppConfig, pid: str | None, fallback_model: str = "?") -> tuple[str, str]:
    """(vendor, model id) of a slot, the calibration identity of a model."""
    s = cfg.models.find(pid) if (cfg.models and pid) else None
    return (s.vendor, s.model) if s else (pid or "?", fallback_model or "?")


def calibration_store(cfg: AppConfig, ui: UI | None = None):
    try:
        return calibration.Store(cfg.data_dir, cfg.vault_root)
    except ValueError as e:
        if ui:
            ui.say(f"⚠️ {e}；本次不使用、也不记录模型校准")
        return None


def apply_calibration(cfg: AppConfig, est: dict, store) -> dict:
    models = {}
    for role in est.get("roles", {}):
        ch = _chain(cfg, STATION[role])
        if ch:
            models[role] = _vm(cfg, ch[0].id, ch[0].model)
    return calibration.apply(est, models, store)


def _role_of(provider_id: str | None) -> str | None:
    for r in ROLES:
        if provider_id and provider_id.startswith(r) and provider_id[len(r):].isdigit():
            return r
    return None


def _pick(ui: UI, n: int, prompt: str, kind: str = "candidate", options: list[dict] | None = None,
          data: dict | None = None) -> int:
    while True:
        a = events.decide(ui, kind, prompt, options or [events.opt(str(i), str(i)) for i in range(1, n + 1)],
                          default=None, data=data).strip().lower()
        if a in ("q", "quit", "exit", "取消", "0"):
            raise Cancelled("已取消，未做任何改动")
        if a.isdigit() and 1 <= int(a) <= n:
            return int(a) - 1
        ui.say(f"请输入 1–{n} 之间的序号，或 q 取消")


YN = [events.opt("y", "继续"), events.opt("n", "取消")]


def _yes(ui: UI, prompt: str, kind: str = "confirm", data: dict | None = None, options: list[dict] | None = None) -> bool:
    while True:
        a = events.decide(ui, kind, prompt, options or YN, default=None, data=data).strip().lower()
        if a in ("y", "yes", "是", "好", "继续"):
            return True
        if a in ("n", "no", "否", "不", "q"):
            return False
        ui.say("请输入 y 或 n")


ROLE_ZH = {"extract": "主笔", "vision": "看图", "judge": "交叉核对"}


def preflight_keys(cfg: AppConfig, env, need_mineru: bool = True) -> None:
    """Before any upload or model call: every configured role needs at least one slot whose key can be read.
    Distinguishes "not stored" from "keychain error". Never reads more than presence; never prints a value."""
    from .secrets import KeychainError
    problems = []
    for st, ids in cfg.llm.stations.items():
        errs = []
        for pid in ids:
            p = cfg.llm.providers[pid]
            try:
                if env.get(p.key_env, ""):
                    errs = None
                    break
                errs.append(f"{p.key_env} 未找到")
            except KeychainError as e:
                errs.append(f"{p.key_env} {_kn()}读取失败（KEYCHAIN_ERROR: {e.kind}）")
        if errs:
            problems.append(f"{ROLE_ZH.get(st, st)}：" + "；".join(errs))
    if need_mineru:
        try:
            ok = bool(env.get(cfg.mineru_token_name, ""))
            if not ok:
                problems.append(f"MinerU 解析：{cfg.mineru_token_name} 未找到")
        except KeychainError as e:
            problems.append(f"MinerU 解析：{cfg.mineru_token_name} {_kn()}读取失败（KEYCHAIN_ERROR: {e.kind}）")
    if problems:
        raise Stop("API Key 预检未通过（尚未上传、未调用任何模型）：" + " | ".join(problems)
                   + f"。请在「模型设置」对应页签保存 Key；" + keystore_prompt_hint())


def _chain(cfg: AppConfig, station: str):
    return cfg.llm.chain(station) if station in cfg.llm.stations else cfg.llm.chain("extract")


def translate_candidates(cfg: AppConfig, cands, llm_tx, env, runs: list | None, ui: UI) -> dict:
    """Display-only Chinese titles for the pick list (never written to Zotero). Failures fall back to English."""
    if not cfg.translate_titles:
        return {}
    try:
        chain = _chain(cfg, "judge" if cfg.translate_role == "judge" else "extract")
    except Exception:  # noqa: BLE001 — no model configured: English only
        chain = []
    zh, info = title_tr.translate(cands, chain, llm_tx, env if env is not None else secrets.SecretEnv(),
                                  cfg.data_dir / title_tr.CACHE_NAME)
    if info["status"] in ("OK", "PARTIAL"):
        u = info["usage"] or {}
        if runs is not None:
            runs.append({"provider": info["provider"], "usage": u, "stage": "title_translate"})
        ui.say(f"  （{info['sent']} 个英文题名已机翻：{cfg.slot_label(info['provider'])}，输入 {u.get('prompt_tokens', 0):,}/"
               f"输出 {u.get('completion_tokens', 0):,} tokens，{info['latency_s']:.1f} 秒"
               + (f"；另 {info['cached']} 个用缓存" if info["cached"] else "")
               + (f"；{len(info['failed'])} 个未通过校验，只显示英文" if info["failed"] else "") + "）")
    elif info["status"] == "FAILED":
        ui.say(f"  （题名机翻失败，只显示英文：{info.get('error', '')}）")
    return zh


_BRACKETS = re.compile(r"[《》〈〉「」『』“”‘’\"'【】\[\]<>]")
_KW_SPLIT = re.compile(r"[\s,，.。:：;；!！?？/\\|()（）\-—–_]+")
_STOP = {"the", "a", "an", "of", "and", "in", "on", "for", "with", "to", "by", "from", "at", "is", "are"}


def clean_query(q: str) -> str:
    """G8-1: book-title marks and quotes the user typed around a title are not part of it."""
    return re.sub(r"\s+", " ", _BRACKETS.sub(" ", q or "")).strip()


def keywords(q: str, n: int = 4) -> list[str]:
    toks = [t for t in _KW_SPLIT.split(clean_query(q)) if len(t) >= 2 and t.lower() not in _STOP]
    seen, out = set(), []
    for t in sorted(toks, key=len, reverse=True):
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:n]


def keyword_candidates(z: ZoteroClient, q: str, limit: int = 10) -> list:
    """Fallback when the whole query matches nothing: search each keyword, rank items by how many keywords hit."""
    score, items = {}, {}
    kws = keywords(q)
    for k in kws:
        for c in z.search(k) or []:
            items.setdefault(c.parent_key, c)
            score[c.parent_key] = score.get(c.parent_key, 0) + 1
    if len(kws) > 1:     # an item that only matches one short keyword out of several is noise
        keep = [k for k, v in score.items() if v >= 2] or list(score)
    else:
        keep = list(score)
    keep.sort(key=lambda k: -score[k])
    return [items[k] for k in keep[:limit]]


def choose_item(z: ZoteroClient, query: str, ui: UI, translate=None):
    query = clean_query(query) or query
    cands = z.search(query) or z.search(query, qmode="everything")
    fallback = False
    if not cands:
        cands = keyword_candidates(z, query)
        fallback = bool(cands)
    if not cands:
        raise Stop(f"Zotero 中没有找到与「{query}」匹配的论文（也试了按关键词 {('、'.join(keywords(query)) or '—')} 查找），"
                   "已停止（未做任何改动）。可以换个关键词，或只写题名中的几个词。")
    if fallback:
        ui.say(f"没有找到题名完全匹配的论文，按关键词（{'、'.join(keywords(query))}）找到以下候选：")
    exact = [c for c in cands if norm_title(c.title) == norm_title(query)]
    if len(exact) == 1 and len(cands) == 1 and not fallback:
        item = exact[0]
        ui.say(f"找到 1 篇：{item.title}（{item.year or '年份未知'}）")
    else:
        ui.say(f"找到 {len(cands)} 篇候选，请选择：")
        mt = translate(cands) if translate else {}
        options, cdata = [], []
        for i, c in enumerate(cands, 1):
            zh_t = c.title_zh or (f"{mt[c.parent_key]}（机翻）" if mt.get(c.parent_key) else "")
            zh = f"\n      中文：{zh_t}" if zh_t else ""
            meta = f"{c.year or '年份未知'} · 加入 Zotero：{(c.date_added or '')[:10]} · 条目 {c.parent_key}"
            ui.say(f"  {i}. {c.title}{zh}\n      {meta}")
            options.append(events.opt(str(i), c.title, (zh_t + " · " if zh_t else "") + meta))
            cdata.append({"title": c.title, "title_zh": c.title_zh or mt.get(c.parent_key) or "",
                          "machine": bool(not c.title_zh and mt.get(c.parent_key)), "year": c.year or "",
                          "added": (c.date_added or "")[:10], "key": c.parent_key})
        item = cands[_pick(ui, len(cands), "请输入序号（q 取消）：", "candidate", options, data={"candidates": cdata})]
    atts = z.attachments(item.parent_key)
    for a in atts:
        if a.parent_key != item.parent_key:
            raise Stop(f"附件 {a.key} 的父条目不一致，停止")
    pdfs = [a for a in atts if a.is_stored_pdf]
    if not pdfs:
        raise Stop("该条目没有存储在本机的 PDF 附件，已停止")
    if len(pdfs) > 1:
        ui.say("该条目有多个 PDF，请选择：")
        for i, a in enumerate(pdfs, 1):
            ui.say(f"  {i}. {a.filename}（附件 {a.key}）")
        att = pdfs[_pick(ui, len(pdfs), "请输入序号（q 取消）：", "pdf",
                         [events.opt(str(i), a.filename, f"附件 {a.key}") for i, a in enumerate(pdfs, 1)])]
    else:
        att = pdfs[0]
    return item, att


def estimate_cost(cfg: AppConfig, est: dict) -> dict:
    """Per-role primary-slot cost (None = no price filled) and the total, the same numbers show_estimate prints."""
    roles, total, priced = {}, 0.0, True
    for role, t in est["roles"].items():
        p = _chain(cfg, STATION[role])[0]
        c = est_mod.cost(t["in"], t["out"], *cfg.price(p.id))
        cal = t.get("calibration") or {}
        roles[role] = {"label": ROLES[role], "model": cfg.slot_label(p.id), "in": t["in"], "out": t["out"], "cost": c,
                       "spread": cal.get("spread", est_mod.RATIO["spread"]), "calibration": cal.get("label"),
                       "calibrated": bool(cal.get("calibrated")), "n": cal.get("n", 0),
                       "price_in": cfg.price(p.id)[0], "price_out": cfg.price(p.id)[1]}
        if c is None:
            priced = False
        else:
            total += c
    return {"roles": roles, "total": total if priced else None, "priced": priced}


def show_estimate(cfg: AppConfig, est: dict, ui: UI) -> None:
    ui.say("—— 运行前估算（ESTIMATE：按论文长度与图数推算，与模型无关；有本机实测的模型按实测校准）——")
    ui.say(f"  PDF：{est['pages'] or '?'} 页；正文约 {est['chars'] or '?'} 字"
           f"{'' if est['chars_measured'] else '（未能本地读取文字，按页数粗估）'}；图约 {est['figures']} 个")
    ui.say("  MinerU：已有解析缓存，不上传" if not est["mineru_pages"] else
           f"  MinerU：将上传 PDF 副本（云端），约 {est['mineru_pages']} 页计入 MinerU 额度")
    total = 0.0
    priced = True
    for role, t in est["roles"].items():
        station = {"writer": "extract", "vision": "vision", "judge": "judge"}[role]
        chain = _chain(cfg, station)
        p = chain[0]
        c = est_mod.cost(t["in"], t["out"], *cfg.price(p.id))
        if c is None:
            priced = False
        else:
            total += c
        note = f"；约 ¥{c:.3f}（按你填的单价）" if c is not None else "；费用：未填单价"
        cal = t.get("calibration") or {}
        sp = cal.get("spread", est_mod.RATIO["spread"])
        ui.say(f"  {ROLES[role]}（{cfg.slot_label(p.id)}）：输入 {est_mod.fmt_range(t['in'], sp)}，"
               f"输出 {est_mod.fmt_range(t['out'], sp)} tokens{note}")
        if cal.get("label"):
            ui.say(f"      {cal['label']}")
    if est.get("lens"):
        le = est["lens"]
        ui.say(f"  项目视角（含在主笔内）：将发送课题《{le['title']}》v{le['version']} 摘要（约 {le['summary_chars']} 字，已确认 "
               f"{le['confirmed']} 项）＋本篇分析要点；输入 约 {le['in']:,}，输出 约 {le['out']:,} tokens（未实测，估算）")
    if est["roles"]:
        ui.say(f"  合计费用估算：约 ¥{total:.3f}" if priced else
               "  费用：部分模型未填单价（models.toml 的 price_in/price_out），只显示 token 估算")


def actual_usage(cfg: AppConfig, runs: list[dict]) -> dict:
    agg: dict = {}
    for r in runs:
        if not r or not r.get("usage"):
            continue
        pid = r.get("provider")
        role = _role_of(pid) or "writer"
        a = agg.setdefault(role, {"in": 0, "out": 0, "cost": 0.0, "priced": True, "models": set()})
        u = r["usage"]
        a["in"] += u.get("prompt_tokens", 0); a["out"] += u.get("completion_tokens", 0)
        a["models"].add(cfg.slot_label(pid) if pid else "?")
        a.setdefault("providers", set()).add(_vm(cfg, pid, r.get("model") or "?"))
        c = est_mod.cost(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), *cfg.price(pid))
        if c is None:
            a["priced"] = False
        else:
            a["cost"] += c
    for a in agg.values():
        a["models"] = sorted(a["models"])
        a["providers"] = sorted(a.get("providers") or [])
    return agg


class _StageTap:
    """Transparent proxy around the run's UI that remembers the last stage (for the stopped/cancelled receipt)."""

    def __init__(self, ui, ctx: dict):
        self._ui, self._ctx = ui, ctx

    def __getattr__(self, name):
        return getattr(self._ui, name)

    def emit(self, type: str, **data):
        if type == "stage" and data.get("status") == "start":
            self._ctx["stage"] = data.get("stage")
        f = getattr(self._ui, "emit", None)
        if callable(f):
            f(type, **data)


def _record_stop(ctx: dict, e: BaseException) -> None:
    """A run that got as far as a job folder but did not finish still leaves a receipt (status STOPPED / CANCELLED),
    so 最近精读 can show it. Written only in the app-data job folder, never in the vault."""
    job, receipt = ctx.get("job"), ctx.get("receipt")
    if job is None or receipt is None or ctx.get("written"):
        return
    cancelled = isinstance(e, (Cancelled, events.Cancelled))
    rec = dict(receipt)
    rec.update(status="CANCELLED" if cancelled else "STOPPED", stopped_at=ctx.get("stage"),
               reason=str(e)[:500], finished=datetime.now().isoformat(timespec="seconds"))
    try:
        (job / f"receipt-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1, default=str), "utf-8")
    except OSError:
        pass


def paper_info(zm: dict, item, att, title_zh: str | None = None) -> dict:
    """What 最近精读 / the result page show for a paper (Zotero metadata; no paper content)."""
    last = (zm.get("authors_last") or [None])[0]
    return {"title_zh": title_zh or zm.get("title_zh_zotero") or "", "title_en": zm.get("title_en") or item.title,
            "first_author": zm.get("first_author_for_name") or (zm.get("authors_full") or [""])[0], "author_last": last or "",
            "year": zm.get("year") or item.year or "", "journal": zm.get("journal") or "", "item_key": item.parent_key,
            "attachment_key": att.key}


def run(cfg: AppConfig, command: str, ui: UI, **kw) -> dict:
    ctx: dict = {}
    try:
        return _run(cfg, command, _StageTap(ui, ctx), _ctx=ctx, **kw)
    except Exception as e:
        _record_stop(ctx, e)
        raise


def _run(cfg: AppConfig, command: str, ui: UI, *, zotero: ZoteroClient | None = None, llm_tx=llm_transport,
         mineru_kwargs: dict | None = None, env=None, pages_fn=_pdf_pages, stats_fn=est_mod.pdf_stats,
         _ctx: dict | None = None) -> dict:
    ctx = _ctx if _ctx is not None else {}
    env = env if env is not None else secrets.SecretEnv()
    if cfg.llm is None:
        raise Stop(cfg.llm_error or "模型未设置")
    if not cfg.vault_root.is_dir():
        raise Stop(f"Obsidian 库路径不存在：{cfg.vault_root}")
    preflight_keys(cfg, env, need_mineru=mineru_kwargs is None)
    runs: list[dict] = []
    directive, command = psession.split_directive(command)   # "本次精读不关联任何课题" / "用〈课题〉角度…"
    requested, command = tsession.split_request(command)   # "用〈模板名〉模板精读…"

    # 1) intent
    it = parse_regex(command)
    if it.action == "unknown" and command.strip():
        ui.say("规则没能识别这条指令。")
        if _yes(ui, "要让模型帮忙理解这句话吗？（一次很小的调用，约 300 tokens）(y/n)：", "consent",
                options=[events.opt("y", "让模型理解", "约 300 tokens"), events.opt("n", "不用")]):
            it = parse_intent(command, _chain(cfg, "judge"), llm_tx, env)
    if it.run:
        runs.append(it.run)
    if it.action == "batch":
        raise Stop("一次只能精读一篇论文（批量暂不支持）。请只写一篇的题名或关键词")
    if it.action != "read":
        raise Stop("没看懂这条指令。示例：精读zotero中的 <题名或关键词>，并将精读笔记存入obsidian中")
    ui.say(f"理解为：精读 Zotero 中的「{it.query}」（{'规则解析' if it.method == 'regex' else '模型解析'}）")
    receipt: dict = {"started": datetime.now().isoformat(timespec="seconds"), "command": command, "query": it.query,
                     "intent_method": it.method, "mode": "dry-run"}

    # 2) Zotero (never auto-picks among several)
    events.stage(ui, "zotero")
    z = zotero or ZoteroClient(base=cfg.zotero_api)
    item, att = choose_item(z, it.query, ui,
                            translate=lambda cs: translate_candidates(cfg, cs, llm_tx, env, runs, ui))
    zm = from_item(z.item_json(item.parent_key))
    pdf = z.file_path(att.key) or storage_path(cfg.zotero_data_dir / "storage", att)
    if not pdf.is_file():
        raise Stop(f"找不到 PDF 文件：{pdf}")

    # 3) isolated copy + identity (local only)
    sha_before = sha256_file(pdf)
    job_root = cfg.data_dir / "jobs"
    copy, sha = isolate_copy(pdf, job_root / "_incoming")
    ident = build_identity("users/0", item, att, sha)
    job = job_root / ident.fs_key.replace("/", "_")
    job.mkdir(parents=True, exist_ok=True)
    work_pdf = job / "source.pdf"
    if not work_pdf.exists():
        copy.replace(work_pdf)
    else:
        copy.unlink()
    receipt.update(identity=asdict(ident), pdf_sha_before=sha_before, paper=paper_info(zm, item, att))
    ctx.update(job=job, receipt=receipt)

    # 3b) project: manual-edit sync, first-use question (once), resolve + FREEZE one snapshot (design §4)
    events.stage(ui, "zotero", "done", item_key=item.parent_key, attachment_key=att.key, title=item.title)
    events.stage(ui, "project")
    proj = psession.resolve(cfg, ui, directive, chain=cfg.llm.chain("extract"), transport=llm_tx, env=env, runs=runs)
    receipt["project"] = proj.receipt() if proj else None
    if proj:
        events.stage(ui, "project", "done", title=proj.rec["title"], version=proj.rec["version"])
    else:
        events.stage(ui, "project", "skip")


    # 4) estimate + consent (before any upload / LLM call on the paper)
    events.stage(ui, "estimate")
    ext = job / "mineru" / "extracted"
    cached = ext.is_dir() and any(ext.glob("*_content_list.json"))
    present = {r for r, st in {"writer": "extract", "vision": "vision", "judge": "judge"}.items() if st in cfg.llm.stations}
    est = est_mod.estimate(stats_fn(work_pdf), present, cached)
    if proj and est["roles"].get("writer"):   # decision 3 = A: project content listed here, consented with this y
        le = psession.lens_estimate(proj, est["roles"]["writer"]["out"])
        est["lens"] = {**le, "title": proj.rec["title"], "version": proj.rec["version"]}
        est["roles"]["writer"] = {"in": est["roles"]["writer"]["in"] + le["in"], "out": est["roles"]["writer"]["out"] + le["out"]}
    cal_store = calibration_store(cfg, ui)
    est = apply_calibration(cfg, est, cal_store)
    receipt["estimate"] = est
    show_estimate(cfg, est, ui)
    ui.say(f"  写入位置：{cfg.dry_run_root}/{cfg.papers_dir}/<主题文件夹>/")
    if not _yes(ui, "是否继续？(y/n)：", "cost", data={"estimate": est, "upload": not cached, "cost": estimate_cost(cfg, est),
                                                     "write_root": f"{cfg.dry_run_root}/{cfg.papers_dir}/"},
                options=[events.opt("y", "继续精读", "将上传 PDF 副本到 MinerU 并调用模型" if not cached else "调用模型"),
                         events.opt("n", "取消", "未上传、未调用模型")]):
        raise Cancelled("已取消：未上传、未调用模型、未写入任何笔记")
    events.stage(ui, "estimate", "done")

    # 5) parse
    events.stage(ui, "parse")
    if not cached:
        ui.say("… 正在上传 PDF 副本到 MinerU 解析（可能需要几分钟）")
        ext = parse_pdf(work_pdf, job / "mineru", secrets.get(cfg.mineru_token_name) or "", consent=True,
                        model_version=cfg.mineru_model, timeout_s=cfg.mineru_timeout_s, log=ui.say, **(mineru_kwargs or {}))
    res = mineru.load_extracted_dir(ext)
    pages = pages_fn(work_pdf) or (res.page_count_reported or 0)
    el = assess(res, pages)
    receipt["extraction"] = {"level": el.level, "reasons": el.reasons}
    if el.metrics.get("page_kinds"):
        receipt["extraction"]["page_kinds"] = el.metrics["page_kinds"]
    if el.metrics.get("unknown_pages"):
        receipt["extraction"]["unknown_pages"] = el.metrics["unknown_pages"]
    ui.say(f"✔ 解析完成，抽取完整度 {el.level}")
    nt = el.metrics.get("page_kinds") or {}
    covered = {p: k for p, k in nt.items() if k not in ("empty", "chrome_only")}
    if covered:
        ui.say("  没有正文但已覆盖的页面：" + "；".join(f"第 {p} 页 {extraction_level.KIND_ZH[k]}" for p, k in covered.items()))
    if el.level in ("E0", "E1"):
        raise Stop(f"抽取完整度 {el.level}，停止：{'; '.join(el.reasons)}\n"
                   f"   （MinerU 解析结果已缓存，不会重复上传。可运行 litreader inspect-parse {item.parent_key} 查看每页的块类型统计，不含论文内容）")
    for r in el.reasons:
        if "UNKNOWN 页面" in r:
            ui.say(f"  ⚠ {r}（证据档案的 UNKNOWN 登记中列出；精读继续）")
    events.stage(ui, "parse", "done", level=el.level, reasons=list(el.reasons), pages=pages, cached=cached,
                 covered={str(p): extraction_level.KIND_ZH[k] for p, k in covered.items()})
    sv = detect_source_version(att.filename, cjk_ratio(res.blocks))
    manifest = figures.build_manifest(res, sha, att.key)

    # 5b) template: refresh registry (library is read-only) -> study type -> choose -> confirm -> freeze snapshot
    events.stage(ui, "template")
    ui.say("… 判定论文类型并选择模板")
    tags = [t.get("tag") for t in ((z.item_json(item.parent_key) or {}).get("data") or {}).get("tags") or [] if isinstance(t, dict)]
    fr = tsession.prepare(cfg, ui, res.blocks, title=item.title, zotero_tags=tags, chain=_chain(cfg, "judge"),
                          transport=llm_tx, env=env, requested=requested,
                          ask_always=cfg.template_selection == "ask", runs=runs,
                          project_id=proj.rec["id"] if proj else None, project_title=proj.rec["title"] if proj else None)
    receipt["template"] = fr.receipt()
    tr = receipt["template"]
    events.stage(ui, "template", "done", title=tr.get("template_title"), template_id=tr.get("template_id"),
                 study_type=(tr.get("study") or {}).get("study_type") or tr.get("study_type"),
                 modules=[m if isinstance(m, str) else str(m) for m in (tr.get("modules") or [])],
                 reason=tr.get("selection_reason"))

    # 6) LLM stages
    vision_obs, vision_runs = {}, []
    if "vision" in cfg.llm.stations:
        events.stage(ui, "vision")
        ui.say("… 看图")
        vchain = cfg.llm.chain("vision", need_vision=True)
        figs = [m for m in manifest if m["kind"] == "figure"]
        for n, m in enumerate(figs, 1):
            obs, info = cached_observe(m, ext, vchain, llm_tx, env, job / "vision_cache", att.key)
            vision_runs.append(info)
            if obs:
                vision_obs[m["id"]] = obs
            u = (info or {}).get("usage") or {}
            events.progress(ui, "vision", n, len(figs), tokens_in=u.get("prompt_tokens"), tokens_out=u.get("completion_tokens"))
        events.stage(ui, "vision", "done")
    else:
        events.stage(ui, "vision", "skip")
    events.stage(ui, "writer")
    ui.say("… 主笔精读")
    raw, text_run = extract_v2(res.blocks, manifest, cfg.llm.chain("extract"), llm_tx, env, vision_obs,
                               template_suffix=fr.prompt_suffix)
    runs += [text_run] + vision_runs
    if raw.get("_parse_error"):
        raise Stop("主笔模型返回的不是合法 JSON，停止（未写入任何文件）")
    tu = (text_run or {}).get("usage") or {}
    events.progress(ui, "writer", 1, 1, tokens_in=tu.get("prompt_tokens"), tokens_out=tu.get("completion_tokens"))
    v2 = validate_v2(raw, res.blocks, manifest, fr.validation_spec)
    events.stage(ui, "writer", "done")
    events.stage(ui, "judge")
    ui.say("… 交叉核对与措辞审查")
    jchain = _chain(cfg, "judge")
    cross, judge_runs = {}, []
    for n, (fid, obs) in enumerate(vision_obs.items(), 1):
        claims, info = judge(next(m for m in manifest if m["id"] == fid), obs, res.blocks, jchain, llm_tx, env)
        cross[fid] = claims; judge_runs.append(info)
        events.progress(ui, "judge", n, len(vision_obs) + 1)
    winfo = wording_judge.apply(v2, res.blocks, cross, jchain, llm_tx, env)
    events.progress(ui, "judge", len(vision_obs) + 1, len(vision_obs) + 1)
    runs += judge_runs + [winfo]
    events.stage(ui, "judge", "done")
    lens = None
    if proj:   # R7: separate call AFTER the objective analysis is validated; never writes back
        events.stage(ui, "lens")
        ui.say("… 项目视角（只读取冻结的课题快照）")
        lens, linfo = lens_mod.run(proj.obj, v2, cfg.llm.chain("extract"), llm_tx, env)
        runs.append(linfo)
        if lens["status"] != "OK":
            ui.say(f"⚠️ 项目视角生成失败（{lens.get('failure')}），笔记中改为通用科研应用价值")
        else:   # review 2: a clean Lens run used to be silent, which looked like it had not run
            rej = len(lens.get("rejected") or [])
            ui.say(f"  项目视角：完成（相关程度：{(lens.get('relevance') or {}).get('level') or '未给出'}）"
                   + (f"；{rej} 条未通过校验，已删除（记入证据档案）" if rej else ""))
        receipt["lens"] = {"status": lens["status"], "rejected": len(lens.get("rejected") or []),
                           "relevance": (lens.get("relevance") or {}).get("level")}
        lu = (linfo or {}).get("usage") or {}
        events.progress(ui, "lens", 1, 1, tokens_in=lu.get("prompt_tokens"), tokens_out=lu.get("completion_tokens"))
        events.stage(ui, "lens", "done", relevance=receipt["lens"]["relevance"], status_code=lens["status"])
    else:
        events.stage(ui, "lens", "skip")

    # 6b) author order: Zotero vs PDF (review fix 10) -> UNKNOWN in the note + ask which name goes into the file name
    conflict = author_order_check(zm, res.blocks, ((raw.get("meta") or {}).get("authors") or {}).get("value"))
    events.stage(ui, "author") if conflict else events.stage(ui, "author", "skip")
    if conflict:
        zm["authors_conflict"] = conflict
        zm["first_author_for_name"] = choose_first_author(conflict, ui)
        v2.unknowns = unknown_rank.rank(v2.unknowns + [{"item": "元数据 第一作者顺序冲突", "why": (
            f"Zotero 第一作者为 {conflict['zotero_first']}，PDF 第一位为 {conflict['pdf_first']}（{conflict['evidence']}）；请在 Zotero 中核对")}])
        receipt["authors_conflict"] = {**conflict, "used_for_file_name": zm["first_author_for_name"]}
        events.stage(ui, "author", "done", zotero_first=conflict.get("zotero_first"), pdf_first=conflict.get("pdf_first"),
                     used=zm["first_author_for_name"])

    # 7) topic folder (reuse similar existing; new name needs confirmation)
    events.stage(ui, "topic")
    title_zh = v2.meta["title_zh"].get("value") or zm.get("title_en") or item.title
    receipt["paper"] = paper_info(zm, item, att, v2.meta["title_zh"].get("value"))
    real_papers = cfg.vault_root / cfg.papers_dir
    root = cfg.dry_run_root
    existing = sorted(set(topics.list_topics(real_papers)) | set(topics.list_topics(root / cfg.papers_dir)))
    tm = v2.data.get("three_minute") or {}
    summary = " ".join(str((tm.get(k) or {}).get("text") or "") for k in ("what", "how", "key_result"))
    sug = topics.suggest(existing, f"{title_zh} / {item.title}", summary,
                         [v2.data["_aux"].get("topic") or ""] + list(v2.data["_aux"].get("tags") or []), jchain, llm_tx, env)
    runs.append(sug)
    topic = choose_topic(sug, existing, ui)
    receipt["topic"] = {"folder": topic, "new": topic not in existing,
                        "suggestion": {k: sug.get(k) for k in ("choice", "folder", "reason", "status", "confident", "alternatives")}}

    events.stage(ui, "topic", "done", folder=topic, new=topic not in existing)

    # 8) write ONLY inside the dry-run sandbox
    events.stage(ui, "write")   # last cancel point: nothing has been written yet
    root.mkdir(parents=True, exist_ok=True)
    w = VaultWriter(Sandbox(root))
    if topic not in existing:   # a new folder: created exclusively, inside the dry-run sandbox only
        new_dir = w.sb.resolve(f"{cfg.papers_dir}/{topic}")
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            new_dir.mkdir()
        except FileExistsError:
            ui.say(f"  文件夹「{topic}」已存在，直接使用（不覆盖其中任何文件）")
    key = item.parent_key
    link_prefix = f"{cfg.dry_run_dir}/"   # Obsidian links are vault-root paths; files live under the output folder
    fig_paths = {}
    for m in manifest:
        for i, p in enumerate(m["parts"], 1):
            if not p.get("img_path"):          # e.g. an HTML-only table: nothing to copy
                continue
            src = ext / p["img_path"]
            if not src.is_file():
                continue
            rel = f"{cfg.papers_dir}/_图表/{key}/{m['id']}-{i}{src.suffix}"
            if not (root / rel).exists():
                w.create_exclusive(rel, src.read_bytes())
            fig_paths.setdefault(m["id"], []).append(link_prefix + rel)
    first = zm.get("first_author_for_name") or (zm.get("authors_full") or [None])[0]
    fam = family_of(zm, first)   # “——Shin2026”: the Zotero last name when this author is a Zotero author
    year = zm.get("year") or v2.meta["year"].get("value")
    note_dir = f"{cfg.papers_dir}/{topic}"
    ev_dir = f"{cfg.papers_dir}/_证据档案/{key}"
    stem = naming.choose(title_zh, first, year, key, taken=lambda c: (root / f"{note_dir}/{c}.md").exists(), family=fam)
    ev_stem = evidence_stem(stem, title_zh, key, bool(zm.get("authors_conflict")), first, year, fam,
                            taken=lambda c: (root / f"{ev_dir}/{c}.md").exists())
    ev_rel = f"{ev_dir}/{ev_stem}"
    notice = ("PDF 疑似中文译本（" + "；".join(sv.reasons) + "）；页码、引文对应本附件，与英文原版一致性 UNKNOWN。"
              if sv.flag == "TRANSLATION_SUSPECTED" else None)
    md = render(v2, blocks=res.blocks, manifest=manifest, vision_obs=vision_obs, figure_paths=fig_paths,
                attachment_key=att.key, parent_key=key, e_level=el.level, translation_notice=notice,
                link_mechanism_verified=cfg.link_mechanism_verified, read_date=date.today().isoformat(),
                evidence_link=link_prefix + ev_rel, model_info={"text": text_run["model"],
                                                                "vision": vision_runs[0].get("model") if vision_runs else None},
                crosscheck=cross, zotero_meta=zm, template=fr.main, modules=fr.modules, provenance=fr.provenance(),
                project=proj.view() if proj else None, lens=lens)
    ev = render_evidence(v2, raw=raw, blocks=res.blocks, manifest=manifest, attachment_key=att.key, title=stem,
                         runs=[text_run], vision_runs=vision_runs, e_report=receipt["extraction"])
    ev += "\n## 读图交叉核对与措辞审查\n\n```json\n" + json.dumps(
        {"judge_runs": judge_runs, "claims": cross, "wording_judge": winfo, "topic": sug, "template": fr.receipt()}, ensure_ascii=False,
        indent=1, default=str) + "\n```\n"
    if proj:
        ev += "\n## 项目视角（Project Lens）\n\n> 课题快照只用于个性化解读，不是原文证据。\n\n```json\n" + json.dumps(
            {"project": proj.evidence(), "lens": lens}, ensure_ascii=False, indent=1, default=str) + "\n```\n"
    w.create_exclusive(ev_rel + ".md", ev.encode())
    note = w.create_exclusive(f"{note_dir}/{stem}.md", md.encode())
    (job / "figures.json").write_text(json.dumps({"manifest": manifest, "vault_paths": fig_paths}, ensure_ascii=False,
                                                 indent=1), "utf-8")
    sha_after = sha256_file(pdf)
    if sha_after != sha_before:
        raise Stop("Zotero 中的原始 PDF 哈希发生变化！立即停止并报告")

    # 9) actual usage / cost
    act = actual_usage(cfg, runs)
    receipt.update(status="DRY_RUN_COMPLETE", note=str(root / note.rel_path), evidence=str(root / (ev_rel + ".md")),
                   pdf_sha_after=sha_after, stats=v2.stats,
                   wording_judge={k: winfo.get(k) for k in ("status", "candidates", "counts")}, actual=act,
                   tokens={"prompt": sum(a["in"] for a in act.values()), "completion": sum(a["out"] for a in act.values())},
                   finished=datetime.now().isoformat(timespec="seconds"))
    receipt["calibration"] = {
        "store": str(cal_store.path) if cal_store else None,
        "estimate": {r: t.get("calibration") for r, t in est["roles"].items()},
        "recorded": calibration.record(cal_store, est, act, item_key=item.parent_key, chars=est.get("chars"),
                                       figures=est.get("figures")) if cal_store else {}}
    rp = job / f"receipt-{datetime.now().strftime('%Y%m%dT%H%M%S%f')}.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=1, default=str), "utf-8")
    ctx["written"] = True
    receipt["receipt"] = str(rp)
    events.stage(ui, "write", "done")
    show_actual(act, est, ui)
    events.emit(ui, "done", note_path=receipt["note"], evidence_path=receipt["evidence"], receipt_path=receipt["receipt"],
                usage=act, estimate=est, topic=topic, e_level=el.level, title=item.title, item_key=item.parent_key)
    return receipt


def family_of(zm: dict, first: str | None) -> str | None:
    """Zotero last name of `first` if it is one of the Zotero authors, else None (naming derives it from the name)."""
    full, last = zm.get("authors_full") or [], zm.get("authors_last") or []
    return last[full.index(first)] if first in full and full.index(first) < len(last) else None


def evidence_stem(note_stem, title_zh, key, authors_conflict: bool, first, year, fam, taken) -> str:
    """G7-12: with an author-order conflict no author name goes into the evidence file name (it may be the wrong
    one) — the Zotero item key identifies it instead: 〈题名〉——〈KEY〉——证据档案.
    G10-3: otherwise it follows the final note stem (already unique, may carry ——姓年份 / 日期): 〈笔记名〉——证据档案.
    A collision only adds the date suffix, so neither the key nor the author is ever repeated."""
    if authors_conflict:
        return naming.choose_fixed(f"{title_zh or note_stem}——{key}——证据档案", taken)
    return naming.choose_fixed(f"{note_stem}——证据档案", taken)


def choose_first_author(conflict: dict, ui: UI) -> str:
    """Which author distinguishes the file name on a collision. Enter = the PDF order only when the PDF author order was
    read verbatim from the PDF text; when it comes from the writer's author string that failed the verbatim check,
    Enter = the Zotero order and the PDF name stays available as `p` (marked unverified)."""
    z, p = conflict["zotero_first"], conflict["pdf_first"]
    verified = bool(conflict.get("verified"))
    ui.say(f"⚠️ 作者顺序冲突：Zotero 的第一作者是「{z}」，但 PDF 里第一位是「{p}」"
           f"（依据：{conflict['evidence']}）。笔记里的作者会记为 UNKNOWN，请之后在 Zotero 里核对作者顺序。")
    if verified:
        q = f"文件名重名时用哪位作者区分？回车 = PDF 顺序「{p}」（已在 PDF 原文中找到） / z = Zotero 顺序「{z}」 / q 取消："
        default = p
        options = [events.opt("", f"PDF 顺序「{p}」", "已在 PDF 原文中找到（默认）"), events.opt("z", f"Zotero 顺序「{z}」")]
    else:
        ui.say("  PDF 的作者顺序来自模型读取的作者串，未通过逐字核对，所以默认用 Zotero 的顺序。")
        q = f"文件名重名时用哪位作者区分？回车 = Zotero 顺序「{z}」 / p = PDF 顺序「{p}」（未核实） / q 取消："
        default = z
        options = [events.opt("", f"Zotero 顺序「{z}」", "默认"), events.opt("p", f"PDF 顺序「{p}」", "未核实")]
    while True:
        a = events.decide(ui, "author", q, options, default="", data={"conflict": conflict}).strip().lower()
        if a == "":
            return default
        if a in ("p", "pdf"):
            return p
        if a in ("z", "zotero"):
            return z
        if a in ("q", "取消"):
            raise Cancelled("已取消：未写入任何笔记（解析结果已缓存，下次不再上传）")
        ui.say("请直接回车，或输入 p / z / q")


def choose_topic(sug: dict, existing: list[str], ui: UI) -> str:
    """Decision 4 (2026-10-18): a confident reuse of an existing folder is taken as before. Otherwise all suggestions are
    listed (a, b, c…: the main one first), then the existing folders (1, 2…), and any other text is a custom new folder
    name: sanitized, validated, matched case-insensitively to existing folders, and confirmed before it is created."""
    if sug["choice"] == "existing" and sug.get("confident", True):
        ui.say(f"主题文件夹：复用已有「{sug['folder']}」（{sug.get('reason') or '主题相近'}）")
        return sug["folder"]
    opts = [sug["folder"]] + [a for a in (sug.get("alternatives") or []) if a != sug["folder"]]
    if sug["choice"] == "existing":
        ui.say(f"主题文件夹拿不准：最接近的是已有「{sug['folder']}」（{sug.get('reason') or '主题相近'}）")
    else:
        ui.say(f"建议新建主题文件夹「{sug['folder']}」（{sug.get('reason') or '无相近的已有文件夹'}）")
    letters = "abc"
    if len(opts) > 1:
        ui.say("建议：")
        for k, o in zip(letters, opts):
            ui.say(f"  {k}. {o}（{'已有' if o in existing else '新建'}）")
    if existing:
        ui.say("也可以改用已有文件夹：")
        for i, n in enumerate(existing, 1):
            ui.say(f"  {i}. {n}")
    first = f"{'用' if opts[0] in existing else '新建'}「{opts[0]}」"
    q = (f"回车 = {first}" + (f" / {letters[:len(opts)][0]}–{letters[len(opts) - 1]} 选建议" if len(opts) > 1 else "")
         + (" / 序号改用已有" if existing else "") + " / 直接输入其他新名称 / q 取消：")
    options = [events.opt("" if i == 0 else k, o, ("已有" if o in existing else "新建") + ("（建议，回车）" if i == 0 else ""))
               for i, (k, o) in enumerate(zip(letters, opts))]
    options += [events.opt(str(i), n, "已有文件夹") for i, n in enumerate(existing, 1) if n not in opts]
    data = {"suggestion": {k: sug.get(k) for k in ("choice", "folder", "reason", "confident", "alternatives")},
            "existing": list(existing)}
    while True:
        a = events.decide(ui, "topic_folder", q, options, default="", allow_custom=True, data=data).strip()
        if a == "" or a.lower() in ("y", "yes", "是"):   # Enter accepts the suggestion (review UX fix)
            return opts[0]
        if a.lower() in ("q", "取消"):
            raise Cancelled("已取消：未写入任何笔记（解析结果已缓存，下次不再上传）")
        if len(opts) > 1 and len(a) == 1 and a.lower() in letters[:len(opts)]:
            return opts[letters.index(a.lower())]
        if a.isdigit():
            if existing and 1 <= int(a) <= len(existing):
                return existing[int(a) - 1]
            ui.say("序号不存在")
            continue
        name, problem = topics.clean_name(a, existing)
        if not name:
            ui.say(f"无效名称：{problem}")
            continue
        if name in existing:
            ui.say(f"已有同名文件夹「{name}」，直接使用")
            return name
        if name != a:
            ui.say(f"名称已整理为「{name}」（去掉了文件名不允许的字符）")
        if _yes(ui, f"确认新建「{name}」？(y/n)：", "confirm",
                options=[events.opt("y", f"新建「{name}」", "在笔记文件夹里创建"), events.opt("n", "重新选择")]):
            return name


def show_actual(act: dict, est: dict, ui: UI) -> None:
    ui.say("—— 实际用量 ——")
    tot, priced = 0.0, True
    for role, a in act.items():
        e = est["roles"].get(role)
        cmp_ = f"（估算 {e['in']:,}/{e['out']:,}）" if e else ""
        c = f"；¥{a['cost']:.3f}" if a["priced"] else "；费用：未填单价"
        priced &= a["priced"]; tot += a["cost"]
        ui.say(f"  {ROLES.get(role, role)}（{', '.join(a['models'])}）：输入 {a['in']:,}，输出 {a['out']:,} tokens{cmp_}{c}")
    if act:
        ui.say(f"  合计：¥{tot:.3f}" if priced else "  合计费用：部分模型未填单价")
