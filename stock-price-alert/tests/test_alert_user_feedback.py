from __future__ import annotations

from pathlib import Path

from alert_log_store import (
    apply_feedback_to_latest_alert,
    distinct_fp_codes_since,
    resolve_alert_db_path,
)
from auto_tune_accuracy import merge_fp_user_feedback_into_ignore
from email_command_bot import _parse_feedback_commands
from kline_store import init_schema, open_store_connection


def test_parse_feedback_commands_fp_tp() -> None:
    rows = _parse_feedback_commands("Re: 预警", "fp 600711\ntp 000001")
    assert ("fp", "600711") in rows
    assert ("tp", "000001") in rows
    rows2 = _parse_feedback_commands("", "误报：688001")
    assert ("fp", "688001") in rows2


def test_apply_feedback_updates_row(tmp_path: Path) -> None:
    db = tmp_path / "mix.db"
    cfg = {
        "alert_log": {"enabled": True, "share_kline_db": True},
        "kline_store": {"enabled": True, "db_path": str(db)},
    }
    root = tmp_path
    p = resolve_alert_db_path(cfg, root)
    assert p == db.resolve()
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO alert_events (
                fired_iso, anchor_trade_date, code, market, secid,
                alert_type, rk, anchor_price, summary, extra_json,
                eval_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,'pending')
            """,
            (
                "2026-05-01T10:00:00",
                "2026-04-30",
                "600711",
                "sh",
                "1.600711",
                "trend_slip",
                "rk1",
                10.0,
                "test",
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert (
        apply_feedback_to_latest_alert(cfg, root, code="600711", feedback="fp") == 1
    )
    conn2 = open_store_connection(db)
    try:
        r = conn2.execute(
            "SELECT user_feedback FROM alert_events WHERE code='600711'"
        ).fetchone()
        assert r and r[0] == "fp"
    finally:
        conn2.close()


def test_distinct_fp_codes_since(tmp_path: Path) -> None:
    db = tmp_path / "m2.db"
    cfg = {
        "alert_log": {"enabled": True, "share_kline_db": True},
        "kline_store": {"enabled": True, "db_path": str(db)},
    }
    root = tmp_path
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        for code, ad in [("600000", "2026-04-15"), ("600000", "2026-05-01")]:
            conn.execute(
                """
                INSERT INTO alert_events (
                    fired_iso, anchor_trade_date, code, market, secid,
                    alert_type, rk, anchor_price, summary, extra_json,
                    eval_status, user_feedback
                ) VALUES (?,?,?,?,?,?,?,?,?,?,'pending','fp')
                """,
                (
                    "2026-05-01T10:00:00",
                    ad,
                    code,
                    "sh",
                    f"1.{code}",
                    "drawdown",
                    "rk",
                    9.0,
                    "x",
                    None,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    codes = distinct_fp_codes_since(cfg, root, anchor_since="2026-04-20")
    assert codes == ["600000"]


def test_merge_fp_into_config_ignore(tmp_path: Path) -> None:
    db = tmp_path / "m3.db"
    cfg = {
        "alert_log": {"enabled": True, "share_kline_db": True},
        "kline_store": {"enabled": True, "db_path": str(db)},
        "trend_slippage_alert": {"alert_ignore_codes": ["111111"]},
        "drawdown_alert": {"alert_ignore_codes": []},
    }
    root = tmp_path
    conn = open_store_connection(db)
    try:
        init_schema(conn)
        conn.execute(
            """
            INSERT INTO alert_events (
                fired_iso, anchor_trade_date, code, market, secid,
                alert_type, rk, anchor_price, summary, extra_json,
                eval_status, user_feedback
            ) VALUES (?,?,?,?,?,?,?,?,?,?,'pending','fp')
            """,
            (
                "2026-05-02T10:00:00",
                "2026-05-01",
                "600711",
                "sh",
                "1.600711",
                "trend_slip",
                "rk",
                8.0,
                "x",
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    ch = merge_fp_user_feedback_into_ignore(cfg, 30, root=tmp_path)
    assert ch
    assert "600711" in cfg["trend_slippage_alert"]["alert_ignore_codes"]
    assert "600711" in cfg["drawdown_alert"]["alert_ignore_codes"]
    assert "111111" in cfg["trend_slippage_alert"]["alert_ignore_codes"]
