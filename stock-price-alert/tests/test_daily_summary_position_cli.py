"""daily_summary：position_cli 分区与 hold/unhold/sell 语义。"""

from __future__ import annotations

from daily_summary import (
    _partition_trades_from_position_cli,
    _padded_label,
    _report_stock_label,
    _stock_display_name,
)


def test_partition_hold_unhold_sell() -> None:
    entries = [
        {
            "time": "2026-05-12 10:00:00",
            "kind": "hold",
            "code": "000537",
            "name": "绿电",
            "hold_shares": 300,
            "cost_price": 9.8,
        },
        {
            "time": "2026-05-12 11:00:00",
            "kind": "unhold",
            "code": "000546",
            "name": "金圆",
            "removed_rows": 1,
        },
        {"time": "2026-05-12 12:00:00", "kind": "sell", "code": "002386", "name": "天原"},
        {
            "time": "2026-05-12 13:00:00",
            "kind": "hold_watch",
            "code": "600000",
            "name": "浦发",
        },
    ]
    buys, sells, pauses, watch = _partition_trades_from_position_cli(entries)
    assert len(buys) == 1 and buys[0]["hold_shares"] == 300
    assert len(sells) == 1 and sells[0]["removed_rows"] == 1
    assert len(pauses) == 1 and pauses[0]["code"] == "002386"
    assert len(watch) == 1 and watch[0]["code"] == "600000"


def test_stock_display_name_priority() -> None:
    cache = {"000001": "缓存名"}
    assert _stock_display_name("000001", "watch名", cache) == "watch名"
    assert _stock_display_name("000001", "", cache) == "缓存名"
    assert _stock_display_name("000001", "  ", cache) == "缓存名"
    assert _stock_display_name("999999", "", {}) == "999999"


def test_padded_label_truncates() -> None:
    assert len(_padded_label("abcdefghijklmn", 12)) == 12


def test_report_stock_label_name_with_code() -> None:
    assert _report_stock_label("绿发电力", "537") == "绿发电力(000537)"
    assert _report_stock_label("000537", "537") == "000537"
    assert _report_stock_label("", "000537") == "000537"


def test_partition_sell_partial_goes_to_sells() -> None:
    entries = [
        {
            "time": "2026-05-12 15:00:00",
            "kind": "sell_partial",
            "code": "600711",
            "name": "盛屯",
            "note": "卖100股",
        }
    ]
    buys, sells, pauses, watch = _partition_trades_from_position_cli(entries)
    assert sells and not pauses
