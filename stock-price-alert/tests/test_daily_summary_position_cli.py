"""daily_summary：position_cli 分区与 hold/unhold/sell 语义。"""

from __future__ import annotations

from pathlib import Path

from daily_summary import (
    _cli_operation_kind_label_cn,
    _collect_position_operations_today,
    _format_position_operation_mail_line,
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


def test_cli_operation_kind_labels() -> None:
    assert _cli_operation_kind_label_cn("buy") == "买入"
    assert _cli_operation_kind_label_cn("ADD") == "加仓"
    assert _cli_operation_kind_label_cn("reduce") == "减持"
    assert _cli_operation_kind_label_cn("unhold") == "清仓"


def test_collect_position_operations_from_tmp_log(tmp_path: Path) -> None:
    log_path = tmp_path / "data" / "position_cli_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        """[
  {"time": "2026-05-20 09:00:01", "kind": "buy", "code": "002237", "name": "恒邦",
   "hold_shares": 100, "cost_price": 10.5, "cmd_shares": 100, "cmd_cost": 10.5},
  {"time": "2026-05-20 14:00:00", "kind": "reduce", "code": "600711", "name": "盛屯",
   "hold_shares": 5000, "cost_price": 12.3, "note": "卖200股"}
]
""",
        encoding="utf-8",
    )
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    rows = _collect_position_operations_today(cfg_path, "2026-05-20")
    assert len(rows) == 2
    assert rows[0]["label"] == "买入" and rows[0]["code"] == "002237"
    assert rows[1]["kind"] == "reduce" and rows[1]["hold_shares"] == 5000
    line = _format_position_operation_mail_line(rows[1])
    assert "减持" in line and "600711" in line and "余 5000" in line
