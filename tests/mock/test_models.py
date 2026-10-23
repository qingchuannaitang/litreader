"""Model settings (roles × primary+3 backups), presets, CLI models list/set/test/migrate, intent, topics, estimate."""
import base64
import json
import tomllib
from pathlib import Path

import pytest

from litreader import appconfig, cli, estimate, intent, secrets
from litreader.llm import models as M
from litreader.llm import presets
from litreader.llm.config import ConfigError
from litreader.vault import topics

ROOT = Path(__file__).resolve().parents[2]


class MemKeyring:
    def __init__(self):
        self.d = {}
    def get_password(self, s, n):
        return self.d.get((s, n))
    def set_password(self, s, n, v):
        self.d[(s, n)] = v
    def delete_password(self, s, n):
        self.d.pop((s, n))
    def get_keyring(self):
        return self


@pytest.fixture
def kr(monkeypatch):
    k = MemKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: k)
    for n in ("DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(n, raising=False)
    return k


@pytest.fixture
def home(tmp_path, monkeypatch):
    (tmp_path / "v").mkdir()
    s = (ROOT / "config.example.toml").read_text("utf-8").replace('root = ""', f'root = "{(tmp_path / "v").as_posix()}"', 1)
    (tmp_path / "config.local.toml").write_text(s, "utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def feed(monkeypatch, answers, keys=()):
    a, k = list(answers), list(keys)
    monkeypatch.setattr("builtins.input", lambda p="": a.pop(0))
    monkeypatch.setattr(cli.getpass, "getpass", lambda p="": k.pop(0) if k else "")


def test_presets_only_verified_urls_no_models():
    assert presets.by_vendor("DeepSeek")["url"] == "https://api.deepseek.com"
    assert presets.by_vendor("minimax")["url"] == "https://api.minimaxi.com/v1"
    assert presets.by_vendor("MiniMax 国际")["url"] == "https://api.minimax.io/v1"
    assert presets.by_vendor("通义") is None and presets.by_vendor("Tongyi") is None
    # 2026-10-18 vendor dropdown: official OpenAI-compatible base URLs, checked against the vendors' docs
    assert presets.by_vendor("Gemini")["url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert presets.by_vendor("ChatGPT")["url"] == "https://api.openai.com/v1"
    assert presets.by_vendor("Claude")["url"] == "https://api.anthropic.com/v1"
    assert presets.by_vendor("Claude Code")["id"] == "anthropic"   # a CLI product, not an API: use the Anthropic API
    assert presets.by_vendor("MiniMax（国际站）")["id"] == "minimax_intl"   # GUI label round-trips
    assert [c["id"] for c in presets.choices()] == ["openai", "gemini", "anthropic", "minimax_cn", "minimax_intl",
                                                    "deepseek", "kimi_cn", "kimi_intl", "glm_cn", "glm_intl", "custom"]
    assert presets.by_id("custom")["url"] == "" and all(p["url"].startswith("https://") for p in presets.PRESETS)
    assert not any(p["json_mode"] for p in presets.PRESETS if p["id"] in ("openai", "gemini", "anthropic"))
    assert all("model" not in p for p in presets.PRESETS)


def test_kimi_and_glm_presets_g6():
    """Stage G6: base URLs from the official quick-start pages (China + international hosts); not yet verified with a
    real call, so json_mode stays off and the GUI note says so."""
    want = {"kimi_cn": "https://api.moonshot.cn/v1", "kimi_intl": "https://api.moonshot.ai/v1",
            "glm_cn": "https://open.bigmodel.cn/api/paas/v4", "glm_intl": "https://api.z.ai/api/paas/v4"}
    for pid, url in want.items():
        p = presets.by_id(pid)
        assert p["url"] == url and not url.endswith("/") and p["unverified_call"] and not p["json_mode"]
        assert p["doc"].startswith("https://") and p["key_page"].startswith("https://") and "真实调用" in p["note"]
        assert presets.by_url(url + "/chat/completions")["id"] == pid      # existing slots map back to the preset
    assert presets.by_vendor("Kimi")["id"] == "kimi_cn" and presets.by_vendor("智谱")["id"] == "glm_cn"
    assert presets.by_vendor("Z.ai")["id"] == "glm_intl" and presets.by_vendor("Moonshot")["id"] == "kimi_cn"
    assert len({p["key_ref"] for p in presets.PRESETS}) == len(presets.PRESETS)   # separate keychain names per host


def test_roundtrip_and_chain_order_and_limits(tmp_path):
    ms = M.ModelSettings()
    for i in range(4):
        ms.roles["writer"].append(M.Slot(f"V{i}", f"m{i}", "https://api.deepseek.com", "DEEPSEEK_API_KEY",
                                         price_in=2.0 if i == 0 else None, price_out=8.0 if i == 0 else None))
    ms.roles["vision"].append(M.Slot("Gemini", "g-vis", "https://example.invalid/v1", "GEMINI_API_KEY"))
    p = tmp_path / "models.toml"
    M.save(ms, p)
    txt = p.read_text("utf-8")
    import re
    assert "sk-" not in txt and not re.search(r"^(api_key|key)\s*=", txt, re.M)
    back = M.load(p)
    llm = back.to_llm_config()
    assert [x.model for x in llm.chain("extract")] == ["m0", "m1", "m2", "m3"]
    w1 = llm.providers["writer1"]
    assert w1.extra_body == {"thinking": {"type": "disabled"}} and w1.json_mode   # DeepSeek preset by URL
    v = llm.chain("vision", need_vision=True)[0]
    assert v.extra_body is None and v.json_mode is False and v.max_tokens == 2048
    assert back.roles["writer"][0].price_in == 2.0
    back.roles["writer"].append(M.Slot("x", "y", "https://a.b", "K"))
    with pytest.raises(ConfigError, match="3 个备用"):
        back.to_llm_config()
    with pytest.raises(ConfigError, match="https"):
        M.Slot("x", "y", "http://evil", "K").validate("t")
    with pytest.raises(ConfigError, match="主笔"):
        M.ModelSettings().to_llm_config()


def test_migrate_legacy_keeps_key_names():
    d = tomllib.loads((ROOT / ".spike_data" / "stage3v2.toml").read_text("utf-8")) if (ROOT / ".spike_data" / "stage3v2.toml").exists() else {
        "providers": {"a": {"protocol": "openai_compatible", "base_url": "https://api.deepseek.com", "model": "m",
                            "key_env": "DEEPSEEK_API_KEY", "json_mode": True}},
        "stations": {"extract": ["a"], "judge": ["a"]}}
    ms = M.migrate_legacy(d)
    assert ms.roles["writer"] and ms.roles["writer"][0].key_ref == "DEEPSEEK_API_KEY"
    assert ms.roles["writer"][0].vendor == "DeepSeek"
    ms.to_llm_config()


def test_cli_models_set_list_with_preset_and_key_in_keychain(home, kr, monkeypatch, capsys):
    feed(monkeypatch, ["DeepSeek", "", "my-model", ""], keys=["sk-SECRET-AAAA"])
    assert cli.main(["models", "set", "主笔"]) == 0
    out = capsys.readouterr().out
    assert "URL 预填为 https://api.deepseek.com" in out and "SECRET" not in out
    assert kr.d[("litreader", "DEEPSEEK_API_KEY")] == "sk-SECRET-AAAA"
    mt = (home / "models.toml").read_text("utf-8")
    assert "SECRET" not in mt and 'model = "my-model"' in mt and 'url = "https://api.deepseek.com"' in mt
    # unknown vendor: URL must be typed, no guessing; price optional
    feed(monkeypatch, ["Tongyi", "https://tongyi.example/v1", "gem-model", "1.5 6"], keys=["g-key"])
    assert cli.main(["models", "set", "主笔"]) == 0
    out = capsys.readouterr().out
    assert "没有预设 URL" in out
    assert kr.d[("litreader", "TONGYI_API_KEY")] == "g-key"
    assert cli.main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "1. 主用  DeepSeek | my-model" in out and "2. 备用1  Tongyi | gem-model" in out and "单价 1.5/6.0" in out
    assert "估算校准：已实测 0 篇，还需 3 篇才启用本模型校准" in out          # decision 3 (2026-10-18)
    assert "g-key" not in out and "SECRET" not in out
    cfg = appconfig.load(None)
    assert [p.model for p in cfg.llm.chain("extract")] == ["my-model", "gem-model"]


def test_cli_models_set_rejects_fifth_slot(home, kr, monkeypatch, capsys):
    for i in range(4):
        feed(monkeypatch, [f"V{i}", "https://x.example/v1", f"m{i}", ""], keys=["k"])
        assert cli.main(["models", "set", "交叉核对"]) == 0
    assert cli.main(["models", "set", "交叉核对"]) == 1
    assert "最多 1 个主用 + 3 个备用" in capsys.readouterr().out


def fake_tx(seen, status=200, reply='{"ok": true}'):
    def tx(url, headers, body, timeout):
        seen.append((url, json.loads(body), headers))
        if status != 200:
            return status, b"{}"
        return 200, json.dumps({"choices": [{"message": {"content": reply}}],
                                "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode()
    return tx


def test_test_slot_text_and_vision_tiny_image(kr):
    kr.d[("litreader", "K")] = "secret-value"
    ms = M.ModelSettings()
    ms.roles["writer"].append(M.Slot("V", "m", "https://x.example/v1", "K"))
    ms.roles["vision"].append(M.Slot("V", "vm", "https://x.example/v1", "K"))
    llm = ms.to_llm_config()
    seen = []
    r = M.test_slot(llm.providers["writer1"], "writer", fake_tx(seen), secrets.SecretEnv())
    assert r["ok"] and r["detail"] == "JSON 正常（内容与预期不同，不影响使用）" and "max_tokens" not in seen[0][1]
    r = M.test_slot(llm.providers["vision1"], "vision", fake_tx(seen, reply="红"), secrets.SecretEnv())
    img = seen[1][1]["messages"][0]["content"][1]["image_url"]["url"]
    assert r["ok"] and "识别正确" in r["detail"] and img.startswith("data:image/png;base64,")
    assert base64.b64decode(img.split(",", 1)[1]).startswith(b"\x89PNG")
    assert "圆形" in seen[1][1]["messages"][0]["content"][0]["text"]
    r = M.test_slot(llm.providers["writer1"], "writer", fake_tx(seen, status=401), secrets.SecretEnv())
    assert not r["ok"] and r["category"] == "AUTH" and "secret-value" not in json.dumps(r)
    r = M.test_slot(llm.providers["writer1"], "writer", fake_tx(seen, reply="hello"), secrets.SecretEnv())
    assert not r["ok"] and r["category"] == "NOT_JSON"


def test_cli_models_test_reports_without_key(home, kr, monkeypatch, capsys):
    feed(monkeypatch, ["DeepSeek", "", "my-model", ""], keys=["sk-SECRET-BBBB"])
    cli.main(["models", "set", "主笔"])
    capsys.readouterr()
    seen = []
    monkeypatch.setattr("litreader.llm.client.urllib_transport", fake_tx(seen))
    assert cli.main(["models", "test"]) == 0
    out = capsys.readouterr().out
    assert "✅ 主笔·主用（DeepSeek my-model）：OK" in out and "SECRET" not in out
    assert seen[0][0] == "https://api.deepseek.com/chat/completions"


def test_cli_models_migrate(home, kr, capsys):
    cfgp = home / "config.local.toml"
    cfgp.write_text(cfgp.read_text("utf-8") + '''
[providers.ds]
protocol = "openai_compatible"
base_url = "https://api.deepseek.com"
model = "legacy-model"
key_env = "DEEPSEEK_API_KEY"
json_mode = true
[stations]
extract = ["ds"]
judge = ["ds"]
''', "utf-8")
    cfg = appconfig.load(None)
    assert cfg.legacy_models and cfg.llm.chain("extract")[0].model == "legacy-model"
    assert cli.main(["models", "migrate"]) == 0
    cfg = appconfig.load(None)
    assert not cfg.legacy_models and cfg.llm.chain("judge")[0].model == "legacy-model"
    assert cli.main(["models", "migrate"]) == 0 and "无需迁移" in capsys.readouterr().out


# ---------- intent ----------
@pytest.mark.parametrize("text,q", [
    ("精读zotero中的Gait kinematics in MCI，并将精读笔记存入obsidian中", "Gait kinematics in MCI"),
    ("请帮我精读 Zotero 里的《轻度认知障碍步态》这篇论文", "轻度认知障碍步态"),
    ("读一下 Yang 2024", "Yang 2024"),
    ("精读“Gait speed”并保存到Obsidian", "Gait speed"),
    ("帮我精读zotero中的论文：Dual-task gait, 然后存到obsidian里", "Dual-task gait"),
])
def test_intent_regex(text, q):
    it = intent.parse_regex(text)
    assert it.action == "read" and it.query == q and it.method == "regex"


def test_intent_batch_unknown_and_llm_fallback_guard():
    assert intent.parse_regex("批量精读所有步态论文").action == "batch"
    assert intent.parse_regex("今天天气怎么样").action == "unknown"
    ms = M.ModelSettings(); ms.roles["writer"].append(M.Slot("V", "m", "https://x.example", "K"))
    chain = ms.to_llm_config().chain("extract")
    ok = intent.parse("麻烦看看 frailty 那篇", chain, fake_tx([], reply='{"action":"read","query":"frailty"}'), {"K": "k"})
    assert ok.action == "read" and ok.query == "frailty" and ok.method == "llm"
    bad = intent.parse("麻烦看看 frailty 那篇", chain, fake_tx([], reply='{"action":"read","query":"Frailty Index 2023"}'), {"K": "k"})
    assert bad.action == "unknown"   # invented query (not verbatim in the command) is refused


# ---------- topics ----------
def test_list_topics_excludes_system_folders(tmp_path):
    for n in ("认知与步态", "_阅读版本", "_证据档案", "_图表", ".obsidian", "跌倒风险"):
        (tmp_path / n).mkdir()
    (tmp_path / "笔记.md").write_text("x")
    assert topics.list_topics(tmp_path) == ["认知与步态", "跌倒风险"]


def test_topic_suggest_validation():
    ms = M.ModelSettings(); ms.roles["writer"].append(M.Slot("V", "m", "https://x.example", "K"))
    chain = ms.to_llm_config().chain("extract")
    s = topics.suggest(["认知与步态"], "t", "", [], chain, fake_tx([], reply='{"choice":"existing","folder":"认知与步态","reason":"r"}'), {"K": "k"})
    assert s["choice"] == "existing" and s["folder"] == "认知与步态"
    s = topics.suggest(["认知与步态"], "t", "", [], chain, fake_tx([], reply='{"choice":"existing","folder":"幻觉","reason":"r"}'), {"K": "k"})
    assert s["choice"] == "new" and s["status"] == "EXISTING_NOT_FOUND"
    s = topics.suggest([], "t", "", [], chain, fake_tx([], reply='{"choice":"new","folder":"../跌倒:风险","reason":"r"}'), {"K": "k"})
    assert s["choice"] == "new" and "/" not in s["folder"] and ".." not in s["folder"].split("/")
    s = topics.suggest([], "t", "", [], chain, fake_tx([], status=500), {"K": "k"})
    assert s["folder"] == "未分类" and s["status"].startswith("LLM_FAILED")


# ---------- estimate ----------
def test_estimate_scales_with_zhong_ratios_and_never_invents_prices():
    e = estimate.estimate({"pages": 11, "chars": 32187, "figures": 2}, {"writer", "vision", "judge"}, cached_parse=False)
    w = e["roles"]["writer"]["in"]   # ratios now calibrated on DeepGaitLab; Zhong's actual 14 626 stays inside ±40 %
    assert w * (1 - estimate.RATIO["spread"]) <= 14626 <= w * (1 + estimate.RATIO["spread"]) and e["mineru_pages"] == 11
    assert e["roles"]["vision"]["in"] == 2 * estimate.RATIO["vision_in"]
    assert estimate.cost(1_000_000, 0, None, 8) is None and estimate.cost(1_000_000, 500_000, 2, 8) == 6.0
    c = estimate.estimate({"pages": 11, "chars": None, "figures": None}, {"writer"}, cached_parse=True)
    assert c["mineru_pages"] == 0 and not c["chars_measured"] and "vision" not in c["roles"]


def test_cli_dispatch_natural_language_and_interactive(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "run_command", lambda text, config, ui=None, **kw: seen.append((text, config)) or 0)
    assert cli.main(["精读zotero中的", "Gait speed"]) == 0
    assert cli.main(["--config", "c.toml", "精读 X"]) == 0
    assert seen == [("精读zotero中的 Gait speed", None), ("精读 X", "c.toml")]

    class UI(cli.ConsoleUI):
        def __init__(self, a):
            self.a, self.out = list(a), []
        def say(self, m):
            self.out.append(m)
        def ask(self, p):
            return self.a.pop(0)

    def boom(text, config, ui=None, **kw):
        from litreader.errors import Stop
        raise Stop("没看懂")
    monkeypatch.setattr(cli, "run_command", boom)
    ui = UI(["", "今天天气", "q"])
    assert cli.interactive(None, ui) == 0 and any("没看懂" in m for m in ui.out)


def test_models_test_uses_exactly_the_real_request_builder(kr):
    """Same json_mode / max_tokens / thinking switch as real runs: the probe request == build_request(slot)."""
    from litreader.llm.client import build_request
    kr.d[("litreader", "DEEPSEEK_API_KEY")] = "sk-abcdef1234567890"
    ms = M.ModelSettings()
    ms.roles["writer"].append(M.Slot("DeepSeek", "deepseek-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"))
    ms.roles["vision"].append(M.Slot("MiniMax（中国站）", "MiniMax-M3", "https://api.minimaxi.com/v1", "MINIMAX_API_KEY"))
    kr.d[("litreader", "MINIMAX_API_KEY")] = "mm-secret-value-xyz"
    llm = ms.to_llm_config()
    seen = []
    w = llm.providers["writer1"]
    r = M.test_slot(w, "writer", fake_tx(seen, reply='{"status": "ok", "sum": 5}'), secrets.SecretEnv())
    assert seen[0][1] == build_request(w, M.TEXT_PROBE)
    assert seen[0][1]["response_format"] == {"type": "json_object"} and seen[0][1]["thinking"] == {"type": "disabled"}
    assert seen[0][1]["max_tokens"] == 32000 and seen[0][1]["messages"][0]["role"] == "system"
    assert r["ok"] and r["detail"] == "JSON 正常" and r["request"]["response_format"] == {"type": "json_object"}
    assert "messages" not in r["request"] and "sk-abcdef" not in json.dumps(r)
    v = llm.providers["vision1"]
    M.test_slot(v, "vision", fake_tx(seen, reply="红"), secrets.SecretEnv())
    body = seen[1][1]
    assert {k: x for k, x in body.items() if k != "messages"} == {k: x for k, x in build_request(v, []).items() if k != "messages"}
    # broken JSON like the real deepseek glitch -> NOT_JSON, raw shown redacted
    r = M.test_slot(w, "writer", fake_tx(seen, reply='{"ok":##"} sk-abcdef1234567890'), secrets.SecretEnv())
    assert r["category"] == "NOT_JSON" and "«KEY»" in r["raw"] and "sk-abcdef" not in r["raw"]


def test_probe_png_is_a_red_disc_on_white():
    import struct as st
    import zlib as zl
    b = M.probe_png()
    assert b.startswith(b"\x89PNG\r\n\x1a\n")
    w, h, depth, ctype = st.unpack(">IIBB", b[16:26])
    assert (w, h, depth, ctype) == (256, 256, 8, 2)            # RGB, 8-bit
    n = st.unpack(">I", b[33:37])[0]
    raw = zl.decompress(b[41:41 + n])
    row = lambda y: raw[y * (1 + 3 * 256) + 1:(y + 1) * (1 + 3 * 256)]
    px = lambda x, y: tuple(row(y)[3 * x:3 * x + 3])
    assert px(128, 128) == (220, 30, 30) and px(5, 5) == (255, 255, 255)   # R first: not BGR


def test_cli_models_test_verbose_shows_request_and_redacted_raw(home, kr, monkeypatch, capsys):
    feed(monkeypatch, ["DeepSeek", "", "my-model", ""], keys=["sk-SECRET-BBBB-1234"])
    cli.main(["models", "set", "主笔"])
    capsys.readouterr()
    seen = []
    monkeypatch.setattr(cli, "urllib_transport", fake_tx(seen, reply='{"status":"ok","sum":5} Bearer sk-SECRET-BBBB-1234'), raising=False)
    from litreader.llm import client as C
    monkeypatch.setattr(C, "urllib_transport", fake_tx(seen, reply='{"status":"ok","sum":5} Bearer sk-SECRET-BBBB-1234'))
    rc = cli.main(["models", "test", "主笔", "--verbose"])
    out = capsys.readouterr().out
    assert rc == 0 and "原始回复（已隐去 Key" in out and "response_format" in out and '"thinking"' in out
    assert "SECRET" not in out
