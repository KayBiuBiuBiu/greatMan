"""今日优质股 / 热门板块优质股：quality_stock_filters 回调过滤。"""

from __future__ import annotations

from run_alert import (
    _filter_watch_packs_for_quality_display,
    _quality_stock_filters_from_cfg,
    _should_display_quality_stock,
)


def _cfg(**qsf_overrides: object) -> dict:
    qsf = {
        "enabled": True,
        "min_change_pct": -2.0,
        "max_change_pct": 5.0,
        "max_intraday_position": 0.7,
        "min_volume_ratio": 1.0,
        "require_buy_signal": False,
    }
    qsf.update(qsf_overrides)
    return {"display": {"quality_stock_filters": qsf}}


def _pack(
    *,
    code: str = "600000",
    change_pct: float = 1.0,
    intraday_position: float | None = 0.5,
    hold_shares: int = 0,
    vol_ratio: float | None = 1.5,
) -> dict:
    q: dict = {
        "code": code,
        "price": 10.0,
        "pre_close": 9.9,
        "change_pct": change_pct,
        "open": 9.95,
        "high": 10.2,
        "low": 9.8,
    }
    if intraday_position is not None:
        q["intraday_position"] = intraday_position
    vols = [100.0] * 20 + [150.0] if vol_ratio is not None else [100.0] * 21
    if vol_ratio is not None and vol_ratio != 1.5:
        vols[-1] = 100.0 * vol_ratio
    return {
        "q": q,
        "rule": {"hold_shares": hold_shares},
        "kline": {
            "ma5": 9.5,
            "ma20": 9.0,
            "low20": 8.0,
            "high20": 12.0,
            "volumes": vols,
        },
    }


def test_quality_stock_filters_defaults(merged_cfg: dict) -> None:
    qsf = merged_cfg["display"]["quality_stock_filters"]
    assert qsf["enabled"] is True
    assert qsf["min_change_pct"] == -2.0
    assert qsf["max_change_pct"] == 5.0
    assert qsf["max_intraday_position"] == 0.7
    assert qsf["min_volume_ratio"] == 1.0
    assert qsf["require_buy_signal"] is False


def test_should_display_quality_stock_passes_normal() -> None:
    assert _should_display_quality_stock(_pack(), _cfg()) is True


def test_should_display_quality_stock_blocks_large_drop() -> None:
    assert _should_display_quality_stock(_pack(change_pct=-3.0), _cfg()) is False


def test_should_display_quality_stock_blocks_chase() -> None:
    assert _should_display_quality_stock(_pack(change_pct=6.0), _cfg()) is False


def test_should_display_quality_stock_blocks_high_intraday_position() -> None:
    assert _should_display_quality_stock(_pack(intraday_position=0.85), _cfg()) is False


def test_should_display_quality_stock_skips_intraday_when_missing() -> None:
    p = _pack(intraday_position=None)
    p["q"].pop("open", None)
    p["q"].pop("high", None)
    p["q"].pop("low", None)
    assert _should_display_quality_stock(p, _cfg()) is True


def test_should_display_quality_stock_blocks_low_volume_ratio() -> None:
    assert _should_display_quality_stock(_pack(vol_ratio=0.5), _cfg()) is False


def test_held_stock_exempt_from_quality_filter() -> None:
    p = _pack(change_pct=-10.0, intraday_position=0.99, vol_ratio=0.1, hold_shares=100)
    assert _should_display_quality_stock(p, _cfg()) is True


def test_filter_disabled_shows_all() -> None:
    packs = [_pack(change_pct=-10.0), _pack(change_pct=10.0)]
    out = _filter_watch_packs_for_quality_display(
        packs, _cfg(enabled=False), log_label="优质"
    )
    assert len(out) == 2


def test_quality_stock_filters_from_cfg_partial_override() -> None:
    cfg = _cfg(max_change_pct=8.0)
    qsf = _quality_stock_filters_from_cfg(cfg)
    assert qsf["max_change_pct"] == 8.0
    assert qsf["min_change_pct"] == -2.0
