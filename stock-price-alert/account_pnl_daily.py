"""每日账户盈亏块：持仓市值、当日价格盈亏、台账已实现；供 daily_summary 嵌入。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backtest_picks_performance import code_to_secid, resolve_db_path
from position_ledger import ledger_db_path, list_events_for_day, sum_realized_pnl_for_day


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
    """汇总账户层盈亏（依赖日 K；无 K 的标的跳过当日与浮动估算）。"""
    db_path = resolve_db_path(cfg)
    ledger_p = ledger_db_path(config_path.parent)
    realized_today = sum_realized_pnl_for_day(ledger_p, day_iso)
    ledger_preview = list_events_for_day(ledger_p, day_iso, limit=80)

    positions: list[dict[str, Any]] = []
    unrealized_total = 0.0
    daily_float_change = 0.0

    if not db_path.is_file():
        return {
            "as_of": day_iso,
            "positions": [],
            "realized_today": round(realized_today, 2),
            "daily_float_change_est": None,
            "unrealized_total_est": None,
            "account_today_change_est": round(realized_today, 2),
            "ledger_events": ledger_preview,
            "notes": ["no_kline_db_for_account_pnl"],
        }

    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
    except OSError:
        return {
            "as_of": day_iso,
            "positions": [],
            "realized_today": round(realized_today, 2),
            "ledger_events": ledger_preview,
            "notes": ["kline_db_open_failed"],
        }
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
            last_c, prev_c = _last_two_closes_on_or_before(conn, sid, day_iso)
            if last_c is None or last_c <= 0:
                positions.append(
                    {
                        "code": code,
                        "name": str(h.get("name") or ""),
                        "hold_shares": hs,
                        "avg_cost": round(cost_f, 4),
                        "last_close": None,
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
                    "daily_pnl_est": None if day_chg is None else round(day_chg, 2),
                    "float_pnl_est": round(fl, 2),
                }
            )
    finally:
        conn.close()

    acct_change = realized_today + daily_float_change
    return {
        "as_of": day_iso,
        "positions": positions,
        "realized_today": round(realized_today, 2),
        "daily_float_change_est": round(daily_float_change, 2),
        "unrealized_total_est": round(unrealized_total, 2),
        "account_today_change_est": round(acct_change, 2),
        "ledger_events": ledger_preview,
        "notes": [],
    }
