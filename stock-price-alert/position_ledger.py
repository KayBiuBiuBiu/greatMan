"""持仓加减流水与已实现盈亏台账（SQLite，与 config 同级 data/position_ledger.db）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def ledger_db_path(config_parent: Path) -> Path:
    d = config_parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "position_ledger.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=12.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ledger_columns(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("PRAGMA table_info(ledger_events)")
    return {str(r[1]) for r in cur.fetchall()}


def init_ledger_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          day_iso TEXT NOT NULL,
          kind TEXT NOT NULL,
          code TEXT NOT NULL,
          name TEXT,
          shares_before INTEGER,
          shares_after INTEGER,
          avg_cost_before REAL,
          avg_cost_after REAL,
          qty_traded INTEGER NOT NULL DEFAULT 0,
          exec_price REAL,
          realized_pnl REAL NOT NULL DEFAULT 0,
          note TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_day ON ledger_events(day_iso);
        CREATE INDEX IF NOT EXISTS idx_ledger_code ON ledger_events(code);
        """
    )
    cols = _ledger_columns(conn)
    if "op_type" not in cols:
        conn.execute("ALTER TABLE ledger_events ADD COLUMN op_type TEXT")
        conn.commit()


def append_ledger_event(
    db_path: Path,
    *,
    kind: str,
    code: str,
    name: str = "",
    shares_before: int | None = None,
    shares_after: int | None = None,
    avg_cost_before: float | None = None,
    avg_cost_after: float | None = None,
    qty_traded: int = 0,
    exec_price: float | None = None,
    realized_pnl: float = 0.0,
    note: str = "",
    ts: str | None = None,
    day_iso: str | None = None,
    op_type: str | None = None,
) -> None:
    now = datetime.now()
    ts_s = (ts or now.strftime("%Y-%m-%d %H:%M:%S")).strip()
    d_iso = (day_iso or ts_s[:10]).strip()[:10]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ot = (op_type or kind or "").strip() or str(kind or "").strip()
    try:
        conn = _connect(db_path)
        try:
            init_ledger_schema(conn)
            cols = _ledger_columns(conn)
            if "op_type" in cols:
                conn.execute(
                    """
                    INSERT INTO ledger_events (
                      ts, day_iso, kind, op_type, code, name,
                      shares_before, shares_after,
                      avg_cost_before, avg_cost_after,
                      qty_traded, exec_price, realized_pnl, note
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        ts_s,
                        d_iso,
                        str(kind or "").strip(),
                        ot,
                        str(code or "").strip().zfill(6)
                        if str(code or "").strip().isdigit()
                        else str(code or "").strip(),
                        str(name or "")[:40],
                        shares_before,
                        shares_after,
                        avg_cost_before,
                        avg_cost_after,
                        int(qty_traded),
                        exec_price,
                        float(realized_pnl),
                        str(note or "")[:500],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ledger_events (
                      ts, day_iso, kind, code, name,
                      shares_before, shares_after,
                      avg_cost_before, avg_cost_after,
                      qty_traded, exec_price, realized_pnl, note
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        ts_s,
                        d_iso,
                        str(kind or "").strip(),
                        str(code or "").strip().zfill(6)
                        if str(code or "").strip().isdigit()
                        else str(code or "").strip(),
                        str(name or "")[:40],
                        shares_before,
                        shares_after,
                        avg_cost_before,
                        avg_cost_after,
                        int(qty_traded),
                        exec_price,
                        float(realized_pnl),
                        str(note or "")[:500],
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def sum_realized_pnl_for_day(db_path: Path, day_iso: str) -> float:
    """当日台账 realized_pnl 全量求和（含所有 kind；加仓类一般为 0）。"""
    if not db_path.is_file():
        return 0.0
    d0 = str(day_iso).strip()[:10]
    try:
        conn = _connect(db_path)
        try:
            init_ledger_schema(conn)
            row = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl),0) AS s FROM ledger_events WHERE day_iso = ?",
                (d0,),
            ).fetchone()
            return float(row["s"] or 0.0) if row else 0.0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0.0


def sum_realized_close_reduce_pnl_for_day(db_path: Path, day_iso: str) -> float:
    """当日减仓、清仓等卖出侧已实现盈亏（仅 reduce / close / unhold_settle 等 kind）。

    不含 hold_add、buy、add 等开仓流水；与「只要今天清仓减仓盈亏」口径一致。
    """
    if not db_path.is_file():
        return 0.0
    d0 = str(day_iso).strip()[:10]
    kinds = ("reduce", "close", "unhold_settle", "sell_clear", "sell_partial")
    ph = ",".join("?" * len(kinds))
    try:
        conn = _connect(db_path)
        try:
            init_ledger_schema(conn)
            row = conn.execute(
                f"""
                SELECT COALESCE(SUM(realized_pnl),0) AS s
                FROM ledger_events
                WHERE day_iso = ?
                  AND lower(trim(kind)) IN ({ph})
                """,
                (d0, *kinds),
            ).fetchone()
            return float(row["s"] or 0.0) if row else 0.0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0.0


def list_events_for_day(db_path: Path, day_iso: str, *, limit: int = 200) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    d0 = str(day_iso).strip()[:10]
    try:
        conn = _connect(db_path)
        try:
            init_ledger_schema(conn)
            cur = conn.execute(
                """
                SELECT * FROM ledger_events
                WHERE day_iso = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (d0, int(limit)),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []
