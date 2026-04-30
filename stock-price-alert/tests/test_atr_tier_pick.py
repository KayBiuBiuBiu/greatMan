"""ATR 分档阈值选择。"""

from __future__ import annotations

from trend_slippage_risk import _pick_atr_tier_dims


def test_atr_tier_picks_tighter_dims_when_volatile() -> None:
    tiers = [
        {"max_close_atr_pct": 2.0, "stock_min_weak_dims": 2, "sector_min_weak_dims": 2, "min_pillars_weak": 2},
        {"max_close_atr_pct": 4.0, "stock_min_weak_dims": 3, "sector_min_weak_dims": 3, "min_pillars_weak": 3},
        {"max_close_atr_pct": None, "stock_min_weak_dims": 4, "sector_min_weak_dims": 4, "min_pillars_weak": 4},
    ]
    sm, se, mp, note = _pick_atr_tier_dims(1.5, tiers, base_stock_min=2, base_sector_min=2, base_min_pillars=2)
    assert sm == 2 and se == 2 and mp == 2
    assert note is not None

    sm2, se2, mp2, _ = _pick_atr_tier_dims(3.0, tiers, base_stock_min=2, base_sector_min=2, base_min_pillars=2)
    assert sm2 == 3 and se2 == 3 and mp2 == 3


def test_atr_tier_none_pct_falls_back_to_base() -> None:
    tiers = [{"max_close_atr_pct": 2.0, "stock_min_weak_dims": 9, "sector_min_weak_dims": 9, "min_pillars_weak": 9}]
    sm, se, mp, _ = _pick_atr_tier_dims(None, tiers, base_stock_min=2, base_sector_min=2, base_min_pillars=2)
    assert (sm, se, mp) == (2, 2, 2)
