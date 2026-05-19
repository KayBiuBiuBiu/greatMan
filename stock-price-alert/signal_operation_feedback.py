#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信号与终端 buy/add/reduce/sell 关联、采纳后收益回填、供 auto_tune_strategy_scores 调分。"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent


def feedback_section(cfg: dict[str, Any]) -> dict[str, Any]:
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    raw = oa.get("self_improve_operation_feedback")
    return raw if isinstance(raw, dict) else {}


def feedback_enabled(cfg: dict[str, Any]) -> bool:
    return bool(feedback_section(cfg).get("enabled", False))


def _db_path(root: Path) -> Path:
    from position_ledger import ledger_db_path

    return ledger_db_path(root)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=12.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_signal_log_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS strategy_signal_log (
          signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT NOT NULL,
          signal_type TEXT NOT NULL,
          strategy_name TEXT NOT NULL,
          score REAL NOT NULL,
          timestamp TEXT NOT NULL,
          expired INTEGER NOT NULL DEFAULT 0,
          adopted INTEGER NOT NULL DEFAULT 0,
          adopted_timestamp TEXT,
          adopted_price REAL,
          adopted_shares INTEGER,
          ledger_event_id INTEGER,
          eval_return_pct REAL,
          eval_price_end REAL,
          eval_date_end TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_siglog_code_time ON strategy_signal_log(code, timestamp);
        CREATE INDEX IF NOT EXISTS idx_siglog_open ON strategy_signal_log(code, signal_type, adopted, expired);
        """
    )
    conn.commit()


def expire_open_signals_for_code_side(
    conn: sqlite3.Connection, *, code: str, signal_type: str
) -> None:
    conn.execute(
        """
        UPDATE strategy_signal_log SET expired = 1
        WHERE code = ? AND signal_type = ? AND adopted = 0 AND expired = 0
        """,
        (code, signal_type),
    )


def insert_signal_row(
    root: Path,
    *,
    code: str,
    signal_type: str,
    strategy_name: str,
    score: float,
    ts: datetime | None = None,
) -> int | None:
    """写入新信号；同代码同向未采纳旧信号标记 expired。"""
    db_path = _db_path(root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ts = ts or datetime.now()
    ts_s = ts.strftime("%Y-%m-%d %H:%M:%S")
    c6 = str(code or "").strip().zfill(6) if str(code or "").strip().isdigit() else str(code or "").strip()
    try:
        conn = _connect(db_path)
        try:
            from position_ledger import init_ledger_schema

            init_ledger_schema(conn)
            init_signal_log_schema(conn)
            expire_open_signals_for_code_side(conn, code=c6, signal_type=signal_type)
            cur = conn.execute(
                """
                INSERT INTO strategy_signal_log (
                  code, signal_type, strategy_name, score, timestamp, expired, adopted
                ) VALUES (?,?,?,?,?,0,0)
                """,
                (c6, signal_type, strategy_name, float(score), ts_s),
            )
            conn.commit()
            return int(cur.lastrowid or 0) or None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _LOG.warning("signal_operation_feedback: insert_signal_row failed: %s", exc)
        return None


def record_emitted_strategy_signal(
    cfg: dict[str, Any],
    root: Path,
    *,
    code: str,
    best_strategy: str,
    best_score: float,
    sig_text: str,
    ts: datetime | None = None,
) -> None:
    if not feedback_enabled(cfg):
        return
    if "【买入信号】" in sig_text:
        st = "buy"
    elif "【卖出信号】" in sig_text:
        st = "sell"
    else:
        return
    rid = insert_signal_row(
        root,
        code=code,
        signal_type=st,
        strategy_name=str(best_strategy or "").strip() or "unknown",
        score=float(best_score),
        ts=ts,
    )
    if rid:
        _LOG.debug(
            "signal_operation_feedback: recorded signal_id=%s %s %s %s",
            rid,
            code,
            st,
            best_strategy,
        )


def _match_window_start(cfg: dict[str, Any], now: datetime) -> str:
    s = feedback_section(cfg)
    try:
        minutes = max(1, int(s.get("match_window_minutes", 10) or 10))
    except (TypeError, ValueError):
        minutes = 10
    return (now - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def find_latest_open_signal(
    root: Path,
    *,
    code: str,
    signal_type: str,
    now: datetime,
    cfg: dict[str, Any],
) -> int | None:
    db_path = _db_path(root)
    if not db_path.is_file():
        return None
    c6 = str(code or "").strip().zfill(6) if str(code or "").strip().isdigit() else str(code or "").strip()
    tmin = _match_window_start(cfg, now)
    try:
        conn = _connect(db_path)
        try:
            init_signal_log_schema(conn)
            row = conn.execute(
                """
                SELECT signal_id FROM strategy_signal_log
                WHERE code = ? AND signal_type = ? AND adopted = 0 AND expired = 0
                  AND timestamp >= ?
                ORDER BY signal_id DESC LIMIT 1
                """,
                (c6, signal_type, tmin),
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def mark_signal_adopted(
    root: Path,
    *,
    signal_id: int,
    adopted_ts: str,
    adopted_price: float,
    adopted_shares: int,
    ledger_event_id: int | None,
) -> None:
    db_path = _db_path(root)
    try:
        conn = _connect(db_path)
        try:
            init_signal_log_schema(conn)
            conn.execute(
                """
                UPDATE strategy_signal_log SET
                  adopted = 1,
                  adopted_timestamp = ?,
                  adopted_price = ?,
                  adopted_shares = ?,
                  ledger_event_id = ?
                WHERE signal_id = ? AND adopted = 0
                """,
                (
                    adopted_ts,
                    float(adopted_price),
                    int(adopted_shares),
                    ledger_event_id,
                    int(signal_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _LOG.warning("signal_operation_feedback: mark_signal_adopted failed: %s", exc)


def try_cli_adopt_buy(
    cfg: dict[str, Any],
    root: Path,
    *,
    code: str,
    price: float,
    shares: int,
    ledger_event_id: int | None,
) -> None:
    if not feedback_enabled(cfg):
        return
    now = datetime.now()
    sid = find_latest_open_signal(root, code=code, signal_type="buy", now=now, cfg=cfg)
    if sid is None:
        return
    mark_signal_adopted(
        root,
        signal_id=sid,
        adopted_ts=now.strftime("%Y-%m-%d %H:%M:%S"),
        adopted_price=float(price),
        adopted_shares=int(shares),
        ledger_event_id=ledger_event_id,
    )


def try_cli_adopt_sell(
    cfg: dict[str, Any],
    root: Path,
    *,
    code: str,
    price: float,
    shares: int,
    ledger_event_id: int | None,
) -> None:
    if not feedback_enabled(cfg):
        return
    now = datetime.now()
    sid = find_latest_open_signal(root, code=code, signal_type="sell", now=now, cfg=cfg)
    if sid is None:
        return
    mark_signal_adopted(
        root,
        signal_id=sid,
        adopted_ts=now.strftime("%Y-%m-%d %H:%M:%S"),
        adopted_price=float(price),
        adopted_shares=int(shares),
        ledger_event_id=ledger_event_id,
    )


def _kline_db_path(cfg: dict[str, Any], root: Path) -> Path | None:
    ks = cfg.get("kline_store") if isinstance(cfg.get("kline_store"), dict) else {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p if p.is_file() else None


def _closes_from_adopt_day(
    conn: sqlite3.Connection, secid: str, adopt_day: str
) -> list[tuple[str, float]]:
    rows = conn.execute(
        """
        SELECT trade_date, close FROM daily_klines
        WHERE secid = ? AND trade_date >= ?
        ORDER BY trade_date ASC
        """,
        (secid, adopt_day[:10]),
    ).fetchall()
    out: list[tuple[str, float]] = []
    for r in rows:
        try:
            out.append((str(r[0]), float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def compute_buy_adopted_return_pct(
    cfg: dict[str, Any],
    root: Path,
    *,
    code: str,
    adopt_ts: str,
    adopt_price: float,
    horizon_days: int,
) -> tuple[float, str, float] | None:
    """采纳价 → 第 N 个交易日收盘价；返回 (pct, end_date, end_close) 或 None。"""
    if adopt_price <= 0:
        return None
    dbp = _kline_db_path(cfg, root)
    if not dbp:
        return None
    try:
        from backtest_picks_performance import code_to_secid
        from kline_store import init_schema, open_store_connection

        sid = code_to_secid(str(code).strip().zfill(6))
    except Exception:
        return None
    adopt_day = adopt_ts.strip()[:10]
    try:
        n = max(1, int(horizon_days))
    except (TypeError, ValueError):
        n = 5
    try:
        conn = open_store_connection(dbp)
        try:
            init_schema(conn)
            seq = _closes_from_adopt_day(conn, sid, adopt_day)
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if len(seq) <= n:
        return None
    end_date, end_close = seq[n]
    pct = (end_close - float(adopt_price)) / float(adopt_price) * 100.0
    return pct, end_date, end_close


def backfill_buy_eval_returns(cfg: dict[str, Any], root: Path, *, now: datetime | None = None) -> int:
    """为已采纳且未 eval 的买入信号回填 eval_return_pct（依赖日 K 库）。"""
    if not feedback_enabled(cfg):
        return 0
    now = now or datetime.now()
    try:
        n_days = max(1, int(feedback_section(cfg).get("eval_n_days", 5) or 5))
    except (TypeError, ValueError):
        n_days = 5
    db_path = _db_path(root)
    if not db_path.is_file():
        return 0
    updated = 0
    try:
        conn = _connect(db_path)
        try:
            init_signal_log_schema(conn)
            rows = conn.execute(
                """
                SELECT signal_id, code, adopted_timestamp, adopted_price
                FROM strategy_signal_log
                WHERE signal_type = 'buy' AND adopted = 1
                  AND adopted_price IS NOT NULL AND adopted_price > 0
                  AND adopted_timestamp IS NOT NULL
                  AND eval_return_pct IS NULL
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    for r in rows:
        sid = int(r["signal_id"])
        code = str(r["code"])
        ts = str(r["adopted_timestamp"] or "")
        px = float(r["adopted_price"] or 0.0)
        got = compute_buy_adopted_return_pct(
            cfg, root, code=code, adopt_ts=ts, adopt_price=px, horizon_days=n_days
        )
        if not got:
            continue
        pct, end_d, end_c = got
        try:
            conn = _connect(db_path)
            try:
                conn.execute(
                    """
                    UPDATE strategy_signal_log SET
                      eval_return_pct = ?, eval_price_end = ?, eval_date_end = ?
                    WHERE signal_id = ?
                    """,
                    (round(pct, 4), round(end_c, 4), end_d, sid),
                )
                conn.commit()
                updated += 1
            finally:
                conn.close()
        except sqlite3.Error:
            continue
    if updated:
        _LOG.info("signal_operation_feedback: backfilled eval rows=%s", updated)
    return updated


def _tune_state_path(root: Path) -> Path:
    return root / "data" / "operation_feedback_tune_state.json"


def _load_tune_state(root: Path) -> dict[str, Any]:
    p = _tune_state_path(root)
    if not p.is_file():
        return {"net_delta_by_strategy": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {"net_delta_by_strategy": {}}
    except (json.JSONDecodeError, OSError):
        return {"net_delta_by_strategy": {}}


def _save_tune_state(root: Path, st: dict[str, Any]) -> None:
    p = _tune_state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_auto_tune_log(root: Path, line: str) -> None:
    from auto_tune_selector_filters import LOG_PATH

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(line.rstrip() + "\n")
    except OSError:
        pass


def _atomic_save_config_json(path: Path, cfg: dict[str, Any]) -> bool:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def run_min_score_tune_from_feedback(
    cfg: dict[str, Any],
    *,
    config_path: Path,
    root: Path,
    now: datetime,
) -> dict[str, Any]:
    """按采纳后收益统计调整 strategy_signal.min_score_by_strategy；写回 config。"""
    out: dict[str, Any] = {"changed": False, "details": []}
    s = feedback_section(cfg)
    if not bool(s.get("enabled", False)):
        return out
    try:
        eval_days = max(7, int(s.get("evaluate_days", 30) or 30))
    except (TypeError, ValueError):
        eval_days = 30
    try:
        step = max(1, int(s.get("adjust_step", 2) or 2))
    except (TypeError, ValueError):
        step = 2
    try:
        max_ch = max(step, int(s.get("max_change", 10) or 10))
    except (TypeError, ValueError):
        max_ch = 10
    try:
        imp_th = float(s.get("improve_threshold_pct", 2.0) or 2.0)
    except (TypeError, ValueError):
        imp_th = 2.0
    try:
        deg_th = float(s.get("degrade_threshold_pct", -1.0) or -1.0)
    except (TypeError, ValueError):
        deg_th = -1.0
    try:
        min_samples = max(2, int(s.get("min_samples", 5) or 5))
    except (TypeError, ValueError):
        min_samples = 5
    try:
        floor_s = float(s.get("min_score_floor", 50.0) or 50.0)
    except (TypeError, ValueError):
        floor_s = 50.0
    try:
        ceil_s = float(s.get("min_score_ceiling", 90.0) or 90.0)
    except (TypeError, ValueError):
        ceil_s = 90.0

    since = (now.date() - timedelta(days=eval_days)).isoformat()
    db_path = _db_path(root)
    if not db_path.is_file():
        return out
    rows: list[sqlite3.Row] = []
    try:
        conn = _connect(db_path)
        try:
            init_signal_log_schema(conn)
            rows = list(
                conn.execute(
                    """
                    SELECT strategy_name,
                           COUNT(*) AS n,
                           AVG(eval_return_pct) AS avg_r,
                           SUM(CASE WHEN eval_return_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS winrate
                    FROM strategy_signal_log
                    WHERE signal_type = 'buy' AND adopted = 1
                      AND eval_return_pct IS NOT NULL
                      AND date(substr(adopted_timestamp,1,10)) >= date(?)
                    GROUP BY strategy_name
                    """,
                    (since,),
                ).fetchall()
            )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _LOG.warning("signal_operation_feedback: aggregate failed: %s", exc)
        return out

    st = _load_tune_state(root)
    netd: dict[str, float] = {}
    raw_nd = st.get("net_delta_by_strategy")
    if isinstance(raw_nd, dict):
        for k, v in raw_nd.items():
            try:
                netd[str(k)] = float(v)
            except (TypeError, ValueError):
                pass

    ss = cfg.setdefault("strategy_signal", {})
    if not isinstance(ss, dict):
        cfg["strategy_signal"] = {}
        ss = cfg["strategy_signal"]
    ms = ss.setdefault("min_score_by_strategy", {})
    if not isinstance(ms, dict):
        ss["min_score_by_strategy"] = {}
        ms = ss["min_score_by_strategy"]

    pending: list[
        tuple[str, float, float, float, int, float]
    ] = []  # strat, cur, new_score, new_nd, n, avg_r

    iso = now.strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        strat = str(r["strategy_name"] or "").strip()
        if not strat:
            continue
        n = int(r["n"] or 0)
        if n < min_samples:
            continue
        try:
            avg_r = float(r["avg_r"] or 0.0)
        except (TypeError, ValueError):
            avg_r = 0.0
        cur = float(ms.get(strat, 0.0) or 0.0)
        if cur <= 0:
            cur = 60.0
        nd = float(netd.get(strat, 0.0))
        direction = 0
        if avg_r > imp_th and abs(nd) < max_ch and cur > floor_s:
            direction = -1
        elif avg_r < deg_th and abs(nd) < max_ch and cur < ceil_s:
            direction = 1
        if direction == 0:
            continue
        step_use = min(step, max_ch - abs(nd))
        if step_use <= 0:
            continue
        delta = direction * float(step_use)
        new_nd = nd + delta
        if abs(new_nd) > max_ch + 1e-6:
            continue
        new_score = cur + delta
        new_score = max(floor_s, min(ceil_s, new_score))
        if abs(new_score - cur) < 1e-9:
            continue
        pending.append((strat, cur, round(new_score, 2), new_nd, n, avg_r))

    if not pending:
        return out

    bak = config_path.with_name(
        config_path.name + f".bak_opfb_{now.strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        import shutil

        shutil.copy2(config_path, bak)
    except OSError as exc:
        _LOG.warning("signal_operation_feedback: config backup failed: %s", exc)
        return {**out, "changed": False, "error": "backup_failed"}

    for strat, cur, new_score, new_nd, n, avg_r in pending:
        ms[strat] = new_score
        netd[strat] = new_nd
        out["details"].append(
            {
                "strategy": strat,
                "n": n,
                "avg_return_pct": round(avg_r, 4),
                "old_min": cur,
                "new_min": new_score,
                "net_delta": new_nd,
            }
        )
        _append_auto_tune_log(
            root,
            f"[{iso}] operation_feedback tune {strat}: n={n} avg_ret={avg_r:.3f}% "
            f"min_score {cur:.1f} -> {new_score:.1f} (net_delta={new_nd:.1f})",
        )

    if not _atomic_save_config_json(config_path, cfg):
        _LOG.warning("signal_operation_feedback: atomic config write failed")
        return {**out, "changed": False, "error": "save_failed"}

    st["net_delta_by_strategy"] = netd
    _save_tune_state(root, st)

    out["changed"] = True
    out["backup"] = str(bak)
    _append_auto_tune_log(
        root,
        f"[{iso}] operation_feedback wrote min_score_by_strategy: {json.dumps(ms, ensure_ascii=False)}",
    )
    return out


def find_open_signal_near_trade_day(
    root: Path,
    *,
    code: str,
    signal_type: str,
    trade_day: date,
    lookback_days: int,
) -> int | None:
    """交收日前 lookback_days 个自然日内发出的未采纳同向信号（后验匹配交割单）。"""
    db_path = _db_path(root)
    if not db_path.is_file():
        return None
    c6 = (
        str(code or "").strip().zfill(6)
        if str(code or "").strip().isdigit()
        else str(code or "").strip()
    )
    start = (trade_day - timedelta(days=max(1, lookback_days))).isoformat()
    end = trade_day.isoformat()
    try:
        conn = _connect(db_path)
        try:
            init_signal_log_schema(conn)
            row = conn.execute(
                """
                SELECT signal_id FROM strategy_signal_log
                WHERE code = ? AND signal_type = ? AND adopted = 0 AND expired = 0
                  AND date(substr(timestamp, 1, 10)) >= date(?)
                  AND date(substr(timestamp, 1, 10)) <= date(?)
                ORDER BY signal_id DESC LIMIT 1
                """,
                (c6, signal_type, start, end),
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def adopt_signals_from_broker_day_trades(
    cfg: dict[str, Any],
    root: Path,
    *,
    trade_day: date,
    day_trades: list[dict[str, Any]],
    lookback_days: int = 5,
) -> int:
    """
    按交割单当日买卖后验标记 strategy_signal_log 采纳（未走过 CLI 10 分钟窗口时补闭环）。
    返回新采纳条数。
    """
    if not feedback_enabled(cfg):
        return 0
    adopted_n = 0
    adopt_ts = f"{trade_day.isoformat()} 15:00:00"
    for row in day_trades:
        ev = row.get("event")
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        try:
            qty = int(row.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            px = float(row.get("price") or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if qty <= 0:
            continue
        st = "buy" if ev == "buy" else "sell" if ev == "sell" else None
        if st is None:
            continue
        sid = find_open_signal_near_trade_day(
            root,
            code=code,
            signal_type=st,
            trade_day=trade_day,
            lookback_days=lookback_days,
        )
        if sid is None:
            continue
        mark_signal_adopted(
            root,
            signal_id=sid,
            adopted_ts=adopt_ts,
            adopted_price=px,
            adopted_shares=qty,
            ledger_event_id=None,
        )
        adopted_n += 1
        _LOG.info(
            "broker_signal_adopt: signal_id=%s %s %s %s股 @%s",
            sid,
            code,
            st,
            qty,
            px,
        )
    return adopted_n
