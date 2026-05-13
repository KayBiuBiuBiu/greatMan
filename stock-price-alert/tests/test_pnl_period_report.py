"""pnl_period_report：按 daily_summary_history 汇总区间已实现。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from pnl_period_report import (
    _due_reports,
    aggregate_trades_from_history,
    format_pnl_period_email,
)


def test_aggregate_sums_realized(tmp_path: Path) -> None:
    h = tmp_path / "daily_summary_history"
    h.mkdir(parents=True)
    for day, r in [("2026-03-01", 10.0), ("2026-03-02", 5.5)]:
        p = h / f"{day}.json"
        p.write_text(
            '{"date":"%s","trades":{"realized_profit":%s,"unrealized_profit":100,"net_profit":110}}'
            % (day, r),
            encoding="utf-8",
        )
    agg = aggregate_trades_from_history(h, date(2026, 3, 1), date(2026, 3, 2))
    assert agg["days_with_summary"] == 2
    assert agg["realized_profit_sum"] == pytest.approx(15.5)
    assert agg["last_day"] == "2026-03-02"
    assert agg["last_day_unrealized"] == 100.0


def test_due_july_first_h1() -> None:
    st: dict = {}
    oa = {"pnl_period_report_catchup_days": 5}
    now = datetime(2026, 7, 1, 16, 0, 0)
    due = _due_reports(now, st, oa)
    kinds = {d.state_key for d in due}
    assert "__pnl_report_month__" in kinds  # 6 月
    assert "__pnl_report_h1__" in kinds


def test_due_jan_first_h2_and_year() -> None:
    st: dict = {}
    oa = {"pnl_period_report_catchup_days": 5}
    now = datetime(2027, 1, 4, 16, 0, 0)  # 周三，补发 1 月报告
    due = _due_reports(now, st, oa)
    keys = {d.state_key for d in due}
    assert "__pnl_report_month__" in keys  # 2026-12
    assert "__pnl_report_h2__" in keys
    assert "__pnl_report_year__" in keys


def test_format_email_contains_disclaimer() -> None:
    agg = {
        "start": "2026-01-01",
        "end": "2026-01-31",
        "days_with_summary": 3,
        "days_missing_json": 28,
        "realized_profit_sum": 1.23,
        "last_day": "2026-01-31",
        "last_day_unrealized": 10.0,
        "last_day_net": 11.0,
    }
    text = format_pnl_period_email(title="【月结】2026-01", agg=agg)
    assert "已实现" in text and "快照" in text
