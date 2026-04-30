"""合规：提醒类文案末尾免责声明（通知、邮件）。"""

from __future__ import annotations

from typing import Any

DEFAULT_DISCLAIMER = (
    "* 本提醒仅为机械计算结果，不构成投资建议。历史数据不代表未来收益。"
)


def disclaimer_suffix(cfg: dict[str, Any] | None) -> str:
    leg = (cfg or {}).get("legal") if isinstance(cfg, dict) else None
    if isinstance(leg, dict):
        s = str(leg.get("disclaimer_suffix") or "").strip()
        if s:
            return s
    return DEFAULT_DISCLAIMER


def append_to_body(body: str, *, cfg: dict[str, Any] | None = None) -> str:
    if not (body or "").strip():
        return body
    tail = disclaimer_suffix(cfg)
    if tail in body:
        return body
    return body.rstrip() + "\n\n" + tail
