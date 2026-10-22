"""Mock layer: LLM config + OpenAI-compatible client + fallback chain (fake transport, no network)."""
import json
import re
from pathlib import Path

import pytest

from litreader.llm.client import AllProvidersFailed, run_chain
from litreader.llm.config import ConfigError, parse_config

CFG = {"providers": {
    "a": {"protocol": "openai_compatible", "base_url": "https://a.example/v1", "model": "user-model-a", "key_env": "KA"},
    "b": {"protocol": "openai_compatible", "base_url": "https://b.example/v1", "model": "user-model-b", "key_env": "KB",
          "supports_vision": True},
    "c": {"protocol": "openai_compatible", "base_url": "https://c.example/v1", "model": "user-model-c", "key_env": "KC"}},
    "stations": {"writer": ["a", "b", "c"], "vision": ["b"]}}
ENV = {"KA": "ka", "KB": "kb", "KC": "kc"}


class FakeLLM:
    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def __call__(self, url, headers, body, timeout):
        host = url.split("//")[1].split(".")[0]
        self.calls.append((host, json.loads(body)["model"], headers["Authorization"]))
        r = self.plan[host]
        if r == "timeout":
            raise TimeoutError("t")
        if isinstance(r, int):
            return r, b"{}"
        return 200, json.dumps({"choices": [{"message": {"content": r}}]}).encode()


def test_primary_ok_uses_configured_model():
    c = parse_config(CFG); t = FakeLLM({"a": "hi"})
    r = run_chain(c.chain("writer"), [{"role": "user", "content": "x"}], t, ENV)
    assert r.text == "hi" and r.model_used == "user-model-a" and len(t.calls) == 1
    assert t.calls[0][2] == "Bearer ka"


def test_503_falls_to_backup1():
    t = FakeLLM({"a": 503, "b": "ok"})
    r = run_chain(parse_config(CFG).chain("writer"), [], t, ENV)
    assert r.provider_used == "b" and [a["category"] for a in r.attempts] == ["SERVER", "OK"]


def test_401_not_retried_on_same_slot():
    t = FakeLLM({"a": 401, "b": "timeout", "c": "ok"})
    r = run_chain(parse_config(CFG).chain("writer"), [], t, ENV)
    assert [h for h, *_ in t.calls] == ["a", "b", "c"]
    assert [a["category"] for a in r.attempts] == ["AUTH", "TIMEOUT", "OK"]


def test_all_fail_raises_with_attempts():
    t = FakeLLM({"a": 500, "b": 429, "c": 404})
    with pytest.raises(AllProvidersFailed) as e:
        run_chain(parse_config(CFG).chain("writer"), [], t, ENV)
    assert [a["category"] for a in e.value.attempts] == ["SERVER", "RATE_LIMIT", "MODEL_OR_URL_NOT_FOUND"]


def test_missing_key_skips_without_network():
    t = FakeLLM({"b": "ok"})
    r = run_chain(parse_config(CFG).chain("writer"), [], t, {"KB": "kb"})
    assert r.provider_used == "b" and r.attempts[0]["category"] == "KEY_MISSING"
    assert [h for h, *_ in t.calls] == ["b"]


def test_bad_response_shape_falls_through():
    class T(FakeLLM):
        def __call__(self, url, headers, body, timeout):
            if "a.example" in url:
                return 200, b'{"nope":1}'
            return super().__call__(url, headers, body, timeout)
    r = run_chain(parse_config(CFG).chain("writer"), [], T({"b": "ok"}), ENV)
    assert r.attempts[0]["category"] == "BAD_RESPONSE"


@pytest.mark.parametrize("mut", [
    lambda d: d["providers"]["a"].pop("model"),
    lambda d: d["providers"]["a"].update(model=" "),
    lambda d: d["providers"]["a"].update(base_url="http://evil.example"),
    lambda d: d["providers"]["a"].update(protocol="magic"),
    lambda d: d["stations"].update(writer=["a", "b", "c", "a", "b"]),
    lambda d: d["stations"].update(writer=["zzz"]),
    lambda d: d["stations"].update(writer=[]),
])
def test_config_validation(mut):
    d = json.loads(json.dumps(CFG)); mut(d)
    with pytest.raises(ConfigError):
        parse_config(d)


def test_vision_station_requires_confirmed_vision():
    c = parse_config(CFG)
    assert c.chain("vision", need_vision=True)[0].id == "b"
    with pytest.raises(ConfigError):
        c.chain("writer", need_vision=True)


def test_no_hardcoded_model_names_in_src():
    src = Path(__file__).resolve().parents[2] / "src"
    pat = re.compile(r"\b(gpt-[0-9]|claude-|gemini-[0-9]|deepseek-(chat|reasoner|flash|v[0-9])|minimax-m[0-9]|qwen[0-9-]|glm-[0-9]|moonshot-|abab)", re.I)
    hits = [str(p) for p in src.rglob("*.py") if pat.search(p.read_text("utf-8"))]
    assert hits == []


def test_example_config_parses_when_uncommented(tmp_path):
    ex = (Path(__file__).resolve().parents[2] / "models.example.toml").read_text("utf-8")
    assert "model =" in ex and "sk-" not in ex
