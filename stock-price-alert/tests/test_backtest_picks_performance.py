"""backtest_picks_performance 工具函数烟测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kline_store import init_schema, open_store_connection, upsert_bars
from backtest_picks_performance import (
    code_to_secid,
    forward_close_return,
    load_picks_records,
)


def test_code_to_secid() -> None:
    assert code_to_secid("600000").startswith("1.")
    assert code_to_secid("000001").startswith("0.")


def test_forward_return_and_load_picks(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        sid = code_to_secid("600000")
        rows = []
        for i, d in enumerate(
            [
                "2026-04-01",
                "2026-04-02",
                "2026-04-03",
                "2026-04-06",
                "2026-04-07",
                "2026-04-08",
                "2026-04-09",
                "2026-04-10",
            ]
        ):
            c = 10.0 + i * 0.1
            rows.append((d, c, c + 0.05, c - 0.05, c, 1e6))
        upsert_bars(conn, sid, rows)
    finally:
        conn.close()

    conn = open_store_connection(db)
    try:
        r, mdd = forward_close_return(conn, sid, "2026-04-01", 5)
        assert r is not None
        assert pytest.approx(r, rel=1e-6) == (float(rows[5][4]) - 10.0) / 10.0
        assert mdd is not None
    finally:
        conn.close()

    jp = tmp_path / "2026-04-01.json"
    jp.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-01T09:00:00",
                "优质股": [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "score": 7.2,
                        "reason": "因子与回测双重达标",
                        "ml_forward4_up_prob": 0.55,
                    }
                ],
                "观察股": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recs = load_picks_records([jp], include_quality=True, include_watch=True, include_reject=False)
    assert len(recs) == 1
    assert recs[0]["code"] == "600000"
