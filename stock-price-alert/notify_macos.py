"""macOS 系统通知 + 可选提示音。"""

from __future__ import annotations

import subprocess


def notify(
    title: str,
    message: str,
    subtitle: str | None = None,
    *,
    sound: bool = True,
    sound_name: str = "Glass",
) -> bool:
    parts: list[str] = [
        "display notification",
        _apple_quote(message),
        "with title",
        _apple_quote(title),
    ]
    if subtitle:
        parts += ["subtitle", _apple_quote(subtitle)]
    if sound:
        parts += ["sound name", _apple_quote(sound_name)]
    script = " ".join(parts)
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def send_notification(
    title: str,
    text: str,
    subtitle: str | None = None,
    *,
    sound: bool = True,
) -> bool:
    """与 notify 等价，兼容 import send_notification。"""
    return notify(title, text, subtitle=subtitle, sound=sound)


def _apple_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
