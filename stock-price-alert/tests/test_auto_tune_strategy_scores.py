"""auto_tune_strategy_scores / signal_operation_feedback 单元测试。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from kline_store import init_schema, open_store_connection
from position_ledger import _connect, init_ledger_schema
from signal_operation_feedback import (
    compute_buy_adopted_return_pct,
    feedback_enabled,
    find_latest_open_signal,
    init_signal_log_schema,
    insert_signal_row,
    run_min_score_tune_from_feedback,
)


def _seed_klines(db_path: Path, secid: str, dates: list[str], closes: list[float]) -> None:
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        for d, c in zip(dates, closes, strict=True):
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_klines
                (secid, trade_date, open, high, low, close, volume)
                VALUES (?,?,?,?,?,?,?)
                """,
                (secid, d, c, c, c, c, 1e6),
            )
        conn.commit()
    finally:
        conn.close()


def test_insert_and_match_buy_signal(tmp_path: Path) -> None:
    db = tmp_path / "data" / "position_ledger.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db)
    try:
        init_ledger_schema(conn)
        init_signal_log_schema(conn)
        conn.commit()
    finally:
        conn.close()

    root = tmp_path
    sid = insert_signal_row(
        root,
        code="600000",
        signal_type="buy",
        strategy_name="ma_dip",
        score=77.0,
        ts=datetime(2026, 6, 1, 10, 0, 0),
    )
    assert sid is not None
    cfg = {
        "ops_automation": {
            "self_improve_operation_feedback": {
                "enabled": True,
                "match_window_minutes": 30,
            }
        }
    }
    m = find_latest_open_signal(
        root,
        code="600000",
        signal_type="buy",
        now=datetime(2026, 6, 1, 10, 5, 0),
        cfg=cfg,
    )
    assert m == sid


def test_compute_buy_adopted_return_pct(tmp_path: Path) -> None:
    root = tmp_path
    kdb = tmp_path / "data" / "daily_klines.db"
    kdb.parent.mkdir(parents=True, exist_ok=True)
    dates = [f"2026-06-{i:02d}" for i in range(1, 12)]
    closes = [10.0 + i * 0.1 for i in range(11)]
    _seed_klines(kdb, "1.600000", dates, closes)
    cfg = {
        "kline_store": {"enabled": True, "db_path": "data/daily_klines.db"},
        "ops_automation": {"self_improve_operation_feedback": {"enabled": True}},
    }
    pct = compute_buy_adopted_return_pct(
        cfg,
        root,
        code="600000",
        adopt_ts="2026-06-01 10:00:00",
        adopt_price=10.0,
        horizon_days=5,
    )
    assert pct is not None
    p, end_d, end_c = pct
    assert end_d == "2026-06-06"
    assert p > 0


def test_run_min_score_tune_lowers_threshold(tmp_path: Path) -> None:
    root = tmp_path
    db = tmp_path / "data" / "position_ledger.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db)
    try:
        init_ledger_schema(conn)
        init_signal_log_schema(conn)
        for _ in range(6):
            conn.execute(
                """
                INSERT INTO strategy_signal_log (
                  code, signal_type, strategy_name, score, timestamp,
                  expired, adopted, adopted_timestamp, adopted_price, adopted_shares,
                  eval_return_pct, eval_price_end, eval_date_end
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "600000",
                    "buy",
                    "ma_dip",
                    70.0,
                    "2026-06-01 10:00:00",
                    0,
                    1,
                    "2026-06-01 10:01:00",
                    10.0,
                    100,
                    3.0,
                    10.5,
                    "2026-06-10",
                ),
            )
        conn.commit()
    finally:
        conn.close()

    kdb = tmp_path / "data" / "daily_klines.db"
    _seed_klines(kdb, "1.600000", ["2026-06-01"], [10.0])

    cfg_path = tmp_path / "config.json"
    cfg = {
        "kline_store": {"enabled": True, "db_path": "data/daily_klines.db"},
        "strategy_signal": {"min_score_by_strategy": {"ma_dip": 60.0}},
        "ops_automation": {
            "self_improve_operation_feedback": {
                "enabled": True,
                "evaluate_days": 30,
                "improve_threshold_pct": 2.0,
                "degrade_threshold_pct": -1.0,
                "min_samples": 5,
                "adjust_step": 2,
                "max_change": 10,
            }
        },
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg_loaded = json.loads(cfg_path.read_text(encoding="utf-8"))

    res = run_min_score_tune_from_feedback(
        cfg_loaded,
        config_path=cfg_path,
        root=root,
        now=datetime(2026, 6, 15, 16, 0, 0),
    )
    assert res.get("changed") is True
    out = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert float(out["strategy_signal"]["min_score_by_strategy"]["ma_dip"]) == pytest.approx(
        58.0
    )


def test_feedback_enabled_false_by_default() -> None:
    assert feedback_enabled({}) is False
    assert feedback_enabled({"ops_automation": {}}) is False
