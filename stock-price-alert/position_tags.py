"""持仓类自定义标签：豁免扫描清理、单独分区展示。"""

from __future__ import annotations

import re
from typing import Any

_POSITION_RE = re.compile(
    r"(持仓|持有|仓位|中线持仓|长线持有|低吸持仓)",
    re.IGNORECASE,
)


def normalize_tags_field(rule: dict[str, Any]) -> str:
    """tags 可为 str（逗号/顿号分隔）或 list[str]，统一为可读字符串。"""
    raw = rule.get("tags")
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        return " ".join(parts)
    return str(raw).strip()


def has_position_tag(rule: dict[str, Any]) -> bool:
    """含「持仓/持有」等自定义标签则视为持仓豁免标的。"""
    s = normalize_tags_field(rule)
    if not s:
        return False
    return bool(_POSITION_RE.search(s))


def format_tags_line(rule: dict[str, Any]) -> str:
    s = normalize_tags_field(rule)
    if not s:
        return "      └ 标签：（空，可在 config.json 的 tags 字段手写标记）"
    return f"      └ 标签：{s}"
