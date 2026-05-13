"""每日账户盈亏块：持仓市值、当日价格盈亏、台账已实现；供 daily_summary 嵌入。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backtest_picks_performance import code_to_secid, resolve_db_path
from position_ledger import (
    ledger_db_path,
    list_events_for_day,
    sum_realized_close_reduce_pnl_for_day,
)


def nominal_last_two_closes(
    conn: sqlite3.Connection | None,
    secid: str,
    day_iso: str,
) -> tuple[float | None, float | None, str]:
    """持仓口径：优先 Tushare daily（不复权）；否则本地 daily_klines（前复权）。

    返回 (last_close, prev_close, basis)，basis 为 raw | qfq_db | none。
    """
    from quote_tushare import last_two_unadj_closes_on_or_before

    lu, pu = last_two_unadj_closes_on_or_before(secid, day_iso)
    if lu is not None and lu > 0:
        return lu, pu, "raw"
    if conn is not None:
        lq, pq = _last_two_closes_on_or_before(conn, secid, day_iso)
        if lq is not None and lq > 0:
            return lq, pq, "qfq_db"
    return None, None, "none"


def _last_two_closes_on_or_before(
    conn: sqlite3.Connection, secid: str, day_iso: str
) -> tuple[float | None, float | None]:
    """返回 (最近收盘, 上一根收盘)，均 ≤ day_iso。"""
    rows = conn.execute(
        """
        SELECT close FROM daily_klines
        WHERE secid = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT 2
        """,
        (str(secid).strip(), str(day_iso).strip()[:10]),
    ).fetchall()
    if not rows:
        return None, None
    try:
        c0 = float(rows[0][0]) if rows[0][0] is not None else None
    except (TypeError, ValueError):
        c0 = None
    if len(rows) < 2:
        return (c0 if c0 and c0 > 0 else None), None
    try:
        c1 = float(rows[1][0]) if rows[1][0] is not None else None
    except (TypeError, ValueError):
        c1 = None
    if c0 is not None and c0 <= 0:
        c0 = None
    if c1 is not None and c1 <= 0:
        c1 = None
    return c0, c1


def build_account_pnl_summary(
    cfg: dict[str, Any],
    root: Path,
    config_path: Path,
    day_iso: str,
    holdings: list[dict[str, Any]],
) -> dict[str, Any]:
    """汇总账户层盈亏：收/当日/浮盈优先 Tushare daily（不复权），否则本地日K（前复权）；今日已实现仅减仓/清仓。"""
    db_path = resolve_db_path(cfg)
    ledger_p = ledger_db_path(config_path.parent)
    realized_today = sum_realized_close_reduce_pnl_for_day(ledger_p, day_iso)
    ledger_preview = list_events_for_day(ledger_p, day_iso, limit=80)

    positions: list[dict[str, Any]] = []
    unrealized_total = 0.0
    daily_float_change = 0.0
    notes: list[str] = []
    any_qfq_basis = False

    conn: sqlite3.Connection | None = None
    if db_path.is_file():
        try:
            conn = sqlite3.connect(str(db_path), timeout=10.0)
        except OSError:
            notes.append("kline_db_open_failed")
    else:
        notes.append("no_kline_db_for_account_pnl")

    try:
        for h in holdings:
            if not isinstance(h, dict):
                continue
            code = str(h.get("code") or "").strip().zfill(6)
            hs = int(h.get("hold_shares") or 0)
            if not code.isdigit() or len(code) != 6 or hs <= 0:
                continue
            cost = h.get("cost_price")
            try:
                cost_f = float(cost) if cost is not None else 0.0
            except (TypeError, ValueError):
                cost_f = 0.0
            if cost_f <= 0:
                continue
            try:
                sid = code_to_secid(code)
            except Exception:
                continue
            last_c, prev_c, basis = nominal_last_two_closes(conn, sid, day_iso)
            if basis == "qfq_db":
                any_qfq_basis = True
            if last_c is None or last_c <= 0:
                positions.append(
                    {
                        "code": code,
                        "name": str(h.get("name") or ""),
                        "hold_shares": hs,
                        "avg_cost": round(cost_f, 4),
                        "last_close": None,
                        "last_close_basis": basis,
                        "daily_pnl_est": None,
                        "float_pnl_est": None,
                    }
                )
                continue
            fl = (last_c - cost_f) * float(hs)
            unrealized_total += fl
            day_chg = None
            if prev_c is not None and prev_c > 0:
                day_chg = (last_c - prev_c) * float(hs)
                daily_float_change += day_chg
            positions.append(
                {
                    "code": code,
                    "name": str(h.get("name") or ""),
                    "hold_shares": hs,
                    "avg_cost": round(cost_f, 4),
                    "last_close": round(last_c, 4),
                    "last_close_basis": basis,
                    "daily_pnl_est": None if day_chg is None else round(day_chg, 2),
                    "float_pnl_est": round(fl, 2),
                }
            )
    finally:
        if conn is not None:
            conn.close()

    if any_qfq_basis:
        notes.append(
            "收/当日/浮盈：部分标的用本地日K库前复权收盘（列尾标*），与券商现价可能不一致；"
            "配置 Tushare 后优先拉取不复权 daily。"
        )
    acct_change = realized_today + daily_float_change
    return {
        "as_of": day_iso,
        "positions": positions,
        "realized_today": round(realized_today, 2),
        "daily_float_change_est": round(daily_float_change, 2),
        "unrealized_total_est": round(unrealized_total, 2),
        "account_today_change_est": round(acct_change, 2),
        "ledger_events": ledger_preview,
        "notes": notes,
    }
