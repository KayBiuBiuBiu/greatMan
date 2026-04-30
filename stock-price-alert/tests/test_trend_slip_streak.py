"""trend_slip_confirm：连续交易日弱势 streak 与清理。"""

from __future__ import annotations

from pathlib import Path

from kline_store import init_schema, open_store_connection
from trend_slip_confirm import consecutive_trend_slip_notify_ok


def _seed_klines(conn, secid: str, dates: list[str]) -> None:
    for d in dates:
        conn.execute(
            """
            INSERT INTO daily_klines(secid, trade_date, open, high, low, close, volume)
            VALUES(?,?,?,?,?,?,?)
            """,
            (secid, d, 1.0, 1.0, 1.0, 1.0, 0.0),
        )


def test_consecutive_trend_slip_notify_two_trade_days(tmp_path: Path) -> None:
    root = tmp_path
    db = tmp_path / "kl.db"
    cfg: dict = {
        "kline_store": {"enabled": True, "db_path": "kl.db"},
        "trend_slippage_alert": {"require_consecutive_trade_days": 2},
    }
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        _seed_klines(
            conn,
            "1.600000",
            ["2099-01-02", "2099-01-03", "2099-01-06", "2099-01-07"],
        )
        conn.commit()
    finally:
        conn.close()

    ok1, n1, _ = consecutive_trend_slip_notify_ok(
        cfg,
        root=root,
        rk="rk_test",
        secid="1.600000",
        anchor_td="2099-01-06",
        raw_fire=True,
    )
    assert ok1 is False and n1 == 1

    ok2, n2, _ = consecutive_trend_slip_notify_ok(
        cfg,
        root=root,
        rk="rk_test",
        secid="1.600000",
        anchor_td="2099-01-07",
        raw_fire=True,
    )
    assert ok2 is True and n2 == 2

    ok3, n3, _ = consecutive_trend_slip_notify_ok(
        cfg,
        root=root,
        rk="rk_test",
        secid="1.600000",
        anchor_td="2099-01-08",
        raw_fire=False,
    )
    assert ok3 is False and n3 == 0

    ok4, n4, _ = consecutive_trend_slip_notify_ok(
        cfg,
        root=root,
        rk="rk_test",
        secid="1.600000",
        anchor_td="2099-01-08",
        raw_fire=True,
    )
    assert ok4 is False and n4 == 1


def test_require_one_matches_raw_fire(tmp_path: Path) -> None:
    cfg: dict = {
        "kline_store": {"enabled": True, "db_path": "x.db"},
        "trend_slippage_alert": {"require_consecutive_trade_days": 1},
    }
    ok_t, _, _ = consecutive_trend_slip_notify_ok(
        cfg, root=tmp_path, rk="a", secid="1.1", anchor_td="2099-01-01", raw_fire=True
    )
    ok_f, _, _ = consecutive_trend_slip_notify_ok(
        cfg, root=tmp_path, rk="a", secid="1.1", anchor_td="2099-01-01", raw_fire=False
    )
    assert ok_t is True and ok_f is False
