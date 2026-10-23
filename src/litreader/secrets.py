"""Secrets: environment variable first, then the OS keyring (macOS Keychain) under service "litreader".
Values are never printed or written to files. keyring is optional (pip install keyring)."""
from __future__ import annotations

from litreader.platform_words import keystore_name as _kn, keystore_short as _ks
import json
import os
from collections.abc import Mapping
from pathlib import Path

SERVICE = "litreader"

# G11-1: lazy, at-most-once keychain access per process. A packaged .app that is not the program which stored the
# keys makes macOS ask once per read, so: never read at startup/page render, cache successful reads for the process
# lifetime, and remember a denied/failed read (no retry loop) until the user explicitly retries.
_STATE: dict = {"src": None, "vals": {}, "denied": {}}


def _session(kr=None):
    src = globals()["_keyring"]
    if _STATE["src"] is not src:            # backend provider swapped (tests use fakes) -> fresh session cache
        _STATE.update(src=src, vals={}, denied={})
    return _STATE


def reset_session() -> None:
    _STATE.update(src=None, vals={}, denied={})


def forget_denied(name: str) -> None:
    """Explicit user retry (e.g. 测试连接 clicked again) may ask the keychain once more."""
    _STATE["denied"].pop(name, None)


def _index_path() -> Path:
    p = os.environ.get("LITREADER_KEY_INDEX")
    if p:
        return Path(p)
    from .appconfig import default_data_dir
    return default_data_dir() / "key_names.json"


def _index() -> set:
    try:
        return set(json.loads(_index_path().read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _index_set(name: str, present: bool) -> None:
    """Names only (never values): lets the settings page show 「已保存（未读取）」 without touching the keychain."""
    try:
        idx = _index()
        if (name in idx) == present:
            return
        if present:
            idx.add(name)
        else:
            idx.discard(name)
        path = _index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(idx)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:
        return None


class KeychainError(RuntimeError):
    """The keyring backend failed (locked, access denied, prompt dismissed…) — NOT the same as "no such key"."""

    def __init__(self, name: str, exc: BaseException):
        super().__init__(f"{_kn()}读取失败（{type(exc).__name__}）：{name}")
        self.name, self.kind = name, type(exc).__name__


def lookup(name: str) -> str | None:
    """Env first, then keyring. Returns None only when the key truly is not stored; a keyring failure raises
    KeychainError (never includes the value)."""
    v = os.environ.get(name)
    if v:
        return v
    kr = _keyring()
    if kr is None:
        return None
    st = _session(kr)
    if name in st["vals"]:
        return st["vals"][name]
    if name in st["denied"]:
        raise st["denied"][name]
    try:
        v = kr.get_password(SERVICE, name) or None
    except Exception as e:  # noqa: BLE001
        err = KeychainError(name, e)
        st["denied"][name] = err
        raise err from None
    if v:
        st["vals"][name] = v
    _index_set(name, bool(v))
    return v


def status(name: str) -> str:
    """Key status WITHOUT reading the keychain: env | saved (read OK this session) | denied | indexed (stored, not
    read yet) | unknown (maybe stored before the index existed — read only when first needed)."""
    if os.environ.get(name):
        return "env"
    st = _session()
    if name in st["vals"]:
        return "saved"
    if name in st["denied"]:
        return "denied"
    return "indexed" if name in _index() else "unknown"


STATUS_ZH = {"env": "来自环境变量", "saved": "已保存", "denied": f"{_ks()}读取被拒绝",
             "indexed": "已保存（未读取）", "unknown": "未读取（用到时再读）"}


def get(name: str) -> str | None:
    """Lenient form for status displays: a keyring failure reads as "not available"."""
    try:
        return lookup(name)
    except KeychainError:
        return None


def set_secret(name: str, value: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("keyring 未安装：请先运行 pip install keyring")
    kr.set_password(SERVICE, name, value)
    st = _session(kr)
    st["vals"][name] = value
    st["denied"].pop(name, None)
    _index_set(name, True)


def delete(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
        _session(kr)["vals"].pop(name, None)
    _index_set(name, False)


def selftest() -> tuple[bool, str]:
    """Store, read back and delete a dummy secret. Returns (ok, backend-name)."""
    kr = _keyring()
    if kr is None:
        return False, "keyring not installed"
    name, val = "litreader-selftest", "selftest-value-123"
    try:
        kr.set_password(SERVICE, name, val)
        ok = kr.get_password(SERVICE, name) == val
        kr.delete_password(SERVICE, name)
        return ok, type(kr.get_keyring()).__name__
    except Exception as e:  # pragma: no cover - backend specific
        return False, f"{type(e).__name__}"


class SecretEnv(Mapping):
    """Mapping usable wherever the LLM client expects `env` (reads env, then keyring)."""

    def __getitem__(self, k):
        v = lookup(k)
        if v is None:
            raise KeyError(k)
        return v

    def get(self, k, default=None):
        v = lookup(k)   # KeychainError propagates so callers can report KEYCHAIN_ERROR
        return default if v is None else v

    def __iter__(self):
        return iter(os.environ)

    def __len__(self):
        return len(os.environ)
