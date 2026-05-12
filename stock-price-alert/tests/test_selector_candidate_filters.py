"""quant_selector.select_candidate_filters：区间位置 + 策略卖出侧参考分。"""

from __future__ import annotations

import pandas as pd

from quant_core import selector


def _th(**kwargs: object) -> dict:
    base = {
        "enabled": True,
        "range_lookback_days": 20,
        "range_position_max": 0.7,
        "strategy_sell_score_max": 70.0,
        "skip_if_has_position_tag": True,
    }
    base.update(kwargs)
    return {"select_candidate_filters": base}


def test_range_position_demote() -> None:
    df = pd.DataFrame(
        {
            "low": [100.0] * 25,
            "high": [110.0] * 25,
            "close": [109.0] * 25,
            "volume": [1e6] * 25,
        }
    )
    r = selector._select_candidate_filter_demote_reason(
        code="600000",
        df=df,
        cfg={},
        th=_th(),
        prior_bucket="优质股",
        prior_reason="测试",
        held_codes=frozenset(),
    )
    assert r is not None
    assert "区间偏高" in r


def test_held_skips_filter() -> None:
    df = pd.DataFrame(
        {
            "low": [100.0] * 25,
            "high": [110.0] * 25,
            "close": [109.0] * 25,
            "volume": [1e6] * 25,
        }
    )
    r = selector._select_candidate_filter_demote_reason(
        code="600000",
        df=df,
        cfg={},
        th=_th(),
        prior_bucket="优质股",
        prior_reason="测试",
        held_codes=frozenset(["600000"]),
    )
    assert r is None


def test_disabled_no_demote() -> None:
    df = pd.DataFrame(
        {
            "low": [100.0] * 25,
            "high": [110.0] * 25,
            "close": [109.0] * 25,
            "volume": [1e6] * 25,
        }
    )
    r = selector._select_candidate_filter_demote_reason(
        code="600000",
        df=df,
        cfg={},
        th=_th(enabled=False),
        prior_bucket="优质股",
        prior_reason="测试",
        held_codes=frozenset(),
    )
    assert r is None


def test_sell_side_score_at_threshold_demotes(monkeypatch) -> None:
    """sell_mx 等于 strategy_sell_score_max 时亦淘汰（>=）。"""
    monkeypatch.setattr(selector, "_range_position_in_window", lambda _df, _n: 0.5)
    monkeypatch.setattr(
        selector,
        "_max_strategy_sell_side_score",
        lambda _p, _kl, min_score_by_strategy=None: 70.0,
    )
    df = pd.DataFrame(
        {
            "low": [100.0] * 25,
            "high": [120.0] * 25,
            "close": [100.0] * 25,
            "volume": [1e6] * 25,
        }
    )
    r = selector._select_candidate_filter_demote_reason(
        code="600000",
        df=df,
        cfg={},
        th=_th(strategy_sell_score_max=70.0),
        prior_bucket="优质股",
        prior_reason="测试",
        held_codes=frozenset(),
    )
    assert r is not None
    assert "卖出侧参考分" in r
    assert "≥70.0" in r or "≥70" in r


def test_sell_side_score_demote(monkeypatch) -> None:
    monkeypatch.setattr(selector, "_range_position_in_window", lambda _df, _n: 0.5)
    df = pd.DataFrame(
        {
            "low": [100.0] * 25,
            "high": [120.0] * 25,
            "close": [100.0] * 24 + [116.0],
            "volume": [1e6] * 25,
        }
    )
    r = selector._select_candidate_filter_demote_reason(
        code="600000",
        df=df,
        cfg={},
        th=_th(strategy_sell_score_max=50.0),
        prior_bucket="观察股",
        prior_reason="测试",
        held_codes=frozenset(),
    )
    assert r is not None
    assert "卖出侧参考分" in r


def test_held_stock_codes_from_cfg() -> None:
    cfg = {
        "watchlist": [
            {"code": "600001", "tags": "持仓", "enabled": True},
            {"code": "600002", "tags": "自选", "enabled": True},
        ]
    }
    s = selector.held_stock_codes_from_cfg(cfg)
    assert s == frozenset({"600001"})
