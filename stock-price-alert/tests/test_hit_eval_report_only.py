"""evaluate_hit_report_only：不写库重算 hit 汇总。"""

from __future__ import annotations

import json
import sqlite3

from backtest_alerts import evaluate_hit_report_only, hit_thresholds_from_cfg
from kline_store import init_schema, open_store_connection
from quote_eastmoney import secid_for
from run_alert import merge_full_config


def test_hit_report_only_matches_strategy_buy(tmp_path) -> None:
    db = tmp_path / "kl.db"
    conn = open_store_connection(db)
    init_schema(conn)
    secid = secid_for("600000", "sh")
    # 锚点后有 3 个交易日，无 T+5 → 买入命中只看 r1
    for td, c in [
        ("2025-06-04", 10.0),
        ("2025-06-05", 10.3),
        ("2025-06-06", 10.4),
        ("2025-06-09", 10.5),
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
        ) VALUES (?,?,?,?,?,?,?,?,?,'done')
        """,
        (
            "2025-06-05T10:00:00",
            "2025-06-04",
            "600000",
            "sh",
            secid,
            "strategy",
            "600000:sh",
            10.0,
            "【买入信号】仅T+1",
        ),
    )
    conn.commit()
    conn.close()

    raw = {
        "watchlist": [],
        "alert_log": {
            "enabled": True,
            "share_kline_db": True,
            "db_path": str(db),
            "strategy_hit_eval": {
                "buy_hit_r5_above_pct": 0.0,
                "buy_hit_r1_above_pct": 0.0,
            },
        },
        "kline_store": {"enabled": True, "db_path": str(db)},
    }
    cfg = merge_full_config(raw)
    rep = evaluate_hit_report_only(cfg, root=tmp_path, since="2025-01-01")
    st = rep["by_alert_type"]["strategy"]
    assert st["n"] == 1
    assert st["n_hit_scored"] == 1
    assert st["hit_rate"] == 1.0

    raw2 = json.loads(json.dumps(raw))
    raw2["alert_log"]["strategy_hit_eval"]["buy_hit_r1_above_pct"] = 5.0
    cfg2 = merge_full_config(raw2)
    rep2 = evaluate_hit_report_only(cfg2, root=tmp_path, since="2025-01-01")
    assert rep2["by_alert_type"]["strategy"]["hit_rate"] == 0.0


def test_hit_thresholds_from_cfg_defaults() -> None:
    t = hit_thresholds_from_cfg(merge_full_config({"watchlist": [], "alert_log": {}}))
    assert "strategy_hit_eval" in t
    assert "bearish_hit_threshold_pct_1d" in t
