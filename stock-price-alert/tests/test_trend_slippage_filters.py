"""趋势预警：忽略列表与价格/量过滤。"""

from __future__ import annotations

import copy

import trend_slippage_risk as tsr


def _k50() -> tuple[list[float], dict]:
    closes = [10.0 + i * 0.02 for i in range(50)]
    n = len(closes)
    k = {
        "opens": list(closes),
        "highs": [c * 1.01 for c in closes],
        "lows": [c * 0.99 for c in closes],
        "volumes": [1_000_000.0 + i * 100 for i in range(n)],
        "ma5": closes[-1] * 1.01,
        "ma20": closes[-1] * 1.02,
        "ma60": closes[-1] * 1.03,
        "high20": closes[-1] * 1.5,
    }
    return closes, k


def test_alert_ignore_codes_skips(merged_cfg: dict) -> None:
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["alert_ignore_codes"] = ["600000"]
    closes, k = _k50()
    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        1.0,
        0.0,
        sector_bk=None,
        sector_kline=None,
        sector_closes=[],
        cfg=cfg,
        stock_code="600000",
    )
    assert tr.skipped_by_filter == "alert_ignore_codes"
    assert tr.fire is False


def test_min_price_skips(merged_cfg: dict) -> None:
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["min_price"] = 50.0
    closes, k = _k50()
    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        1.0,
        0.0,
        sector_bk=None,
        sector_kline=None,
        sector_closes=[],
        cfg=cfg,
    )
    assert tr.skipped_by_filter == "min_price"
    assert tr.fire is False


def test_min_volume_ratio_skips(merged_cfg: dict) -> None:
    cfg = copy.deepcopy(merged_cfg)
    cfg["trend_slippage_alert"]["min_volume_ratio"] = 5.0
    closes, k = _k50()
    vols = list(k["volumes"])
    vols[-1] = 1.0
    k["volumes"] = vols
    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        1.0,
        0.0,
        sector_bk=None,
        sector_kline=None,
        sector_closes=[],
        cfg=cfg,
    )
    assert tr.skipped_by_filter == "min_volume_ratio"


def test_sector_data_warning_when_no_bk(merged_cfg: dict) -> None:
    cfg = copy.deepcopy(merged_cfg)
    closes, k = _k50()
    tr = tsr.evaluate_trend_slippage_alert(
        float(closes[-1]),
        k,
        closes,
        1.0,
        0.0,
        sector_bk=None,
        sector_kline=None,
        sector_closes=[],
        cfg=cfg,
    )
    assert tr.sector_data_warning is not None
    assert "板块数据缺失" in tr.sector_data_warning
