"""Platform-aware user-facing wording (W3): where secrets live, the file manager's name,
and whether to show macOS-only Keychain prompt hints. Evaluated at call time (tests patch sys.platform)."""
from __future__ import annotations

import sys


def _plat(platform: str | None = None) -> str:
    p = platform or sys.platform
    return "mac" if p == "darwin" else "win" if p.startswith("win") else "linux"


def keystore_name(platform: str | None = None) -> str:
    """macOS 钥匙串（Keychain） / Windows 凭据管理器（Credential Manager） / Linux 系统密钥环（keyring）."""
    return {"mac": "钥匙串（Keychain）", "win": "凭据管理器（Credential Manager）",
            "linux": "系统密钥环（keyring）"}[_plat(platform)]


def keystore_short(platform: str | None = None) -> str:
    """Short form for tight labels: 钥匙串 / 凭据管理器 / 密钥环."""
    return {"mac": "钥匙串", "win": "凭据管理器", "linux": "密钥环"}[_plat(platform)]


def file_manager_name(platform: str | None = None) -> str:
    return {"mac": "访达", "win": "资源管理器", "linux": "文件管理器"}[_plat(platform)]


def keystore_prompt_hint(platform: str | None = None) -> str:
    """macOS-only hint about the Keychain authorisation dialog; empty elsewhere."""
    if _plat(platform) == "mac":
        return "若提示钥匙串读取失败，请在弹出的系统授权里选择「始终允许」后重试。"
    return ""


def display_path(path, platform: str | None = None) -> str:
    """W5: paths shown to the user use the platform's separator (Windows: all backslashes, no mixed D:\\a/b)."""
    s = str(path)
    return s.replace("/", "\\") if _plat(platform) == "win" else s


def shortcut(key: str, platform: str | None = None) -> str:
    """⌘O on macOS, Ctrl+O elsewhere (tooltip text only)."""
    return f"⌘{key}" if _plat(platform) == "mac" else f"Ctrl+{key}"


def notification_hint(platform: str | None = None) -> str:
    return {"mac": "第一次通知时 macOS 会询问是否允许；之后可在「系统设置 → 通知」里修改。拒绝后界面内照常提示。",
            "win": "可在 Windows「设置 → 系统 → 通知」里开关 Litreader 的通知。关闭后界面内照常提示。",
            "linux": "通知由桌面环境显示；关闭后界面内照常提示。"}[_plat(platform)]
