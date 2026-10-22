"""LLM provider config (BYOK). No model names or keys are hardcoded; everything comes from config.

TOML shape:
[providers.<id>]
protocol = "openai_compatible"
base_url = "https://..."
model = "<user-filled>"
key_env = "MY_PROVIDER_KEY"     # name of env var (keyring support later)
supports_vision = false          # true|false; omit => unknown
timeout_s = 60
[stations]
writer = ["<id1>", "<id2>"]      # fallback order: primary, backup1, backup2, backup3
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass

from ..errors import LitError

SUPPORTED_PROTOCOLS = {"openai_compatible"}
MAX_CHAIN = 4


class ConfigError(LitError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    id: str
    protocol: str
    base_url: str
    model: str
    key_env: str
    supports_vision: bool | None
    timeout_s: float = 60.0
    extra_body: dict | None = None      # provider-specific request fields from config (e.g. thinking switch)
    json_mode: bool = False             # send response_format={"type":"json_object"}
    max_tokens: int | None = None


@dataclass(frozen=True)
class LLMConfig:
    providers: dict[str, ProviderConfig]
    stations: dict[str, list[str]]

    def chain(self, station: str, need_vision: bool = False) -> list[ProviderConfig]:
        ids = self.stations.get(station)
        if not ids:
            raise ConfigError(f"station '{station}' has no providers configured")
        chain = [self.providers[i] for i in ids]
        if need_vision:
            bad = [p.id for p in chain if p.supports_vision is not True]
            if bad:
                raise ConfigError(f"station '{station}' needs vision; not confirmed for: {bad}")
        return chain


def parse_config(d: dict) -> LLMConfig:
    provs = {}
    for pid, p in (d.get("providers") or {}).items():
        for k in ("protocol", "base_url", "model", "key_env"):
            if not str(p.get(k, "")).strip():
                raise ConfigError(f"provider '{pid}': '{k}' is required (no defaults)")
        if p["protocol"] not in SUPPORTED_PROTOCOLS:
            raise ConfigError(f"provider '{pid}': unsupported protocol {p['protocol']}")
        if not p["base_url"].startswith("https://") and not p["base_url"].startswith("http://localhost"):
            raise ConfigError(f"provider '{pid}': base_url must be https (or http://localhost)")
        sv = p.get("supports_vision")
        provs[pid] = ProviderConfig(pid, p["protocol"], p["base_url"].rstrip("/"), p["model"], p["key_env"],
                                    sv if isinstance(sv, bool) else None, float(p.get("timeout_s", 60)),
                                    dict(p["extra_body"]) if isinstance(p.get("extra_body"), dict) else None,
                                    bool(p.get("json_mode", False)), p.get("max_tokens"))
    stations = {}
    for st, ids in (d.get("stations") or {}).items():
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_CHAIN:
            raise ConfigError(f"station '{st}': chain must list 1..{MAX_CHAIN} provider ids")
        for i in ids:
            if i not in provs:
                raise ConfigError(f"station '{st}': unknown provider '{i}'")
        stations[st] = list(ids)
    return LLMConfig(provs, stations)


def load_config(path) -> LLMConfig:
    with open(path, "rb") as f:
        return parse_config(tomllib.load(f))
