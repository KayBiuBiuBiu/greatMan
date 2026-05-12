"""三柱趋势下滑：两柱退化触发、monkeypatch 技术柱与 monkeypatch 计数隔离。"""

from __future__ import annotations

import copy

import pytest

import trend_slippage_risk as tsr


def _long_closes(n: int = 50, base: float = 10.0) -> list[float]:
    return [base + i * 0.01 for i in range(n)]


def _minimal_kline(closes: list[float]) -> dict:
    n = len(closes)
    return {
        "opens": [float(c) for c in closes],
        "highs": [float(c) * 1.01 for c in closes],
        "lows": [float(c) * 0.99 for c in closes],
        "volumes": [1_000_000.0] * n,
        "ma5": closes[-1] * 1.01,
        "ma20": closes[-1] * 1.02,
        "ma60": closes[-1] * 1.03,
        "high20": closes[-1] * 1.5,
    }


def test_trend_disabled_all_off(merged_cfg: dict) -> None:
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["enabled"] = False
    closes = _long_closes()
    k = _minimal_kline(closes)
    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        1.0,
        0.0,
        sector_bk="801010.SI",
        sector_kline=k,
        sector_closes=closes,
        cfg=cfg,
    )
    assert tr.fire is False
    assert tr.sector_eligible is False


def test_two_pillar_fire_when_sector_ineligible(
    merged_cfg: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无有效板块柱时：个股弱 + 大盘弱 才触发。"""
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["enabled"] = True
    cfg["trend_slippage_alert"]["min_pillars_weak"] = 2
    closes = _long_closes()
    k = _minimal_kline(closes)

    monkeypatch.setattr(
        tsr,
        "_count_ma_pattern_macd_vol",
        lambda *a, **kwa: (3, ["mock个股弱"]),
    )

    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        0.5,
        -0.02,
        sector_bk=None,
        sector_kline=None,
        sector_closes=[],
        cfg=cfg,
    )
    assert tr.sector_eligible is False
    assert tr.fire is True


def test_three_pillar_uses_sector_when_eligible(
    merged_cfg: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["enabled"] = True
    cfg["trend_slippage_alert"]["min_pillars_weak"] = 2
    closes = _long_closes()
    k = _minimal_kline(closes)
    sc = _long_closes()

    def fake_count(price, kline, closes2, tc, tag_prefix: str = ""):
        if tag_prefix.startswith("个股"):
            return (0, [])
        if tag_prefix.startswith("板块"):
            return (3, ["mock板块弱"])
        return (0, [])

    monkeypatch.setattr(tsr, "_count_ma_pattern_macd_vol", fake_count)

    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        0.5,
        -0.02,
        sector_bk="801010.SI",
        sector_kline=k,
        sector_closes=sc,
        cfg=cfg,
    )
    assert tr.sector_eligible is True
    assert tr.fire is True


def test_atr_wilder_and_simple_ma_return_pct() -> None:
    closes = [10.0 + 0.01 * (i % 5) for i in range(60)]
    k = _minimal_kline(closes)
    w = tsr._atr_close_pct(closes, k, 14, method="wilder")
    s = tsr._atr_close_pct(closes, k, 14, method="simple_ma")
    assert w is not None and s is not None
    assert 0 < w < 5 and 0 < s < 5
