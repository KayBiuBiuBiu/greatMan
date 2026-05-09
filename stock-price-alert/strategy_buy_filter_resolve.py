"""按大盘三档情绪合并「买入实时过滤」有效配置（不修改磁盘 cfg）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_MOOD_KEYS = frozenset({"strong_bull", "range", "weak_bear"})


def resolve_effective_strategy_buy_filter(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    从 cfg['strategy_buy_filter'] 生成本轮生效的过滤 dict。
    若启用 adaptive_by_mood，则合并 cfg['_runtime_mood_tier_for_buy_filter'] 对应档位覆盖。
    """
    sbf = cfg.get("strategy_buy_filter") or {}
    if not isinstance(sbf, dict):
        return {}
    base = {k: v for k, v in sbf.items() if k != "adaptive_by_mood"}
    adb = sbf.get("adaptive_by_mood")
    if not isinstance(adb, dict) or not bool(adb.get("enabled", False)):
        return base
    tier = cfg.get("_runtime_mood_tier_for_buy_filter")
    if tier not in _MOOD_KEYS:
        tier = "range"
    ov = adb.get(str(tier))
    if not isinstance(ov, dict) or not ov:
        return base
    merged = deepcopy(base)
    for k, v in ov.items():
        if k == "sector_buy_cross_check" and isinstance(v, dict):
            prev = merged.get("sector_buy_cross_check")
            prev_d = deepcopy(prev) if isinstance(prev, dict) else {}
            prev_d.update(v)
            merged["sector_buy_cross_check"] = prev_d
        else:
            merged[k] = deepcopy(v) if isinstance(v, dict) else v
    return merged
