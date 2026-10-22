"""Secrets: environment variable first, then the OS keyring (macOS Keychain) under service "litreader".
Values are never printed or written to files. keyring is optional (pip install keyring)."""
from __future__ import annotations

import os
from collections.abc import Mapping

SERVICE = "litreader"


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:
        return None


class KeychainError(RuntimeError):
    """The keyring backend failed (locked, access denied, prompt dismissed…) — NOT the same as "no such key"."""

    def __init__(self, name: str, exc: BaseException):
        super().__init__(f"钥匙串读取失败（{type(exc).__name__}）：{name}")
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
    try:
        return kr.get_password(SERVICE, name) or None
    except Exception as e:  # noqa: BLE001
        raise KeychainError(name, e) from None


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


def delete(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass


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
