"""macOS 系统通知 + 可选提示音。"""

from __future__ import annotations

import subprocess

from legal_disclosure import append_to_body


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
    cfg: dict | None = None,
    skip_disclaimer: bool = False,
    severity: str | None = None,
) -> bool:
    """与 notify 等价；默认在正文末附加合规免责声明（P0-2）。

    severity：info / warning / critical，写入副标题前缀便于过滤（P1-5）。
    """
    body = text if skip_disclaimer else append_to_body(text, cfg=cfg)
    sev = (severity or "").strip().lower()
    sub = subtitle
    if sev in ("info", "warning", "critical"):
        tag = {"critical": "[紧急]", "warning": "[预警]", "info": "[提示]"}.get(
            sev, ""
        )
        sub = f"{tag} {subtitle}".strip() if subtitle else tag
    return notify(title, body, subtitle=sub, sound=sound)


def _apple_quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
