"""indicator_last 表读写与 kline 合并。"""

from __future__ import annotations

import sqlite3

from kline_indicators import (
    merge_indicator_last_into_kline,
    read_indicator_last,
    upsert_indicator_last,
)
from kline_store import init_schema


def test_indicator_last_merge_macd(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    upsert_indicator_last(
        conn,
        "0.000001",
        trade_date="2026-04-28",
        ma5=1.0,
        ma20=2.0,
        ma60=3.0,
        high20=4.0,
        low20=0.5,
        atr_pct=2.5,
        macd_bundle={
            "dif": [0.1, 0.0, -0.05],
            "dea": [0.11, 0.05, 0.0],
            "hist": [0.1, 0.2, -0.1, -0.2],
        },
        computed_iso="2026-04-29T00:00:00",
    )
    snap = read_indicator_last(conn, "0.000001")
    conn.close()
    assert snap is not None
    out: dict = {
        "ma5": 1.0,
        "kline_last_trade_date": "2026-04-28",
    }
    merge_indicator_last_into_kline(out, snap)
    assert "precomputed_macd" in out
    assert len(out["precomputed_macd"]["hist"]) == 4
    assert out["precomputed_atr_pct"] == 2.5
