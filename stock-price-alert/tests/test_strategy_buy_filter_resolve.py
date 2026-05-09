"""adaptive_by_mood 与有效 strategy_buy_filter 合并。"""

from __future__ import annotations

from strategy_buy_filter_resolve import resolve_effective_strategy_buy_filter


def test_resolve_adaptive_disabled_returns_base_without_adaptive_key() -> None:
    cfg = {
        "strategy_buy_filter": {
            "enabled": True,
            "min_volume_ratio": 1.0,
            "adaptive_by_mood": {"enabled": False, "weak_bear": {"min_volume_ratio": 2.0}},
        },
        "_runtime_mood_tier_for_buy_filter": "weak_bear",
    }
    eff = resolve_effective_strategy_buy_filter(cfg)
    assert eff["min_volume_ratio"] == 1.0
    assert "adaptive_by_mood" not in eff


def test_resolve_weak_bear_overrides_and_merges_sector_cross() -> None:
    cfg = {
        "strategy_buy_filter": {
            "enabled": True,
            "min_intraday_position": 0.3,
            "sector_buy_cross_check": {
                "enabled": True,
                "min_pass_votes": 2,
                "min_evaluated_dims": 2,
            },
            "adaptive_by_mood": {
                "enabled": True,
                "weak_bear": {
                    "min_intraday_position": 0.15,
                    "sector_buy_cross_check": {"min_pass_votes": 3},
                },
            },
        },
        "_runtime_mood_tier_for_buy_filter": "weak_bear",
    }
    eff = resolve_effective_strategy_buy_filter(cfg)
    assert eff["min_intraday_position"] == 0.15
    assert eff["sector_buy_cross_check"]["min_pass_votes"] == 3
    assert eff["sector_buy_cross_check"]["min_evaluated_dims"] == 2


def test_unknown_tier_falls_back_to_range_branch() -> None:
    cfg = {
        "strategy_buy_filter": {
            "enabled": True,
            "adaptive_by_mood": {
                "enabled": True,
                "range": {"max_intraday_position": 0.7},
            },
        },
        "_runtime_mood_tier_for_buy_filter": "not_a_tier",
    }
    eff = resolve_effective_strategy_buy_filter(cfg)
    assert eff.get("max_intraday_position") == 0.7
