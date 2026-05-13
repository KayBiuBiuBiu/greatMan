"""sum_realized_close_reduce_pnl_for_day 仅统计卖出侧 kind。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from position_ledger import (
    append_ledger_event,
    init_ledger_schema,
    sum_realized_close_reduce_pnl_for_day,
    sum_realized_pnl_for_day,
)


def _db() -> Path:
    fd, name = tempfile.mkstemp(suffix=".db")
    import os

    os.close(fd)
    p = Path(name)
    from position_ledger import _connect

    conn = _connect(p)
    try:
        init_ledger_schema(conn)
    finally:
        conn.close()
    return p


def test_close_reduce_sum_excludes_hold_add() -> None:
    dbp = _db()
    try:
        append_ledger_event(
            dbp,
            kind="hold_add",
            code="600711",
            name="x",
            shares_after=12300,
            qty_traded=8600,
            exec_price=13.2,
            realized_pnl=999.0,
            day_iso="2026-05-20",
            op_type="add",
        )
        append_ledger_event(
            dbp,
            kind="reduce",
            code="600711",
            name="x",
            shares_before=100,
            shares_after=50,
            qty_traded=50,
            exec_price=12.0,
            realized_pnl=-40.0,
            day_iso="2026-05-20",
        )
        append_ledger_event(
            dbp,
            kind="close",
            code="000001",
            name="y",
            shares_before=200,
            shares_after=0,
            qty_traded=200,
            exec_price=11.0,
            realized_pnl=100.0,
            day_iso="2026-05-20",
        )
        assert sum_realized_pnl_for_day(dbp, "2026-05-20") == pytest.approx(999 - 40 + 100)
        assert sum_realized_close_reduce_pnl_for_day(dbp, "2026-05-20") == pytest.approx(
            -40.0 + 100.0
        )
    finally:
        dbp.unlink(missing_ok=True)
