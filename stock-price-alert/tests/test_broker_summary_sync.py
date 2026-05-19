"""交割单回灌 daily_summary_history 与 trade_norm。"""

from __future__ import annotations

import json
from datetime import date as date_cls
from pathlib import Path

import pytest

from auto_tune_selector_filters import _summary_trade_net_and_activity, _trade_norm_from_daily_summary_file
from broker_summary_sync import (
    broker_trades_overlay_from_report,
    last_completed_trading_day,
    merge_broker_into_summary_history,
)
from weekly_report import broker_holdings_for_daily_summary, trade_dates_in_events


def test_broker_overlay_from_report() -> None:
    report = {
        "period": "daily",
        "period_range": {"start": "2026-05-16", "end": "2026-05-16"},
        "source_file": "test.xls",
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
        "totals": {
            "realized_profit_period": 985.0,
            "unrealized_change": 10.0,
            "total_pnl_day": 995.0,
        },
    }
    ov = broker_trades_overlay_from_report(report)
    assert ov["broker_net_profit"] == 995.0
    assert ov["source"] == "broker_xls"
    assert len(ov["broker_sells"]) == 1


def test_last_completed_trading_day() -> None:
    assert last_completed_trading_day(date_cls(2026, 5, 18)) == date_cls(2026, 5, 15)
    assert last_completed_trading_day(date_cls(2026, 5, 12)) == date_cls(2026, 5, 11)


def test_broker_holdings_for_daily_summary() -> None:
    report = {
        "holdings": [
            {
                "code": "600000",
                "name": "浦发银行",
                "hold_shares": 1000,
                "cost_price": 10.5,
                "close_price": 11.0,
                "unrealized_profit": 500.0,
            },
            {"code": "000001", "name": "平安", "hold_shares": 0},
        ]
    }
    rows = broker_holdings_for_daily_summary(report)
    assert len(rows) == 1
    assert rows[0]["code"] == "600000"
    assert rows[0]["hold_shares"] == 1000
    assert rows[0]["source"] == "broker_xls"


def test_merge_aligns_holdings(tmp_path: Path) -> None:
    day = "2026-05-16"
    hdir = tmp_path / "data" / "daily_summary_history"
    hdir.mkdir(parents=True)
    (hdir / f"{day}.json").write_text(
        json.dumps(
            {
                "date": day,
                "holdings": [{"code": "999999", "hold_shares": 1, "name": "旧"}],
                "trades": {},
            }
        ),
        encoding="utf-8",
    )
    report = {
        "period": "daily",
        "period_range": {"end": day},
        "holdings": [
            {
                "code": "600000",
                "name": "浦发银行",
                "hold_shares": 500,
                "cost_price": 10.0,
                "close_price": 10.5,
                "unrealized_profit": 250.0,
            }
        ],
        "totals": {"cash_available": 1000.0, "market_value": 5250.0},
    }
    ov = broker_trades_overlay_from_report(report)
    cfg = {"ops_automation": {"broker_sync_align_holdings": True}}
    merge_broker_into_summary_history(
        tmp_path, day, ov, report=report, cfg=cfg
    )
    doc = json.loads((hdir / f"{day}.json").read_text(encoding="utf-8"))
    assert doc["holdings"][0]["code"] == "600000"
    assert doc["holdings_watchlist"][0]["code"] == "999999"
    assert doc["trades"]["unrealized_positions"][0]["float_pnl_est"] == 250.0


def test_trade_dates_in_events() -> None:
    events = [
        {"settle_date": date_cls(2026, 5, 12)},
        {"settle_date": date_cls(2026, 5, 16)},
        {"settle_date": date_cls(2026, 5, 12)},
    ]
    assert trade_dates_in_events(events) == [
        date_cls(2026, 5, 12),
        date_cls(2026, 5, 16),
    ]


def test_merge_and_trade_norm(tmp_path: Path) -> None:
    day = "2026-05-16"
    hdir = tmp_path / "data" / "daily_summary_history"
    hdir.mkdir(parents=True)
    (hdir / f"{day}.json").write_text(
        json.dumps({"date": day, "trades": {"buys": [], "sells": [], "net_profit": 0}}),
        encoding="utf-8",
    )
    ov = {
        "source": "broker_xls",
        "broker_synced_at": "2026-05-18T12:00:00",
        "broker_net_profit": 500.0,
        "broker_realized_profit": 400.0,
        "broker_unrealized_change": 100.0,
        "broker_buys": [],
        "broker_sells": [{"code": "600000", "quantity": 100}],
        "broker_day_trades": [],
    }
    p = merge_broker_into_summary_history(tmp_path, day, ov, overwrite_net=True)
    doc = json.loads(p.read_text(encoding="utf-8"))
    tr = doc["trades"]
    assert tr["net_profit"] == 500.0
    assert tr["broker_net_profit"] == 500.0
    act, net = _summary_trade_net_and_activity(tr)
    assert act is True
    assert net == 500.0
    norm, ok = _trade_norm_from_daily_summary_file(p, 5000.0)
    assert ok is True
    assert norm > 0
