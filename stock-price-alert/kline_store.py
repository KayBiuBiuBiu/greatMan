"""本地 SQLite 日 K 持久化（阶段三）：盘后同步 + 监控端优先读库减少东财请求。"""

from __future__ import annotations

import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Any, Iterable

_DB_LOCK = threading.Lock()


def db_lock() -> threading.Lock:
    """与日 K / 预警事件共用同一 SQLite 文件时的写锁。"""
    return _DB_LOCK


def _apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """降低写锁竞争：WAL + NORMAL（日 K 同步场景可接受）。"""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=8000")
    except sqlite3.Error:
        pass


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_connection_pragmas(conn)
    return conn


def open_store_connection(db_path: Path) -> sqlite3.Connection:
    """打开日 K 库（含 WAL 等 pragma），供同步脚本与工具复用。"""
    return _connect(db_path)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_klines (
            secid TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (secid, trade_date)
        );
        CREATE INDEX IF NOT EXISTS idx_kl_secid_d ON daily_klines(secid, trade_date);
        CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS indicator_last (
            secid TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            ma5 REAL, ma20 REAL, ma60 REAL,
            high20 REAL, low20 REAL,
            atr_pct REAL,
            macd_bundle_json TEXT,
            computed_iso TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ind_last_td ON indicator_last(trade_date);
        CREATE TABLE IF NOT EXISTS alert_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fired_iso TEXT NOT NULL,
            anchor_trade_date TEXT NOT NULL,
            code TEXT NOT NULL,
            market TEXT NOT NULL,
            secid TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            rk TEXT,
            anchor_price REAL NOT NULL,
            summary TEXT NOT NULL,
            extra_json TEXT,
            eval_status TEXT NOT NULL DEFAULT 'pending',
            ret_1d REAL,
            ret_3d REAL,
            ret_5d REAL,
            hit INTEGER,
            evaluated_iso TEXT,
            user_feedback TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alert_eval ON alert_events(eval_status);
        CREATE INDEX IF NOT EXISTS idx_alert_type_td
            ON alert_events(alert_type, anchor_trade_date);
        CREATE INDEX IF NOT EXISTS idx_alert_secid_td
            ON alert_events(secid, anchor_trade_date);
        CREATE TABLE IF NOT EXISTS trend_slip_streak (
            rk TEXT PRIMARY KEY,
            secid TEXT NOT NULL,
            last_weak_anchor TEXT NOT NULL,
            streak INTEGER NOT NULL,
            updated_iso TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trend_streak_td
            ON trend_slip_streak(last_weak_anchor);
        """
    )
    conn.commit()
    _migrate_alert_events_user_feedback(conn)


def _migrate_alert_events_user_feedback(conn: sqlite3.Connection) -> None:
    try:
        cols = {
            str(r[1])
            for r in conn.execute("PRAGMA table_info(alert_events)").fetchall()
        }
    except sqlite3.Error:
        return
    if "user_feedback" in cols:
        return
    try:
        conn.execute("ALTER TABLE alert_events ADD COLUMN user_feedback TEXT")
        conn.commit()
    except sqlite3.Error:
        pass


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        (key, value),
    )
    conn.commit()


def secid_bar_stats(conn: sqlite3.Connection, secid: str) -> tuple[int, str | None]:
    """返回 (bars 条数, 最新 trade_date YYYY-MM-DD 或 None)。"""
    row = conn.execute(
        "SELECT COUNT(*), MAX(trade_date) FROM daily_klines WHERE secid = ?",
        (str(secid).strip(),),
    ).fetchone()
    if not row:
        return 0, None
    n = int(row[0] or 0)
    mx = row[1]
    s = str(mx).strip()[:10] if mx else None
    return n, s or None


def secid_incremental_skip_ok(
    conn: sqlite3.Connection,
    secid: str,
    *,
    min_rows: int,
    max_stale_calendar_days: int,
    target_bars: int | None = None,
) -> bool:
    """本地已有足够根数且最新日 K 未过旧时跳过网络拉取。"""
    n, mx = secid_bar_stats(conn, secid)
    tb = int(target_bars) if target_bars is not None else 0
    if tb > 0 and n < tb:
        return False
    if n < max(1, int(min_rows)):
        return False
    if not mx:
        return False
    try:
        last = date.fromisoformat(mx[:10])
    except ValueError:
        return False
    age = (date.today() - last).days
    return age <= max(0, int(max_stale_calendar_days))


def upsert_bars(
    conn: sqlite3.Connection,
    secid: str,
    rows: Iterable[tuple[str, float, float, float, float, float]],
) -> int:
    """rows: (trade_date YYYY-MM-DD, o,h,l,c,v) 按日期升序或乱序均可。"""
    n = 0
    cur = conn.cursor()
    for trade_date, o, h, low, c, v in rows:
        cur.execute(
            """
            INSERT INTO daily_klines(secid, trade_date, open, high, low, close, volume)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(secid, trade_date) DO UPDATE SET
              open=excluded.open, high=excluded.high, low=excluded.low,
              close=excluded.close, volume=excluded.volume
            """,
            (secid, trade_date[:10], float(o), float(h), float(low), float(c), float(v)),
        )
        n += 1
    conn.commit()
    return n


def read_meta_value(db_path: Path, key: str) -> str | None:
    """读取 meta 表（如 last_full_sync_iso）；库不存在时返回 None。"""
    if not db_path.is_file():
        return None
    with _DB_LOCK:
        conn = _connect(db_path)
        try:
            init_schema(conn)
            return meta_get(conn, key)
        finally:
            conn.close()


def read_last_trade_date_for_secid(db_path: Path, secid: str) -> str | None:
    """该 secid 在库中最新一根日 K 的 trade_date（YYYY-MM-DD）。"""
    if not db_path.is_file():
        return None
    with _DB_LOCK:
        conn = _connect(db_path)
        try:
            init_schema(conn)
            row = conn.execute(
                """
                SELECT trade_date FROM daily_klines
                WHERE secid = ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (str(secid).strip(),),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return str(row[0] or "")[:10] or None


def read_ohlcv_lists(
    db_path: Path,
    secid: str,
    *,
    lmt: int,
) -> tuple[list[float], list[float], list[float], list[float], list[float]] | None:
    """返回按日期升序的 opens,highs,lows,closes,volumes；不足 lmt 则返回 None。"""
    eff = max(40, int(lmt))
    if not db_path.is_file():
        return None
    with _DB_LOCK:
        conn = _connect(db_path)
        try:
            init_schema(conn)
            rows = conn.execute(
                """
                SELECT open, high, low, close, volume FROM daily_klines
                WHERE secid = ?
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (secid, eff),
            ).fetchall()
        finally:
            conn.close()
    if len(rows) < eff:
        return None
    rows = list(reversed(rows))
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    vols = [float(r["volume"] or 0) for r in rows]
    return opens, highs, lows, closes, vols


def is_db_fresh(db_path: Path, fresh_hours: float) -> bool:
    """根据 meta.last_full_sync_iso 判断是否仍可用本地数据。"""
    if fresh_hours <= 0 or not db_path.is_file():
        return False
    try:
        from datetime import datetime, timedelta

        with _DB_LOCK:
            conn = _connect(db_path)
            try:
                init_schema(conn)
                s = meta_get(conn, "last_full_sync_iso")
            finally:
                conn.close()
        if not s:
            return False
        t0 = datetime.fromisoformat(str(s).replace("Z", ""))
        return datetime.now() - t0 < timedelta(hours=float(fresh_hours))
    except Exception:
        return False


def touch_full_sync(conn: sqlite3.Connection) -> None:
    from datetime import datetime

    meta_set(conn, "last_full_sync_iso", datetime.now().isoformat(timespec="seconds"))
