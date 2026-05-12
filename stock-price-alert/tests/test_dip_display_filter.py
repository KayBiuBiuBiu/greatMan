"""dip_display_filter：低吸优选控制台分区展示过滤。"""

from __future__ import annotations

from run_alert import _dip_pick_passes_display_filter, _is_sold_position_placeholder_pack


def test_dip_filter_skips_when_change_pct_high() -> None:
    pack = {
        "tagged": False,
        "rule": {"tags": ""},
        "q": {
            "price": 11.0,
            "pre_close": 10.0,
            "high": 11.0,
            "low": 10.0,
        },
    }
    box = {"enabled": True, "max_change_pct": 5.0, "max_intraday_position": 0.99}
    assert _dip_pick_passes_display_filter(pack, box) is False


def test_dip_filter_skips_when_intraday_position_high() -> None:
    pack = {
        "tagged": False,
        "rule": {"tags": ""},
        "q": {
            "price": 9.9,
            "pre_close": 10.0,
            "high": 10.0,
            "low": 8.0,
        },
    }
    box = {"enabled": True, "max_change_pct": 50.0, "max_intraday_position": 0.85}
    assert _dip_pick_passes_display_filter(pack, box) is False


def test_dip_filter_position_tag_does_not_exempt() -> None:
    """带「持仓」tags 仍按涨幅/日内位置过滤，与是否曾标记持仓无关。"""
    pack = {
        "tagged": False,
        "rule": {"tags": "持仓"},
        "q": {
            "price": 20.0,
            "pre_close": 10.0,
            "high": 20.0,
            "low": 10.0,
        },
    }
    box = {"enabled": True, "max_change_pct": 5.0, "max_intraday_position": 0.1}
    assert _dip_pick_passes_display_filter(pack, box) is False


def test_sold_position_placeholder_pack() -> None:
    assert _is_sold_position_placeholder_pack(
        {"rule": {"tags": "持仓", "hold_shares": 0}}
    )
    assert _is_sold_position_placeholder_pack(
        {"rule": {"tags": "中线持仓", "hold_shares": 0}}
    )
    assert not _is_sold_position_placeholder_pack(
        {"rule": {"tags": "持仓", "hold_shares": 100}}
    )
    assert not _is_sold_position_placeholder_pack(
        {"rule": {"tags": "自选", "hold_shares": 0}}
    )


def test_dip_filter_disabled() -> None:
    pack = {
        "tagged": False,
        "rule": {"tags": ""},
        "q": {"price": 11.0, "pre_close": 10.0, "high": 11.0, "low": 10.0},
    }
    box = {"enabled": False, "max_change_pct": 5.0, "max_intraday_position": 0.5}
    assert _dip_pick_passes_display_filter(pack, box) is True
