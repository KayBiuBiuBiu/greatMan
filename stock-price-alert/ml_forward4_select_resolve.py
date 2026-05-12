"""按大盘三档情绪合并 ml_forward4 选股门槛（不写回磁盘）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_MOOD_KEYS = frozenset({"strong_bull", "range", "weak_bear"})
# 仅允许按情绪覆盖的键（避免误合并杂项）
_SELECT_MOOD_OVERRIDE_KEYS = frozenset(
    {
        "select_min_up_prob_quality",
        "select_min_up_prob_watch",
        "select_strict_no_prob",
    }
)


def resolve_ml_forward4_for_daily_select(
    cfg: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """
    返回 (选股用 ml_forward4 有效副本, 所用情绪档或 None)。
    未配置 ml_forward4 时返回 (None, None)；未启用 adaptive 时第二项为 None。
    """
    if not isinstance(cfg, dict):
        return None, None
    mf4 = cfg.get("ml_forward4")
    if not isinstance(mf4, dict):
        return None, None
    adb = mf4.get("select_adaptive_by_mood")
    if not isinstance(adb, dict) or not bool(adb.get("enabled", False)):
        return deepcopy(mf4), None

    base = {k: v for k, v in mf4.items() if k != "select_adaptive_by_mood"}
    try:
        from macro_risk import get_market_mood_three_tier

        mr = cfg.get("macro_risk") or {}
        tier = get_market_mood_three_tier(
            dynamic_cfg=mr if isinstance(mr, dict) else None
        )
    except Exception:
        tier = "range"
    if tier not in _MOOD_KEYS:
        tier = "range"
    ov = adb.get(str(tier))
    if not isinstance(ov, dict) or not ov:
        return deepcopy(mf4), tier

    merged = deepcopy(base)
    for k, v in ov.items():
        if k not in _SELECT_MOOD_OVERRIDE_KEYS:
            continue
        if v is None:
            continue
        merged[k] = v
    return merged, tier


def effective_select_thresholds(mf4: dict[str, Any] | None) -> dict[str, Any]:
    """解析当前 ml_forward4 里用于打印/汇总的门槛（可能为 null）。"""
    if not isinstance(mf4, dict):
        return {"select_min_up_prob_quality": None, "select_min_up_prob_watch": None}

    def _f(key: str) -> float | None:
        if key not in mf4:
            return None
        v = mf4.get(key)
        if v is None:
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        if x < 0.0 or x > 1.0:
            return None
        return x

    return {
        "select_min_up_prob_quality": _f("select_min_up_prob_quality"),
        "select_min_up_prob_watch": _f("select_min_up_prob_watch"),
        "select_strict_no_prob": bool(mf4.get("select_strict_no_prob", False)),
    }
