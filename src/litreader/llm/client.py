"""OpenAI-compatible chat client with injectable transport, plus fallback runner."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from ..errors import LitError
from .config import ProviderConfig

# transport(url, headers, body_bytes, timeout) -> (status, body_bytes); may raise TimeoutError
Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class ProviderError(LitError):
    def __init__(self, provider: str, category: str, detail: str):
        super().__init__(f"{provider}: {category}: {detail}")
        self.provider, self.category, self.detail = provider, category, detail


class AllProvidersFailed(LitError):
    def __init__(self, attempts: list[dict]):
        super().__init__(f"all providers failed: {[a['category'] for a in attempts]}")
        self.attempts = attempts


def classify(status: int) -> str:
    if status in (401, 403):
        return "AUTH"
    if status == 404:
        return "MODEL_OR_URL_NOT_FOUND"
    if status == 429:
        return "RATE_LIMIT"
    if status >= 500:
        return "SERVER"
    return f"HTTP_{status}"


LAST_USAGE: dict = {}


def build_request(p: ProviderConfig, messages: list[dict]) -> dict:
    """THE request builder: used by every real call and by `models test` (no per-path overrides)."""
    req = {"model": p.model, "messages": messages}
    if p.json_mode:
        req["response_format"] = {"type": "json_object"}
    if p.max_tokens:
        req["max_tokens"] = int(p.max_tokens)
    for k, v in (p.extra_body or {}).items():
        if k in ("model", "messages"):
            raise ProviderError(p.id, "CONFIG", f"extra_body may not override {k}")
        req[k] = v
    return req


def chat(p: ProviderConfig, messages: list[dict], transport: Transport, env=os.environ) -> str:
    from ..secrets import KeychainError
    try:
        key = env.get(p.key_env, "")
    except KeychainError as e:
        raise ProviderError(p.id, "KEYCHAIN_ERROR", f"{e.kind}: {p.key_env}") from None
    if not key:
        raise ProviderError(p.id, "KEY_MISSING", f"env {p.key_env} not set")
    req = build_request(p, messages)
    body = json.dumps(req).encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        status, raw = transport(f"{p.base_url}/chat/completions", headers, body, p.timeout_s)
    except TimeoutError as e:
        raise ProviderError(p.id, "TIMEOUT", str(e)) from e
    if status != 200:
        raise ProviderError(p.id, classify(status), f"HTTP {status}")
    try:
        j = json.loads(raw)
        LAST_USAGE.clear(); LAST_USAGE.update(j.get("usage") or {})
        return j["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise ProviderError(p.id, "BAD_RESPONSE", "unexpected response shape") from e


@dataclass
class FallbackResult:
    text: str
    model_used: str
    provider_used: str
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    attempts: list[dict] = field(default_factory=list)


def run_chain(chain: list[ProviderConfig], messages: list[dict], transport: Transport,
              env=os.environ) -> FallbackResult:
    """One attempt per provider, in order. Any failure moves on; nothing is retried on the same slot."""
    attempts = []
    for p in chain:
        import time
        t0 = time.monotonic()
        try:
            text = chat(p, messages, transport, env)
            attempts.append({"provider": p.id, "model": p.model, "category": "OK"})
            return FallbackResult(text, p.model, p.id, dict(LAST_USAGE), time.monotonic() - t0, attempts)
        except ProviderError as e:
            attempts.append({"provider": p.id, "model": p.model, "category": e.category})
    raise AllProvidersFailed(attempts)


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:  # pragma: no cover
    import socket
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (socket.timeout, TimeoutError) as e:
        raise TimeoutError(str(e)) from e
