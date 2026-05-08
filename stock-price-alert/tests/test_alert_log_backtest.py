"""alert_events 表 + 远期收益与 bearish hit 计算。"""

from __future__ import annotations

import sqlite3

from alert_log_store import (
    compute_bearish_hit,
    compute_risk_stop_hit,
    compute_strategy_hit,
    evaluate_row,
    forward_returns_vs_anchor,
)
from kline_store import init_schema, open_store_connection
from quote_eastmoney import secid_for


def test_forward_returns_and_bearish_hit(tmp_path) -> None:
    db = tmp_path / "mix.db"
    conn = open_store_connection(db)
    init_schema(conn)
    secid = secid_for("600000", "sh")
    rows = [
        ("2025-06-02", 10.0),
        ("2025-06-03", 9.7),
        ("2025-06-04", 9.4),
        ("2025-06-05", 9.0),
        ("2025-06-06", 8.8),
        ("2025-06-09", 8.5),
    ]
    for td, c in rows:
        conn.execute(
            """
            INSERT INTO daily_klines (
                secid, trade_date, open, high, low, close, volume
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (secid, td, c, c, c, c, 1_000_000.0),
        )
    conn.execute(
        """
        INSERT INTO alert_events (
            fired_iso, anchor_trade_date, code, market, secid,
            alert_type, rk, anchor_price, summary, extra_json, eval_status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,'pending')
        """,
        (
            "2025-06-03T10:00:00",
            "2025-06-02",
            "600000",
            "sh",
            secid,
            "trend_slip",
            "600000:sh",
            10.0,
            "slip",
            None,
        ),
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    ev = conn.execute("SELECT * FROM alert_events WHERE id = 1").fetchone()
    th = {
        "bearish_hit_threshold_pct_1d": -2.0,
        "bearish_hit_threshold_pct_3d": -2.5,
        "bearish_hit_threshold_pct_5d": -3.0,
    }
    r1, r3, r5, hit = evaluate_row(conn, ev, th)
    conn.close()

    assert r1 is not None and abs(r1 - (9.7 - 10.0) / 10.0) < 1e-9
    assert r3 is not None
    assert hit == 1

    conn2 = open_store_connection(db)
    r1b, r3b, r5b = forward_returns_vs_anchor(
        conn2, secid, "2025-06-02", anchor_price=10.0
    )
    conn2.close()
    assert r1b is not None
    h2 = compute_bearish_hit(
        "trend_slip", None, r1b, r3b, r5b, th1=-2.0, th3=-2.5, th5=-3.0
    )
    assert h2 == 1


def test_price_band_hit_is_none(tmp_path) -> None:
    db = tmp_path / "pb.db"
    conn = open_store_connection(db)
    init_schema(conn)
    secid = secid_for("000001", "sz")
    for td, c in [("2025-06-02", 20.0), ("2025-06-03", 20.1)]:
        conn.execute(
            """
            INSERT INTO daily_klines (
                secid, trade_date, open, high, low, close, volume
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (secid, td, c, c, c, c, 1.0),
        )
    conn.execute(
        """
        INSERT INTO alert_events (
            fired_iso, anchor_trade_date, code, market, secid,
            alert_type, rk, anchor_price, summary, eval_status
        ) VALUES (?,?,?,?,?,?,?,?,?,'pending')
        """,
        (
            "2025-06-03T09:00:00",
            "2025-06-02",
            "000001",
            "sz",
            secid,
            "price_band",
            "000001:sz",
            20.0,
            "band",
        ),
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    ev = conn.execute("SELECT * FROM alert_events WHERE id = 1").fetchone()
    _r1, _r3, _r5, hit = evaluate_row(
        conn,
        ev,
        {
            "bearish_hit_threshold_pct_1d": -2.0,
            "bearish_hit_threshold_pct_3d": -2.5,
            "bearish_hit_threshold_pct_5d": -3.0,
        },
    )
    conn.close()
    assert hit is None


def test_strategy_buy_hit_uses_r5(tmp_path) -> None:
    db = tmp_path / "st.db"
    conn = open_store_connection(db)
    init_schema(conn)
    secid = secid_for("600000", "sh")
    for td, c in [
        ("2025-06-02", 10.0),
        ("2025-06-03", 10.0),
        ("2025-06-04", 10.1),
        ("2025-06-05", 10.2),
        ("2025-06-06", 10.3),
        ("2025-06-09", 10.5),
        ("2025-06-10", 10.6),
    ]:
        conn.execute(
            """
            INSERT INTO daily_klines (
                secid, trade_date, open, high, low, close, volume
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (secid, td, c, c, c, c, 1.0),
        )
    conn.execute(
        """
        INSERT INTO alert_events (
            fired_iso, anchor_trade_date, code, market, secid,
            alert_type, rk, anchor_price, summary, eval_status
        ) VALUES (?,?,?,?,?,?,?,?,?,'pending')
        """,
        (
            "2025-06-03T10:00:00",
            "2025-06-02",
            "600000",
            "sh",
            secid,
            "strategy",
            "600000:sh",
            10.0,
            "【买入信号】箱体下沿",
        ),
    )
    conn.commit()
    conn.row_factory = sqlite3.Row
    ev = conn.execute("SELECT * FROM alert_events WHERE id = 1").fetchone()
    th = {
        "bearish_hit_threshold_pct_1d": -2.0,
        "bearish_hit_threshold_pct_3d": -2.5,
        "bearish_hit_threshold_pct_5d": -3.0,
        "strategy_hit_eval": {},
        "risk_stop_take_eval": {},
    }
    _r1, _r3, r5, hit = evaluate_row(conn, ev, th)
    conn.close()
    assert r5 is not None and r5 > 0
    assert hit == 1


def test_take_profit_correctness_both_negative() -> None:
    h = compute_risk_stop_hit(
        {"risk_kind": "take_profit_short"},
        -0.01,
        None,
        -0.02,
        th1=-2.0,
        th3=-2.5,
        th5=-3.0,
        take_profit_eval={"take_profit_hit_for_correctness": 1.0},
    )
    assert h == 1


def test_take_profit_correctness_both_positive_is_miss() -> None:
    h = compute_risk_stop_hit(
        {"risk_kind": "take_profit_short"},
        0.001,
        None,
        0.02,
        th1=-2.0,
        th3=-2.5,
        th5=-3.0,
        take_profit_eval={},
    )
    assert h == 0


def test_take_profit_correctness_only_r1_negative() -> None:
    h = compute_risk_stop_hit(
        {"risk_kind": "take_profit_wave"},
        -0.005,
        None,
        None,
        th1=-2.0,
        th3=-2.5,
        th5=-3.0,
        take_profit_eval={},
    )
    assert h == 1


def test_take_profit_legacy_sell_flew_semantics() -> None:
    h = compute_risk_stop_hit(
        {"risk_kind": "take_profit_short"},
        0.001,
        None,
        0.02,
        th1=-2.0,
        th3=-2.5,
        th5=-3.0,
        take_profit_eval={
            "take_profit_hit_for_correctness": 0.0,
            "take_profit_hit_r1_above_pct": 0.5,
        },
    )
    assert h == 1


def test_risk_stop_loss_still_bearish() -> None:
    h = compute_risk_stop_hit(
        {"risk_kind": "stop_loss"},
        -0.03,
        -0.04,
        -0.05,
        th1=-2.0,
        th3=-2.5,
        th5=-3.0,
        take_profit_eval={},
    )
    assert h == 1


def test_compute_strategy_sell_hit_negative_r5() -> None:
    assert (
        compute_strategy_hit(
            "【卖出信号】箱体上沿",
            None,
            None,
            -0.01,
            {},
        )
        == 1
    )
    assert (
        compute_strategy_hit(
            "【卖出信号】箱体上沿",
            None,
            None,
            0.01,
            {},
        )
        == 0
    )
