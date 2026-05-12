from __future__ import annotations

from datetime import date

from midday_ops import (
    effective_console_quality_codes,
    intraday_position_from_ohlc,
    liquidity_warn_codes,
)
from quant_core.strategies import precompute_signal_proximity_hints


def test_intraday_position_from_ohlc() -> None:
    assert intraday_position_from_ohlc(
        {"price": 10.0, "high": 12.0, "low": 8.0, "open": 9.0}
    ) == 0.5
    assert intraday_position_from_ohlc({"price": 12.0, "high": 12.0, "low": 8.0}) == 1.0


def test_effective_console_quality_codes_intersect() -> None:
    st: dict = {
        "__midday_quality_codes__": {
            "date": date.today().isoformat(),
            "codes": ["600000", "000001"],
        }
    }
    base = {"600000", "600001", "000001"}
    eff = effective_console_quality_codes(base, st)
    assert eff == {"600000", "000001"}


def test_liquidity_warn_codes_reads_codes_list() -> None:
    st = {
        "__midday_liquidity_warn_codes__": {
            "date": date.today().isoformat(),
            "codes": ["600000"],
            "messages": [],
        }
    }
    assert liquidity_warn_codes(st) == {"600000"}


def test_precompute_signal_proximity_hints_smoke() -> None:
    kl = {
        "ma5": 10.0,
        "ma20": 10.0,
        "low20": 8.0,
        "high20": 12.0,
    }
    hints = precompute_signal_proximity_hints(
        9.5, kl, min_score_by_strategy=None, up_pct=5.0, down_pct=5.0
    )
    assert isinstance(hints, list)
