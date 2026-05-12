"""选股 load_df：优先 kline_store SQLite（前复权与 sync 一致）。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from kline_store import init_schema, open_store_connection, upsert_bars
from quant_core import selector


def _seed_db(path: Path, *, secid: str, n_bars: int) -> None:
    conn = open_store_connection(path)
    try:
        init_schema(conn)
        base = date.today() - timedelta(days=n_bars - 1)
        rows: list[tuple[str, float, float, float, float, float]] = []
        for i in range(n_bars):
            d = (base + timedelta(days=i)).isoformat()
            px = 10.0 + i * 0.01
            rows.append((d, px, px + 0.5, px - 0.5, px + 0.1, 1_000_000.0))
        upsert_bars(conn, secid, rows)
    finally:
        conn.close()


def test_read_ohlcv_tail_rows_order_and_length(tmp_path: Path) -> None:
    from kline_store import read_ohlcv_tail_rows

    db = tmp_path / "t.db"
    _seed_db(db, secid="0.000001", n_bars=50)
    tail = read_ohlcv_tail_rows(db, "0.000001", lmt=45)
    assert tail is not None
    assert len(tail) == 45
    dates = [r[0] for r in tail]
    assert dates == sorted(dates)
    assert dates[-1] == date.today().isoformat()


def test_load_df_prefers_sqlite_no_pro_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "k.db"
    _seed_db(db, secid="0.000001", n_bars=60)

    cfg = {
        "sources": {"quote_ut": "ea"},
        "kline_store": {"enabled": True, "db_path": str(db)},
        "quant_selector": {
            "use_tushare_for_daily": True,
            "use_sqlite_cache": True,
            "max_stale_calendar_days": 2,
            "tushare_rt_k_enabled": False,
        },
    }

    def _no_pro_bar(*_a, **_k):
        raise AssertionError("fetch_stock_kline_rows_pro_bar should not be called")

    monkeypatch.setattr(
        "quote_tushare.fetch_stock_kline_rows_pro_bar",
        _no_pro_bar,
    )

    df = selector.load_df("000001", lookback=50, cfg=cfg)
    assert df is not None
    assert len(df) >= 30


def test_load_df_stale_sqlite_falls_through_to_pro_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "old.db"
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        old = date.today() - timedelta(days=10)
        rows = []
        for i in range(50):
            d = (old - timedelta(days=49 - i)).isoformat()
            px = 10.0 + i * 0.01
            rows.append((d, px, px + 0.5, px - 0.5, px + 0.1, 1e6))
        upsert_bars(conn, "0.000001", rows)
    finally:
        conn.close()

    cfg = {
        "sources": {},
        "kline_store": {"enabled": True, "db_path": str(db)},
        "quant_selector": {
            "use_tushare_for_daily": True,
            "use_sqlite_cache": True,
            "max_stale_calendar_days": 2,
            "tushare_rt_k_enabled": False,
        },
    }

    called: list[int] = []

    def fake_pro_bar(secid: str, want: int):
        called.append(want)
        return [
            ("2020-01-02", 1.0, 1.1, 0.9, 1.05, 1e6),
            ("2020-01-03", 1.05, 1.2, 1.0, 1.1, 1e6),
        ]

    monkeypatch.setattr(
        "quote_tushare.fetch_stock_kline_rows_pro_bar",
        fake_pro_bar,
    )

    selector.load_df("000001", lookback=50, cfg=cfg)
    assert called, "stale SQLite should fall back to pro_bar"


def test_sqlite_last_bar_fresh_boundary() -> None:
    from datetime import timedelta

    today = date.today()
    assert selector._sqlite_last_bar_fresh(today.isoformat(), 2) is True
    assert selector._sqlite_last_bar_fresh((today - timedelta(days=2)).isoformat(), 2) is True
    assert selector._sqlite_last_bar_fresh((today - timedelta(days=3)).isoformat(), 2) is False
