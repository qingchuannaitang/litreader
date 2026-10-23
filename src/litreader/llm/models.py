"""Model settings (user decision 2026-10-17): three roles, each primary + up to 3 backups.

Each slot has 4 user fields: vendor (厂商名称, free display label), model (模型名, typed by the user), url
(OpenAI-compatible base URL), key_ref (name of the API key in the keychain; the key itself never touches a file).
Optional: price_in / price_out (元/百万 tokens, only if the user fills them), and advanced json_mode / max_tokens /
timeout_s / extra_body (filled from a verified preset when the URL matches one).
Stored in models.toml next to config.local.toml. No built-in model list.
"""
from __future__ import annotations

from litreader.platform_words import keystore_name as _kn
import base64
import json
import re
import struct
import tomllib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import presets
from .config import MAX_CHAIN, ConfigError, LLMConfig, ProviderConfig

ROLES = {"writer": "主笔", "vision": "看图", "judge": "交叉核对"}
STATION = {"writer": "extract", "vision": "vision", "judge": "judge"}
ROLE_ALIASES = {"主笔": "writer", "看图": "vision", "交叉核对": "judge", "writer": "writer", "vision": "vision",
                "judge": "judge", "text": "writer"}
SLOT_NAMES = ["主用", "备用1", "备用2", "备用3"]
SHARED_VISION_ID = "vision_shared"
SHARE_TARGETS = {"writer"}


@dataclass
class Slot:
    vendor: str
    model: str
    url: str
    key_ref: str
    price_in: float | None = None
    price_out: float | None = None
    json_mode: bool | None = None
    max_tokens: int | None = None
    timeout_s: float | None = None
    extra_body: dict | None = None
    supports_vision: bool | None = None   # G12-3: user-confirmed (from vendor docs); only used for 「与主笔共用」

    def validate(self, where: str) -> None:
        for k in ("vendor", "model", "url", "key_ref"):
            if not str(getattr(self, k) or "").strip():
                raise ConfigError(f"{where}: 缺少 {k}")
        if not (self.url.startswith("https://") or self.url.startswith("http://localhost")):
            raise ConfigError(f"{where}: URL 必须以 https:// 开头（本机服务可用 http://localhost）")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", self.key_ref):
            raise ConfigError(f"{where}: key_ref 只能含字母/数字/_-.")
        for p in ("price_in", "price_out"):
            v = getattr(self, p)
            if v is not None and (not isinstance(v, (int, float)) or v < 0):
                raise ConfigError(f"{where}: {p} 必须是非负数字（元/百万 tokens）")


@dataclass
class ModelSettings:
    roles: dict[str, list[Slot]] = field(default_factory=lambda: {r: [] for r in ROLES})
    vision_share: str | None = None       # G12-3: "writer" = 看图 uses the 主笔 主用 slot ([share] vision = "writer")

    def shared_vision_slot(self) -> Slot | None:
        if self.vision_share == "writer" and self.roles["writer"]:
            return self.roles["writer"][0]
        return None

    def slot_id(self, role: str, i: int) -> str:
        return f"{role}{i + 1}"

    def find(self, provider_id: str) -> Slot | None:
        if self.vision_share == "writer" and provider_id == SHARED_VISION_ID:
            return self.shared_vision_slot()
        for r, slots in self.roles.items():
            for i, s in enumerate(slots):
                if self.slot_id(r, i) == provider_id:
                    return s
        return None

    def to_llm_config(self, require_writer: bool = True) -> LLMConfig:
        provs, stations = {}, {}
        if self.vision_share is not None and self.vision_share not in SHARE_TARGETS:
            raise ConfigError(f"[share] vision 只能是 writer（与主笔共用），不是 {self.vision_share!r}")
        for role, slots in self.roles.items():
            if role == "vision" and self.vision_share:
                continue          # stored vision slots are kept but not used while 「与主笔共用」 is on
            if len(slots) > MAX_CHAIN:
                raise ConfigError(f"{ROLES[role]}：最多 1 个主用 + 3 个备用")
            ids = []
            for i, s in enumerate(slots):
                pid = self.slot_id(role, i)
                s.validate(f"{ROLES[role]}·{SLOT_NAMES[i]}")
                pre = presets.by_url(s.url) or {}
                jm = s.json_mode if s.json_mode is not None else (pre.get("json_mode", role != "vision"))
                mt = s.max_tokens or pre.get("max_tokens") or (2048 if role == "vision" else None)
                if role == "vision" and mt and mt > 4096:
                    mt = 2048
                provs[pid] = ProviderConfig(
                    pid, "openai_compatible", s.url.rstrip("/"), s.model, s.key_ref,
                    True if role == "vision" else None, float(s.timeout_s or (180 if role == "vision" else 300)),
                    s.extra_body if s.extra_body is not None else pre.get("extra_body"),
                    bool(jm) if role != "vision" else False, mt)
                ids.append(pid)
            if ids:
                stations[STATION[role]] = ids
        sv = self.shared_vision_slot()
        if sv is not None:
            if sv.supports_vision is not True:
                raise ConfigError("看图「与主笔共用」：主笔主用模型未标记为支持看图（请先在厂商文档确认后勾选「支持看图」）")
            pre = presets.by_url(sv.url) or {}
            provs[SHARED_VISION_ID] = ProviderConfig(
                SHARED_VISION_ID, "openai_compatible", sv.url.rstrip("/"), sv.model, sv.key_ref, True,
                180.0, sv.extra_body if sv.extra_body is not None else pre.get("extra_body"), False, 2048)
            stations["vision"] = [SHARED_VISION_ID]
        if require_writer and "extract" not in stations:
            raise ConfigError("主笔模型未设置：运行 litreader models set 主笔")
        return LLMConfig(provs, stations)


def load(path: Path) -> ModelSettings:
    with open(path, "rb") as f:
        d = tomllib.load(f)
    ms = ModelSettings()
    for role in ROLES:
        rows = d.get(role) or []
        if not isinstance(rows, list):
            raise ConfigError(f"models.toml: [{role}] 应写成 [[{role}]] 列表")
        for r in rows:
            ms.roles[role].append(Slot(**{k: r.get(k) for k in Slot.__dataclass_fields__ if k in r}
                                       | {k: r.get(k, "") for k in ("vendor", "model", "url", "key_ref")}))
    share = d.get("share") or {}
    if not isinstance(share, dict):
        raise ConfigError("models.toml: [share] 应是一个表")
    ms.vision_share = share.get("vision") or None
    ms.to_llm_config(require_writer=False)  # validate slots
    return ms


def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_val(x)}" for k, x in v.items()) + " }"
    return json.dumps(str(v), ensure_ascii=False)


def dumps(ms: ModelSettings) -> str:
    out = ["# litreader 模型设置（由 `litreader models set` 维护，可手工编辑）。不含任何 API Key：",
           f"# key_ref 是{_kn()}里的名称（litreader models set 时输入 Key 即存入{_kn()}）。",
           "# price_in / price_out：可选，元/百万 tokens（你自己从厂商价目表抄写；程序不内置价格）。", ""]
    for role, label in ROLES.items():
        out.append(f"# ===== {label}（{role}）：第 1 个为主用，其后最多 3 个备用 =====")
        for i, s in enumerate(ms.roles[role]):
            out.append(f"[[{role}]]   # {SLOT_NAMES[i]}")
            for k in Slot.__dataclass_fields__:
                v = getattr(s, k)
                if v is not None and v != "":
                    out.append(f"{k} = {_val(v)}")
            out.append("")
        out.append("")
    if ms.vision_share:
        out += ["# ===== 共用（G12）：看图与主笔共用主笔的主用模型和 Key（旧版本会忽略这一节）=====", "[share]",
                f"vision = {_val(ms.vision_share)}", ""]
    return "\n".join(out)


def save(ms: ModelSettings, path: Path) -> None:
    ms.to_llm_config(require_writer=False)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps(ms), "utf-8")
    tomllib.loads(tmp.read_text("utf-8"))
    tmp.replace(path)


def default_key_ref(vendor: str, url: str, role: str, idx: int) -> str:
    pre = presets.by_url(url) or presets.by_vendor(vendor)
    if pre:
        return pre["key_ref"]
    a = re.sub(r"[^A-Za-z0-9]+", "_", vendor or "").strip("_").upper()
    return f"{a}_API_KEY" if a else f"{role.upper()}_{idx + 1}_API_KEY"


def migrate_legacy(d: dict) -> ModelSettings:
    """Old config.local.toml [providers]/[stations] -> ModelSettings (keys stay under the same keychain names)."""
    provs = d.get("providers") or {}
    ms = ModelSettings()
    inv = {v: k for k, v in STATION.items()}
    for st, ids in (d.get("stations") or {}).items():
        role = inv.get(st)
        if not role:
            continue
        for pid in ids[:MAX_CHAIN]:
            p = provs[pid]
            pre = presets.by_url(p.get("base_url", ""))
            ms.roles[role].append(Slot(vendor=(pre or {}).get("label") or pid, model=p.get("model", ""),
                                       url=p.get("base_url", ""), key_ref=p.get("key_env", ""),
                                       json_mode=p.get("json_mode"), max_tokens=p.get("max_tokens"),
                                       timeout_s=p.get("timeout_s"), extra_body=p.get("extra_body")))
    return ms


# ---------- connectivity test ----------
# Probes (chosen after real trials on DeepSeek / MiniMax, 2026-10-17):
# - The old text probe (a bare user line containing a literal JSON example, no system message) made the DeepSeek text model in
#   JSON mode emit broken JSON most of the time ('{"ok":##"}', 7/8 failures), with or without the 64-token cap. A
#   system line + a tiny task is 16/16 valid. Real runs always send a system prompt and were never affected.
# - The old vision probe (64×64 flat red square) was ambiguous to the MiniMax vision model (3/8 "红"; also 蓝/绿/白/黑). A red disc on
#   a white 256×256 background is 16/16 "红". The PNG itself was correct (RGB 220,30,30).
TEXT_PROBE = [{"role": "system", "content": "你是一个只输出 JSON 的接口。只输出一个 JSON 对象，不要任何其他文字。"},
              {"role": "user", "content": "连通性测试：请返回一个 JSON 对象，包含两个键：status（字符串 \"ok\"）和 sum（数字，等于 2+3）。"}]
VISION_QUESTION = "图片中间的圆形是什么颜色？只能从 红、绿、蓝、黄 中选一个字回答。"


def _png(size: int, px) -> bytes:
    raw = b"".join(b"\x00" + b"".join(bytes(px(x, y)) for x in range(size)) for y in range(size))

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def tiny_png(rgb=(220, 30, 30), size=64) -> bytes:
    """Flat colour square (kept for callers/tests); NOT used as the vision probe any more."""
    return _png(size, lambda x, y: rgb)


def probe_png(size: int = 256) -> bytes:
    """Red (220,30,30) disc, radius 80, centred on white — RGB, 8-bit, standard PNG."""
    c = size // 2
    return _png(size, lambda x, y: (220, 30, 30) if (x - c) ** 2 + (y - c) ** 2 < 80 ** 2 else (255, 255, 255))


def redact(text: str, env, key_env: str) -> str:
    t = text or ""
    try:
        k = env.get(key_env, "")
    except Exception:  # noqa: BLE001
        k = ""
    if k and len(k) >= 6:
        t = t.replace(k, "«KEY»")
    t = re.sub(r"(?i)bearer\s+\S+", "Bearer «KEY»", t)
    return re.sub(r"\b(sk|key|tok)[-_][A-Za-z0-9_\-]{8,}", "«KEY»", t)


def test_slot(p: ProviderConfig, role: str, transport, env) -> dict:
    """Tiny real call through the SAME request builder as real runs (client.build_request via chat; the slot's
    json_mode / max_tokens / extra_body unchanged). Returns {ok, category, detail, latency_s, usage, request, raw};
    never includes the key (request is a summary without messages/headers; raw is redacted and ≤300 chars)."""
    import time
    from dataclasses import replace
    from .client import ProviderError, build_request, chat, LAST_USAGE
    if role == "vision":
        b64 = base64.b64encode(probe_png()).decode()
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": VISION_QUESTION},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
    else:
        msgs = TEXT_PROBE
    try:
        req = build_request(p, msgs)
    except ProviderError as e:
        return {"ok": False, "category": e.category, "detail": e.detail}
    summary = {"url": f"{p.base_url}/chat/completions", **{k: v for k, v in req.items() if k != "messages"}}
    raw_seen = {}

    def tx(url, headers, body, timeout):
        st, b = transport(url, headers, body, timeout)
        raw_seen["status"], raw_seen["body"] = st, b
        return st, b

    t0 = time.monotonic()
    try:
        text = chat(p, msgs, tx, env)
    except ProviderError as e:
        res = {"ok": False, "category": e.category, "detail": e.detail, "request": summary,
               "raw": redact((raw_seen.get("body") or b"")[:300].decode("utf-8", "replace"), env, p.key_env)}
        if e.category == "HTTP_400" and p.json_mode:
            try:
                chat(replace(p, json_mode=False), msgs, transport, env)
                res["hint"] = "该厂商可能不支持 JSON 模式：在 models.toml 此槽位加 json_mode = false"
            except ProviderError:
                pass
        return res
    out = {"ok": bool((text or "").strip()), "category": "OK", "latency_s": round(time.monotonic() - t0, 2),
           "usage": dict(LAST_USAGE), "request": summary, "raw": redact((text or "")[:300], env, p.key_env)}
    if role == "vision":
        out["detail"] = "识别正确（红）" if re.search(r"红|red", text or "", re.I) else f"已回复但未认出红色：{(text or '')[:20]}"
    else:
        try:
            from .jsonparse import loads_lenient   # the same parser real runs use
            d = loads_lenient(text or "")
            if not isinstance(d, dict):
                raise ValueError
            out["detail"] = "JSON 正常" if str(d.get("sum")) in ("5", "5.0") else "JSON 正常（内容与预期不同，不影响使用）"
        except (ValueError, TypeError):
            out["detail"] = "已回复，但不是合法 JSON（主笔/核对需要 JSON；加 --verbose 查看原始回复）"
            out["ok"] = False
            out["category"] = "NOT_JSON"
    return out
