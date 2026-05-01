"""macro_risk.get_market_regime 与上证缓存解析。"""

from __future__ import annotations

import macro_risk as mr


def test_get_market_regime_bull_above_ma(monkeypatch):
    closes = [100.0] * 19 + [150.0]
    assert len(closes) == 20
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: closes)
    monkeypatch.setattr(mr, "get_sh_index_volumes_cached", lambda: None)
    assert mr.get_market_regime(ma_period=20, dynamic_cfg=None) == "bull"


def test_get_market_regime_bear_below_ma(monkeypatch):
    closes = [150.0] * 19 + [100.0]
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: closes)
    monkeypatch.setattr(mr, "get_sh_index_volumes_cached", lambda: None)
    assert mr.get_market_regime(ma_period=20, dynamic_cfg=None) == "bear"


def test_get_market_regime_short_series_bear(monkeypatch):
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: [1.0, 2.0])
    assert mr.get_market_regime(ma_period=20, dynamic_cfg=None) == "bear"


def test_volume_filter_low_volume_returns_bear(monkeypatch):
    closes = [100.0] * 24 + [150.0]
    vols = [1_000_000.0] * 25
    vols[-1] = 1.0
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: closes)
    monkeypatch.setattr(mr, "get_sh_index_volumes_cached", lambda: vols)
    cfg = {"use_volume_filter": True, "volume_ratio_active": 1.2}
    assert mr.get_market_regime(ma_period=20, dynamic_cfg=cfg) == "bear"


def _flat_closes_with_last_uptrend(n: int = 80, last: float = 105.0) -> list[float]:
    base = [100.0] * (n - 1)
    return base + [last]


def test_get_market_mood_three_tier_strong_bull(monkeypatch):
    """价在 MA 之上、RSI 高、布林有宽度 → strong_bull。"""
    closes = _flat_closes_with_last_uptrend(80, 108.0)
    # 人为抬高末端涨幅使 RSI > 56
    for i in range(-15, 0):
        closes[i] = closes[i - 1] * 1.01
    closes[-1] = closes[-2] * 1.02
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: closes)
    monkeypatch.setattr(mr, "get_sh_index_volumes_cached", lambda: None)
    cfg = {
        "ma_period": 20,
        "rsi_period": 14,
        "rsi_strong_bull_min": 55.0,
        "rsi_weak_bear_max": 44.0,
        "bb_period": 20,
        "bb_width_min_for_strong": 0.001,
        "use_volume_filter": False,
    }
    assert mr.get_market_mood_three_tier(dynamic_cfg=cfg) == "strong_bull"


def test_get_market_mood_three_tier_weak_bear_below_ma(monkeypatch):
    closes = [120.0] * 60 + [90.0]
    monkeypatch.setattr(mr, "get_sh_index_closes_cached", lambda: closes)
    monkeypatch.setattr(mr, "get_sh_index_volumes_cached", lambda: None)
    assert mr.get_market_mood_three_tier(dynamic_cfg={"ma_period": 20}) == "weak_bear"


def test_sector_rs_bucket_outperform():
    idx = [100.0] * 25
    sec = [100.0] * 24 + [102.0]
    assert mr.sector_rs_bucket(sec, idx, ret_days=20, out_pct=0.005, under_pct=-0.005) == "outperform"


def test_sector_rs_bucket_underperform():
    idx = [100.0] * 25
    sec = [100.0] * 24 + [97.0]
    assert mr.sector_rs_bucket(sec, idx, ret_days=20, out_pct=0.005, under_pct=-0.005) == "underperform"
