"""券商交割单周报解析（合成数据）。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from weekly_report import (
    _biz_kind,
    closed_positions_in_week,
    format_broker_daily_text,
    format_weekly_summary_text,
    load_mapping_config,
    parse_ledger_from_df,
    positions_at_date,
    resolve_period_bounds,
    trades_on_day,
    week_realized_sum,
)


@pytest.fixture
def mapping() -> dict:
    return load_mapping_config(Path(__file__).resolve().parents[1] / "mapping_config.json")


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": "600000",
                "name": "浦发银行",
                "settle_date": "2026-05-12",
                "business": "证券买入",
                "price": 10.0,
                "quantity": 1000,
                "amount": 10000.0,
                "settlement_amount": -10005.0,
                "cash_balance": 50000.0,
                "currency": "人民币",
                "order_id": "1",
                "trade_time": "09:30:00",
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "settle_date": "2026-05-16",
                "business": "证券卖出",
                "price": 11.0,
                "quantity": 1000,
                "amount": 11000.0,
                "settlement_amount": 10990.0,
                "cash_balance": 60990.0,
                "currency": "人民币",
                "order_id": "2",
                "trade_time": "14:00:00",
            },
        ]
    )


def test_parse_buy_sell_realized(mapping: dict) -> None:
    pos, events, cash, meta = parse_ledger_from_df(_sample_df(), mapping)
    assert meta["rows_parsed"] == 2
    assert cash == pytest.approx(60990.0)
    assert pos["600000"].shares == 0
    sells = [e for e in events if e["event"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["realized_profit"] == pytest.approx(985.0, rel=0.01)


def test_closed_in_week(mapping: dict) -> None:
    _, events, _, _ = parse_ledger_from_df(_sample_df(), mapping)
    w0, w1 = date(2026, 5, 12), date(2026, 5, 16)
    closed = closed_positions_in_week(events, w0, w1)
    assert len(closed) == 1
    assert closed[0].code == "600000"
    assert closed[0].realized_profit == pytest.approx(985.0, rel=0.01)


def test_week_realized_sum(mapping: dict) -> None:
    _, events, _, _ = parse_ledger_from_df(_sample_df(), mapping)
    s = week_realized_sum(events, date(2026, 5, 12), date(2026, 5, 16))
    assert s == pytest.approx(985.0, rel=0.01)


def test_biz_kind(mapping: dict) -> None:
    assert _biz_kind("证券买入", mapping) == "buy"
    assert _biz_kind("证券卖出", mapping) == "sell"
    assert _biz_kind("银行转证券", mapping) == "skip"


def test_resolve_daily_bounds() -> None:
    d = date(2026, 5, 16)
    assert resolve_period_bounds("daily", d) == (d, d)


def test_trades_on_day(mapping: dict) -> None:
    _, events, _, _ = parse_ledger_from_df(_sample_df(), mapping)
    trades = trades_on_day(events, date(2026, 5, 16))
    assert len(trades) == 1
    assert trades[0]["event"] == "sell"
    assert trades[0]["realized_profit"] == pytest.approx(985.0, rel=0.01)


def test_format_daily_summary() -> None:
    report = {
        "period": "daily",
        "period_range": {"start": "2026-05-16", "end": "2026-05-16"},
        "source_file": "test.xlsx",
        "day_trades": [
            {
                "code": "600000",
                "name": "浦发银行",
                "event": "sell",
                "quantity": 1000,
                "price": 11.0,
                "realized_profit": 985.0,
            }
        ],
        "closed_positions": [
            {
                "code": "600000",
                "name": "浦发银行",
                "shares": 1000,
                "avg_sell_price": 11.0,
                "realized_profit": 985.0,
            }
        ],
        "holdings": [],
        "totals": {
            "realized_profit_period": 985.0,
            "unrealized_change": 0.0,
            "unrealized_period_end": 0.0,
            "unrealized_period_start": 0.0,
            "total_pnl_day": 985.0,
            "cash_available": 60990.0,
            "market_value": 0.0,
            "total_assets": 60990.0,
        },
        "warnings": [],
    }
    text = format_broker_daily_text(report)
    assert "券商交割单日结" in text
    assert "当日合计" in text
    assert "600000" in text


def test_format_summary() -> None:
    report = {
        "week": {"start": "2026-05-12", "end": "2026-05-16"},
        "source_file": "test.xlsx",
        "closed_positions": [
            {
                "code": "600000",
                "name": "浦发银行",
                "shares": 1000,
                "avg_sell_price": 11.0,
                "realized_profit": 985.0,
            }
        ],
        "holdings": [],
        "totals": {
            "realized_profit_week": 985.0,
            "unrealized_change": 0.0,
            "unrealized_week_end": 0.0,
            "unrealized_week_start": 0.0,
            "cash_available": 60990.0,
            "market_value": 0.0,
            "total_assets": 60990.0,
        },
        "warnings": [],
    }
    text = format_weekly_summary_text(report)
    assert "券商交割单周报" in text
    assert "600000" in text
