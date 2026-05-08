"""策略分阈值与买入实时过滤（量比、大盘 weak_bear）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_core import strategies as strat


def test_min_score_by_strategy_blocks_buy_only() -> None:
    kline_buy = {"ma5": 10.0, "ma20": 9.5, "low20": 8.0, "high20": 12.0}
    price_buy = 9.7
    hi = strat.evaluate_all_strategies(
        price_buy,
        kline_buy,
        min_score_by_strategy={"ma_dip": 100.0},
    )
    assert not any(s.strategy == "ma_dip" and s.action == "buy_watch" for s in hi)
    ok = strat.evaluate_all_strategies(
        price_buy,
        kline_buy,
        min_score_by_strategy={"ma_dip": 50.0},
    )
    assert any(s.strategy == "ma_dip" and s.action == "buy_watch" for s in ok)

    kline_sell = {"ma5": 8.0, "ma20": 9.5, "low20": 8.0, "high20": 12.0}
    price_sell = 9.0
    blocked = strat.evaluate_all_strategies(
        price_sell,
        kline_sell,
        min_score_by_strategy={"ma_dip": 100.0},
    )
    assert any(s.strategy == "ma_dip" and s.action == "risk_reduce" for s in blocked)


def test_strategy_buy_realtime_blocked() -> None:
    from run_alert import _strategy_buy_realtime_blocked, merge_full_config

    ex = Path(__file__).resolve().parent.parent / "config.example.json"
    cfg = merge_full_config(json.loads(ex.read_text(encoding="utf-8")))

    pack_wb = {"_ps_vol_ratio": 1.5, "_strategy_buy_mood_tier": "weak_bear"}
    r1 = _strategy_buy_realtime_blocked(pack_wb, cfg)
    assert r1 is not None
    assert "weak_bear" in r1

    pack_ok = {"_ps_vol_ratio": 1.5, "_strategy_buy_mood_tier": "range"}
    assert _strategy_buy_realtime_blocked(pack_ok, cfg) is None

    pack_low_vol = {"_ps_vol_ratio": 0.8, "_strategy_buy_mood_tier": "range"}
    r3 = _strategy_buy_realtime_blocked(pack_low_vol, cfg)
    assert r3 is not None
    assert "量比" in r3

    cfg_off = json.loads(ex.read_text(encoding="utf-8"))
    cfg_off["strategy_buy_filter"] = {"enabled": False}
    cfg2 = merge_full_config(cfg_off)
    assert _strategy_buy_realtime_blocked(pack_wb, cfg2) is None


@pytest.mark.parametrize(
    "score,p1,w1,p3,expect_bucket",
    [
        (7.0, 0.0, 50.0, -5.0, "优质股"),
        (6.9, 0.0, 50.0, -5.0, "观察股"),
        (5.5, -2.0, 45.0, -10.0, "观察股"),
    ],
)
def test_selector_classify_thresholds(
    score: float,
    p1: float,
    w1: float,
    p3: float,
    expect_bucket: str,
) -> None:
    from quant_core.selector import _classify

    th = {
        "score_min_quality": 7.0,
        "score_min_watch": 5.5,
        "profit_1y_min": 0.0,
        "win_1y_min": 50.0,
        "profit_3y_floor": -8.0,
    }
    bt1 = {"profit": p1, "win": w1, "trades": 3}
    bt3 = {"profit": p3, "win": 40.0, "trades": 5}
    bt5 = {"profit": -10.0, "win": 30.0, "trades": 8}
    bucket, _ = _classify(score, bt1, bt3, bt5, th=th)
    assert bucket == expect_bucket
