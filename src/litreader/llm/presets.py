"""Vendor presets: ONLY prefill a base URL (and request switches) that were verified for this project.
No model names here — the user types model ids. Unknown vendors get no preset (URL left blank, never guessed).

Sources:
- DeepSeek: docs/spikes/S0_llm.md + STAGE_LOG Stage 3 (api-docs.deepseek.com: thinking switch, JSON output; real calls).
- MiniMax: docs/spikes/S0_vision_minimax.md (China host verified with real calls; intl host documented on
  platform.minimax.io, keys are NOT interchangeable between hosts; thinking disabled verified on China host).
- Re-checked 2026-10-18 against the official docs (WebFetch; no API call made):
  - DeepSeek  https://api-docs.deepseek.com/  -> base_url (OpenAI) https://api.deepseek.com
  - MiniMax intl  https://platform.minimax.io/docs/api-reference/text-openai-api -> https://api.minimax.io/v1
  - OpenAI  https://platform.openai.com/docs/api-reference/chat/create -> https://api.openai.com/v1/chat/completions
  - Google Gemini  https://ai.google.dev/gemini-api/docs/openai -> https://generativelanguage.googleapis.com/v1beta/openai/
  - Anthropic Claude  https://docs.anthropic.com/en/api/openai-sdk -> https://api.anthropic.com/v1/ (OpenAI SDK
    compatibility layer; Anthropic says it is "primarily intended to test and compare", and `response_format` is
    ignored, so json_mode stays off). litreader only speaks the OpenAI chat-completions format, so this layer is
    used; the native Messages API is not implemented. "Claude Code" is a CLI product, not an API: use this preset.
  key_page links are the vendors' official key consoles (reachability checked with curl only: Google/Anthropic 200,
  OpenAI 403 to scripts / bot protection); they are opened in the system browser, never embedded.
  None of these presets sets a model name; json_mode is only on where it was verified with real calls (DeepSeek).
- Added 2026-10-19 (stage G6), base URLs read from the official quick-start pages (WebFetch; NO API call made, so
  these four are "URL verified from docs, not verified with a real call" -> `unverified_call=True`, json_mode off):
  - Kimi / Moonshot China  https://platform.moonshot.cn/docs/guide/start-using-kimi-api (now platform.kimi.com)
    -> base_url https://api.moonshot.cn/v1 ; key console https://platform.kimi.com/console/api-keys
  - Kimi / Moonshot international  https://platform.moonshot.ai/docs/guide/start-using-kimi-api (now platform.kimi.ai)
    -> base_url https://api.moonshot.ai/v1 ; key console https://platform.kimi.ai/console/api-keys
  - 智谱 GLM BigModel (China)  https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
    -> base_url https://open.bigmodel.cn/api/paas/v4/ ; key console https://open.bigmodel.cn/usercenter/apikeys
  - 智谱 GLM Z.ai (international)  https://docs.z.ai/guides/develop/openai/python
    -> base_url https://api.z.ai/api/paas/v4/ ; key console https://z.ai/manage-apikey/apikey-list
  Keys of the China and international hosts are separate accounts (each host has its own console).
"""
from __future__ import annotations

from litreader.platform_words import keystore_name as _kn
from urllib.parse import urlsplit

PRESETS = [
    {"id": "deepseek", "names": ("deepseek", "深度求索"), "label": "DeepSeek",
     "url": "https://api.deepseek.com", "key_ref": "DEEPSEEK_API_KEY",
     "json_mode": True, "max_tokens": 32000, "extra_body": {"thinking": {"type": "disabled"}}},
    {"id": "minimax_cn", "names": ("minimax", "minimax中国", "minimax国内", "minimax 中国", "minimax 国内", "海螺"),
     "label": "MiniMax（中国站）", "url": "https://api.minimaxi.com/v1", "key_ref": "MINIMAX_API_KEY",
     "json_mode": False, "extra_body": {"thinking": {"type": "disabled"}}},
    {"id": "minimax_intl", "names": ("minimax国际", "minimax 国际", "minimax intl", "minimax international"),
     "label": "MiniMax（国际站）", "url": "https://api.minimax.io/v1", "key_ref": "MINIMAX_INTL_API_KEY",
     "json_mode": False, "extra_body": {"thinking": {"type": "disabled"}}},
    {"id": "openai", "names": ("openai", "chatgpt", "openai (chatgpt)", "gpt"), "label": "OpenAI（ChatGPT）",
     "url": "https://api.openai.com/v1", "key_ref": "OPENAI_API_KEY", "json_mode": False,
     "doc": "https://platform.openai.com/docs/api-reference/chat/create", "key_page": "https://platform.openai.com/api-keys"},
    {"id": "gemini", "names": ("gemini", "google", "google gemini", "谷歌"), "label": "Google Gemini",
     "url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_ref": "GEMINI_API_KEY", "json_mode": False,
     "doc": "https://ai.google.dev/gemini-api/docs/openai", "key_page": "https://aistudio.google.com/apikey"},
    {"id": "anthropic", "names": ("anthropic", "claude", "anthropic claude", "claude code"), "label": "Anthropic Claude",
     "url": "https://api.anthropic.com/v1", "key_ref": "ANTHROPIC_API_KEY", "json_mode": False,
     "doc": "https://docs.anthropic.com/en/api/openai-sdk", "key_page": "https://console.anthropic.com/settings/keys",
     "note": "使用 Anthropic 官方的 OpenAI 兼容层（官方说明主要用于测试对比；不支持 JSON 模式开关）。Claude Code 是命令行工具，不是 API。"},
    {"id": "kimi_cn", "names": ("kimi", "moonshot", "月之暗面", "kimi中国", "moonshot中国"), "label": "Kimi（Moonshot 中国站）",
     "url": "https://api.moonshot.cn/v1", "key_ref": "MOONSHOT_API_KEY", "json_mode": False, "unverified_call": True,
     "doc": "https://platform.kimi.com/docs/guide/start-using-kimi-api", "key_page": "https://platform.kimi.com/console/api-keys"},
    {"id": "kimi_intl", "names": ("kimi国际", "kimi 国际", "moonshot intl", "kimi international", "moonshot international"),
     "label": "Kimi（Moonshot 国际站）", "url": "https://api.moonshot.ai/v1", "key_ref": "MOONSHOT_INTL_API_KEY",
     "json_mode": False, "unverified_call": True,
     "doc": "https://platform.kimi.ai/docs/guide/start-using-kimi-api", "key_page": "https://platform.kimi.ai/console/api-keys"},
    {"id": "glm_cn", "names": ("glm", "智谱", "zhipu", "bigmodel", "智谱glm", "智谱 glm"), "label": "智谱 GLM（BigModel 中国站）",
     "url": "https://open.bigmodel.cn/api/paas/v4", "key_ref": "ZHIPU_API_KEY", "json_mode": False, "unverified_call": True,
     "doc": "https://docs.bigmodel.cn/cn/guide/develop/openai/introduction",
     "key_page": "https://open.bigmodel.cn/usercenter/apikeys"},
    {"id": "glm_intl", "names": ("z.ai", "zai", "glm国际", "glm 国际", "glm international"), "label": "智谱 GLM（Z.ai 国际站）",
     "url": "https://api.z.ai/api/paas/v4", "key_ref": "ZAI_API_KEY", "json_mode": False, "unverified_call": True,
     "doc": "https://docs.z.ai/guides/develop/openai/python", "key_page": "https://z.ai/manage-apikey/apikey-list"},
]
for _p in PRESETS:
    if _p.get("unverified_call"):
        _p.setdefault("note", "Base URL 已按官方文档核对（2026-10-19），但还没有用真实调用验证；先点“测试连接”确认。"
                              "中国站和国际站是不同账号，Key 不通用。")
for _p in PRESETS:
    _p.setdefault("doc", {"deepseek": "https://api-docs.deepseek.com/",
                          "minimax_intl": "https://platform.minimax.io/docs/api-reference/text-openai-api"}.get(_p["id"]))

# GUI vendor dropdown order (decision 2026-10-18). "custom" = 自定义 / 中转站: no preset, the user types the URL.
CHOICES = ["openai", "gemini", "anthropic", "minimax_cn", "minimax_intl", "deepseek", "kimi_cn", "kimi_intl", "glm_cn",
           "glm_intl", "custom"]
CUSTOM = {"id": "custom", "names": (), "label": "自定义 / 中转站", "url": "", "key_ref": "", "json_mode": False,
          "note": f"填写中转站或其他厂商提供的 OpenAI 兼容 Base URL（通常以 /v1 结尾）。Key 只存{_kn()}。"}


def by_id(pid: str) -> dict | None:
    return CUSTOM if pid == "custom" else next((p for p in PRESETS if p["id"] == pid), None)


def choices() -> list[dict]:
    return [by_id(i) for i in CHOICES]


def _n(s: str) -> str:
    return "".join((s or "").lower().split())


def by_vendor(vendor: str) -> dict | None:
    v = _n(vendor)
    for p in sorted(PRESETS, key=lambda p: -max(len(_n(n)) for n in p["names"])):
        if any(v == _n(n) for n in p["names"]) or v == _n(p["label"]):
            return p
    return None


def by_url(url: str) -> dict | None:
    host = urlsplit(url or "").netloc.lower()
    for p in PRESETS:
        if host and host == urlsplit(p["url"]).netloc:
            return p
    return None
