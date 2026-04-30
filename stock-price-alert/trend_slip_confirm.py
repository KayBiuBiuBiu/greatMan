"""趋势下滑：连续 N 个交易日触发（SQLite streak，与 kline_store 同库）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from kline_store import db_lock, init_schema, open_store_connection


def resolve_kline_db_path(cfg: dict[str, Any], root: Path) -> Path | None:
    ks = cfg.get("kline_store") or {}
    if not isinstance(ks, dict) or not bool(ks.get("enabled")):
        return None
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def _prev_trade_date(conn: sqlite3.Connection, secid: str, anchor_td: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(trade_date) FROM daily_klines WHERE secid = ? AND trade_date < ?",
        (secid, anchor_td[:10]),
    ).fetchone()
    if not row or row[0] is None:
        return None
    s = str(row[0]).strip()
    return s[:10] if len(s) >= 10 else s


def clear_trend_slip_streak(cfg: dict[str, Any], *, root: Path, rk: str) -> None:
    """当日未触发趋势柱走弱时清理 streak（仅 require_consecutive_trade_days>1 时调用）。"""
    dbp = resolve_kline_db_path(cfg, root)
    if dbp is None:
        return
    with db_lock():
        conn = open_store_connection(dbp)
        try:
            init_schema(conn)
            conn.execute("DELETE FROM trend_slip_streak WHERE rk = ?", (rk,))
            conn.commit()
        finally:
            conn.close()


def consecutive_trend_slip_notify_ok(
    cfg: dict[str, Any],
    *,
    root: Path,
    rk: str,
    secid: str,
    anchor_td: str,
    raw_fire: bool,
) -> tuple[bool, int, str]:
    """
    返回 (是否允许按原逻辑推送/记日志, 当前 streak, 说明)。
    require_consecutive_trade_days<=1 时与 raw_fire 一致。
    """
    tc = cfg.get("trend_slippage_alert") or {}
    n_need = max(1, int(tc.get("require_consecutive_trade_days", 1) or 1))
    if n_need <= 1:
        return bool(raw_fire), 1 if raw_fire else 0, ""

    dbp = resolve_kline_db_path(cfg, root)
    if dbp is None:
        return bool(raw_fire), 1 if raw_fire else 0, ""

    anchor = (anchor_td or "")[:10]
    if len(anchor) != 10:
        anchor = datetime.now().strftime("%Y-%m-%d")

    if not raw_fire:
        clear_trend_slip_streak(cfg, root=root, rk=rk)
        return False, 0, ""

    now_iso = datetime.now().isoformat(timespec="seconds")
    with db_lock():
        conn = open_store_connection(dbp)
        try:
            init_schema(conn)
            prev_td = _prev_trade_date(conn, secid, anchor)
            row = conn.execute(
                "SELECT last_weak_anchor, streak FROM trend_slip_streak WHERE rk = ?",
                (rk,),
            ).fetchone()
            if row is None:
                streak = 1
            else:
                last_w = str(row[0] or "")[:10]
                old_s = max(0, int(row[1] or 0))
                if last_w == anchor:
                    streak = max(1, old_s)
                elif prev_td and last_w == prev_td:
                    streak = old_s + 1
                else:
                    streak = 1
            conn.execute(
                """
                INSERT INTO trend_slip_streak(rk, secid, last_weak_anchor, streak, updated_iso)
                VALUES(?,?,?,?,?)
                ON CONFLICT(rk) DO UPDATE SET
                    secid=excluded.secid,
                    last_weak_anchor=excluded.last_weak_anchor,
                    streak=excluded.streak,
                    updated_iso=excluded.updated_iso
                """,
                (rk, secid, anchor, streak, now_iso),
            )
            conn.commit()
        finally:
            conn.close()

    ok = streak >= n_need
    note = f"连续弱势第{streak}个交易日（需≥{n_need}才推送）"
    return ok, streak, note
