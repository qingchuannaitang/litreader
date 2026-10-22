"""Project archive model (design §2.3; spec §6.2): eight modules, fixed item keys, four states, sources.

A project VERSION object (canonical JSON, content-addressed in the project registry):
  {"schema": 1, "project_id", "version", "parent_sha", "created", "folder", "status": "ACTIVE"|"ARCHIVED",
   "items": {key: [value, ...]}, "change": {"op", "summary", "source"}}
value = {"value", "state", "source": {"kind", "role", "file"?, "locator"?, "quote"?}, "confirmed_at"?, "updated_at",
         "note"?, "conflict"?}
Rules enforced here (not by callers): AI-derived content can never be CONFIRMED unless the user confirmed it at the
confirmation screen (source.confirmed_by == "user"); SUGGESTION never enters the summary.
"""
from __future__ import annotations

import json
import secrets as _rand
from datetime import datetime

from ..errors import Stop

STATES = ("CONFIRMED", "PENDING", "UNDECIDED", "SUGGESTION")
STATE_ZH = {"CONFIRMED": "已确认", "PENDING": "待确认", "UNDECIDED": "未定", "SUGGESTION": "研究建议"}
KINDS = ("用户输入", "用户编辑", "文件明确写出", "AI 归纳")
ROLES = ("用户确认", "作者提出", "导师建议", "其他")
USER_KINDS = ("用户输入", "用户编辑")
MAX_VALUE = 600
SUMMARY_MAX = 1500

MODULES = [
    ("01", "基本信息", [("formal_title", "正式题目"), ("working_title", "工作题目"), ("discipline", "学科"),
                       ("project_status", "项目状态")]),
    ("02", "研究背景", [("motivation", "临床/科研动机"), ("evidence_gap", "已有证据不足")]),
    ("03", "科学问题", [("core_question", "核心问题"), ("hypothesis", "研究假设"), ("aims", "研究目标")]),
    ("04", "对象与设计", [("population", "目标人群"), ("groups", "分组"), ("inclusion", "纳入标准"),
                         ("exclusion", "排除标准"), ("design", "研究设计"), ("reference_standard", "参考标准")]),
    ("05", "方法与技术", [("tasks", "实验任务"), ("devices", "设备"), ("acquisition", "采集与处理"),
                         ("tech_route", "技术路线")]),
    ("06", "研究指标", [("primary_outcomes", "主要指标"), ("secondary_outcomes", "次要指标"),
                       ("exploratory_outcomes", "探索性指标"), ("operational_definitions", "操作定义")]),
    ("07", "统计与建模", [("statistics", "统计方案"), ("features_models", "特征与模型"), ("validation", "验证方案"),
                         ("missing_data", "缺失处理")]),
    ("08", "当前进度", [("done", "已完成"), ("open_issues", "未解决问题"), ("advisor_notes", "导师意见")]),
]
KEYS = {k: (mid, mname, zh) for mid, mname, items in MODULES for k, zh in items}
ZH2KEY = {zh: k for k, (_, _, zh) in KEYS.items()}
# spec §6.3.3: the five items confirmed on one screen after an import
KEY5 = [("title", "题目", ("formal_title", "working_title")), ("question", "科学问题", ("core_question",)),
        ("population", "研究对象", ("population",)), ("methods", "已定方法", ("design", "tasks", "tech_route")),
        ("outcomes", "重要指标", ("primary_outcomes",))]
# changes to these need an item-by-item decision (spec §6.4 影响研究方向/核心方案)
CORE = ("formal_title", "working_title", "core_question", "hypothesis", "aims", "population", "groups", "design",
        "reference_standard")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return f"p{datetime.now().strftime('%Y%m%d')}-{_rand.token_hex(2)}"


def value(text: str, state: str, kind: str, role: str = "用户确认", *, file=None, locator=None, quote=None,
          confirmed_by: str | None = None, note: str | None = None, conflict: str | None = None) -> dict:
    v = {"value": " ".join(str(text).split())[:MAX_VALUE], "state": state,
         "source": {"kind": kind, "role": role}, "updated_at": now_iso()}
    for k, x in (("file", file), ("locator", locator), ("quote", quote), ("confirmed_by", confirmed_by)):
        if x:
            v["source"][k] = x
    if state == "CONFIRMED":
        v["confirmed_at"] = v["updated_at"]
    if note:
        v["note"] = note
    if conflict:
        v["conflict"] = conflict
    return v


def check(obj: dict) -> None:
    """Gate (ROADMAP Stage 7 禁止项): refuse any object where AI-derived content is CONFIRMED without the user."""
    for k, vals in obj["items"].items():
        if k not in KEYS:
            raise Stop(f"课题档案含未知条目 {k}，拒绝")
        for v in vals:
            if v["state"] not in STATES:
                raise Stop(f"课题条目 {k} 状态非法：{v['state']}")
            s = v["source"]
            if s.get("kind") not in KINDS or s.get("role") not in ROLES:
                raise Stop(f"课题条目 {k} 来源非法")
            if v["state"] == "CONFIRMED" and s["kind"] not in USER_KINDS and s.get("confirmed_by") != "user":
                raise Stop(f"拒绝：条目「{KEYS[k][2]}」来自{s['kind']}，未经你确认不能标为已确认")


def blank(project_id: str, folder: str) -> dict:
    return {"schema": 1, "project_id": project_id, "version": 0, "parent_sha": None, "created": now_iso(),
            "folder": folder, "status": "ACTIVE", "items": {}, "change": {}}


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def title_of(obj: dict) -> str:
    for k in ("formal_title", "working_title"):
        for v in obj["items"].get(k) or []:
            if v["state"] == "CONFIRMED":
                return v["value"]
    for k in ("formal_title", "working_title"):
        for v in obj["items"].get(k) or []:
            return v["value"]
    return "（未命名课题）"


def confirmed(obj: dict, key: str) -> list[str]:
    return [v["value"] for v in obj["items"].get(key) or [] if v["state"] == "CONFIRMED"]


def item_state(obj: dict, key: str) -> str:
    vals = obj["items"].get(key) or []
    if any(v["state"] == "CONFIRMED" for v in vals):
        return "CONFIRMED"
    if any(v["state"] == "PENDING" for v in vals):
        return "PENDING"
    return "UNDECIDED"


def summary(obj: dict) -> str:
    """Design §2.4: the ONLY project text ever sent to a model. CONFIRMED values; everything else shows 未定."""
    lines = [f"课题：{title_of(obj)}（{obj['project_id']} v{obj['version']}）"]
    dropped = 0
    for mid, mname, items in MODULES:
        parts = []
        for k, zh in items:
            vals = confirmed(obj, k)
            parts.append(f"{zh}：{'；'.join(vals)}" if vals else f"{zh}：未定")
        line = f"{mid} {mname}｜" + "｜".join(parts)
        if sum(len(x) for x in lines) + len(line) > SUMMARY_MAX:
            dropped += sum(1 for k, _ in items if confirmed(obj, k))
            continue
        lines.append(line)
    if dropped:
        lines.append(f"（另有 {dropped} 项已确认内容因长度上限未纳入）")
    return "\n".join(lines)


def counts(obj: dict) -> dict:
    out = {s: 0 for s in STATES}
    for k in KEYS:
        st = item_state(obj, k)
        out[st] += 1
    out["SUGGESTION"] = sum(1 for vals in obj["items"].values() for v in vals if v["state"] == "SUGGESTION")
    return out
