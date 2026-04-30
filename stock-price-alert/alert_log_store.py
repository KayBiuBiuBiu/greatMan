"""预警事件落库 + 供 backtest_alerts 计算远期收益与命中标记。"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from kline_store import db_lock, init_schema, open_store_connection
from quote_eastmoney import secid_for

_LOG = logging.getLogger(__name__)

BEARISH_ALERT_TYPES = frozenset({"trend_slip", "drawdown"})


def resolve_alert_db_path(cfg: dict[str, Any], root: Path) -> Path | None:
    al = cfg.get("alert_log") or {}
    if not bool(al.get("enabled")):
        return None
    share = bool(al.get("share_kline_db", True))
    ks = cfg.get("kline_store") or {}
    if share:
        rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
        p = Path(rel)
        if not p.is_absolute():
            p = root / p
        return p.resolve()
    rel2 = str(al.get("db_path") or "data/alert_events.db").strip()
    p2 = Path(rel2)
    if not p2.is_absolute():
        p2 = root / p2
    return p2.resolve()


def _anchor_from_pack(pack: dict[str, Any]) -> tuple[str, str, str, float]:
    rule = pack.get("rule") or {}
    q = pack.get("q") or {}
    code = str(q.get("code") or rule.get("code") or "").strip()
    market = str(rule.get("market") or "sh").strip().lower()
    kl = pack.get("kline") or {}
    kld = str(kl.get("kline_last_trade_date") or "").strip()[:10]
    anchor_d = kld if len(kld) == 10 else datetime.now().strftime("%Y-%m-%d")
    price = float(q.get("price") or 0.0)
    return code, market, anchor_d, price


def log_watch_alert(
    cfg: dict[str, Any],
    *,
    root: Path,
    pack: dict[str, Any],
    alert_type: str,
    rk: str,
    summary: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if not bool((cfg.get("alert_log") or {}).get("enabled")):
        return
    code, market, anchor_td, anchor_px = _anchor_from_pack(pack)
    if not code or anchor_px <= 0:
        return
    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None:
        return
    secid = secid_for(code, market)
    fired_iso = datetime.now().isoformat(timespec="seconds")
    extra_json = json.dumps(extra, ensure_ascii=False) if extra else None
    summary_s = (summary or "").strip() or alert_type
    with db_lock():
        conn = open_store_connection(db_path)
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
                    fired_iso,
                    anchor_td,
                    code,
                    market,
                    secid,
                    alert_type,
                    rk,
                    float(anchor_px),
                    summary_s,
                    extra_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _anchor_close_or_price(
    conn: sqlite3.Connection,
    secid: str,
    anchor_trade_date: str,
    anchor_price: float,
) -> tuple[float, str]:
    row = conn.execute(
        "SELECT close FROM daily_klines WHERE secid = ? AND trade_date = ?",
        (secid, anchor_trade_date[:10]),
    ).fetchone()
    if row and row[0] is not None:
        c = float(row[0])
        if c > 0:
            return c, "db_close"
    if anchor_price > 0:
        return float(anchor_price), "intraday_price"
    return 0.0, "none"


def forward_returns_vs_anchor(
    conn: sqlite3.Connection,
    secid: str,
    anchor_trade_date: str,
    anchor_price: float,
) -> tuple[float | None, float | None, float | None]:
    """相对锚定价的 T+1 / T+3 / T+5 收盘收益率（按交易日计）。"""
    c0, _src = _anchor_close_or_price(conn, secid, anchor_trade_date, anchor_price)
    if c0 <= 0:
        return None, None, None
    rows = conn.execute(
        """
        SELECT close FROM daily_klines
        WHERE secid = ? AND trade_date > ?
        ORDER BY trade_date ASC
        LIMIT 5
        """,
        (secid, anchor_trade_date[:10]),
    ).fetchall()
    closes = [float(r[0]) for r in rows if r[0] is not None and float(r[0]) > 0]
    r1 = (closes[0] - c0) / c0 if len(closes) >= 1 else None
    r3 = (closes[2] - c0) / c0 if len(closes) >= 3 else None
    r5 = (closes[4] - c0) / c0 if len(closes) >= 5 else None
    return r1, r3, r5


def _pct_threshold_to_frac(pct: float) -> float:
    return float(pct) / 100.0


def compute_bearish_hit(
    alert_type: str,
    extra: dict[str, Any] | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    *,
    th1: float,
    th3: float,
    th5: float,
) -> int | None:
    if alert_type not in BEARISH_ALERT_TYPES:
        return None
    t1 = _pct_threshold_to_frac(th1)
    t3 = _pct_threshold_to_frac(th3)
    t5 = _pct_threshold_to_frac(th5)
    if r1 is not None and r1 <= t1:
        return 1
    if r3 is not None and r3 <= t3:
        return 1
    if r5 is not None and r5 <= t5:
        return 1
    if r1 is None and r3 is None and r5 is None:
        return None
    return 0


def compute_risk_stop_hit(
    extra: dict[str, Any] | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    *,
    th1: float,
    th3: float,
    th5: float,
) -> int | None:
    """止损：与 bearish 相同；止盈类暂不写 hit。"""
    kind = (extra or {}).get("risk_kind")
    if kind != "stop_loss":
        return None
    return compute_bearish_hit(
        "drawdown",
        None,
        r1,
        r3,
        r5,
        th1=th1,
        th3=th3,
        th5=th5,
    )


def row_hit_for_eval(
    alert_type: str,
    extra_json: str | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    thresholds: dict[str, float],
) -> int | None:
    extra: dict[str, Any] | None = None
    if extra_json:
        try:
            extra = json.loads(extra_json)
        except json.JSONDecodeError:
            extra = None
    th1 = float(thresholds.get("bearish_hit_threshold_pct_1d", -2.0))
    th3 = float(thresholds.get("bearish_hit_threshold_pct_3d", -2.5))
    th5 = float(thresholds.get("bearish_hit_threshold_pct_5d", -3.0))
    if alert_type == "risk_stop_take":
        return compute_risk_stop_hit(extra, r1, r3, r5, th1=th1, th3=th3, th5=th5)
    return compute_bearish_hit(
        alert_type, extra, r1, r3, r5, th1=th1, th3=th3, th5=th5
    )


def evaluate_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    thresholds: dict[str, float],
) -> tuple[float | None, float | None, float | None, int | None]:
    secid = str(row["secid"])
    anchor_td = str(row["anchor_trade_date"])
    anchor_px = float(row["anchor_price"])
    r1, r3, r5 = forward_returns_vs_anchor(conn, secid, anchor_td, anchor_px)
    ex = row["extra_json"] if row["extra_json"] is not None else None
    hit = row_hit_for_eval(str(row["alert_type"]), ex, r1, r3, r5, thresholds=thresholds)
    return r1, r3, r5, hit
