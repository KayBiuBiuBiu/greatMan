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


def compute_position_suggestion_hit(
    extra: dict[str, Any] | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    ev: dict[str, Any],
) -> int | None:
    """
    仓位建议回测：与远期收益对比。
    hit=1 建议方向与 T+5（优先）走势一致；0 明显相反；None 数据不足或落在中性带。

    ev 来自 alert_log.position_suggestion_eval，值为「百分数」如 -0.5 表示 -0.5%。
    """
    _ = r1
    _ = r3
    if not extra:
        return None
    act = str(extra.get("ps_action") or "").strip()
    if act not in ("卖出", "补仓", "持有"):
        return None

    def pct(name: str, default: float) -> float:
        try:
            return float(ev.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    def frac(name: str, default: float) -> float:
        return pct(name, default) / 100.0

    if act == "卖出":
        h = frac("sell_hit_r5_below_pct", -0.5)
        m = frac("sell_miss_r5_above_pct", 1.5)
        if r5 is not None:
            if r5 <= h:
                return 1
            if r5 >= m:
                return 0
        return None

    if act == "补仓":
        h = frac("add_hit_r5_above_pct", 0.5)
        m = frac("add_miss_r5_below_pct", -2.0)
        if r5 is not None:
            if r5 >= h:
                return 1
            if r5 <= m:
                return 0
        return None

    if act == "持有":
        hi = frac("hold_hit_abs_r5_below_pct", 3.0)
        mis = frac("hold_miss_abs_r5_above_pct", 6.0)
        if r5 is None:
            return None
        a = abs(float(r5))
        if a <= hi:
            return 1
        if a >= mis:
            return 0
        return None

    return None


TAKE_PROFIT_RISK_KINDS = frozenset({"take_profit_wave", "take_profit_short"})


def compute_strategy_hit(
    summary: str | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    ev: dict[str, Any],
) -> int | None:
    """
    策略类（箱体/均线等）事后命中：从 summary 识别买入/卖出话术。
    买入：默认 T+5 收益 > 0 为 hit；无 r5 时可用 T+1 同号替代。
    卖出：默认 T+5 收益 < 0 为 hit（卖后走弱）；无 r5 时看 T+1。
    阈值单位为「百分数」如 buy_hit_r5_above_pct=0 表示 r5>0 即命中。
    """
    _ = r3
    s = str(summary or "")
    is_buy = "【买入信号】" in s
    is_sell = "【卖出信号】" in s
    if not is_buy and not is_sell:
        return None

    def f(name: str, default: float) -> float:
        try:
            return float(ev.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    buy_r5_th = f("buy_hit_r5_above_pct", 0.0) / 100.0
    sell_r5_th = f("sell_hit_r5_below_pct", 0.0) / 100.0
    buy_r1_th = f("buy_hit_r1_above_pct", 0.0) / 100.0
    sell_r1_th = f("sell_hit_r1_below_pct", 0.0) / 100.0

    if is_buy:
        if r5 is not None:
            return 1 if r5 > buy_r5_th else 0
        if r1 is not None:
            return 1 if r1 > buy_r1_th else 0
        return None

    if r5 is not None:
        if sell_r5_th == 0.0:
            return 1 if r5 < 0.0 else 0
        return 1 if r5 < sell_r5_th else 0
    if r1 is not None:
        if sell_r1_th == 0.0:
            return 1 if r1 < 0.0 else 0
        return 1 if r1 < sell_r1_th else 0
    return None


def compute_risk_stop_hit(
    extra: dict[str, Any] | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    *,
    th1: float,
    th3: float,
    th5: float,
    take_profit_eval: dict[str, Any],
) -> int | None:
    """
    止损：与 bearish/drawdown 相同阈值。
    止盈（波段/短线）：默认「卖对算 hit」——锚点后 T+1、T+5 收跌视为止盈正确；
    take_profit_hit_for_correctness=0 时切回旧语义（T+1 超阈或 T+5>0 视为「卖飞」hit）。
    """
    _ = th3, th5
    kind = str((extra or {}).get("risk_kind") or "").strip()
    if kind == "stop_loss":
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
    if kind in TAKE_PROFIT_RISK_KINDS:
        raw_corr = take_profit_eval.get("take_profit_hit_for_correctness", 1.0)
        try:
            use_correctness = bool(float(raw_corr))
        except (TypeError, ValueError):
            use_correctness = True
        if not use_correctness:
            try:
                t1p = float(
                    take_profit_eval.get("take_profit_hit_r1_above_pct", 0.5)
                ) / 100.0
            except (TypeError, ValueError):
                t1p = 0.005
            hit_up = (r1 is not None and r1 > t1p) or (
                r5 is not None and r5 > 0.0
            )
            if hit_up:
                return 1
            if r1 is None and r5 is None:
                return None
            miss = (r1 is not None and r1 <= t1p) and (
                r5 is not None and r5 <= 0.0
            )
            if miss:
                return 0
            return None

        if r1 is not None and r5 is not None:
            return 1 if (r1 < 0.0 and r5 < 0.0) else 0
        if r1 is not None:
            return 1 if r1 < 0.0 else 0
        if r5 is not None:
            return 1 if r5 < 0.0 else 0
        return None
    return None


def row_hit_for_eval(
    alert_type: str,
    extra_json: str | None,
    r1: float | None,
    r3: float | None,
    r5: float | None,
    thresholds: dict[str, Any],
    *,
    summary: str | None = None,
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
    if alert_type == "position_suggestion":
        ev = thresholds.get("position_suggestion_eval")
        if not isinstance(ev, dict):
            ev = {}
        return compute_position_suggestion_hit(extra, r1, r3, r5, ev)
    if alert_type == "strategy":
        ev = thresholds.get("strategy_hit_eval")
        if not isinstance(ev, dict):
            ev = {}
        return compute_strategy_hit(summary, r1, r3, r5, ev)
    if alert_type == "risk_stop_take":
        tpe = thresholds.get("risk_stop_take_eval")
        if not isinstance(tpe, dict):
            tpe = {}
        return compute_risk_stop_hit(
            extra, r1, r3, r5, th1=th1, th3=th3, th5=th5, take_profit_eval=tpe
        )
    return compute_bearish_hit(
        alert_type, extra, r1, r3, r5, th1=th1, th3=th3, th5=th5
    )


def evaluate_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    thresholds: dict[str, Any],
) -> tuple[float | None, float | None, float | None, int | None]:
    secid = str(row["secid"])
    anchor_td = str(row["anchor_trade_date"])
    anchor_px = float(row["anchor_price"])
    r1, r3, r5 = forward_returns_vs_anchor(conn, secid, anchor_td, anchor_px)
    ex = row["extra_json"] if row["extra_json"] is not None else None
    summ = row["summary"] if row["summary"] is not None else ""
    hit = row_hit_for_eval(
        str(row["alert_type"]),
        ex,
        r1,
        r3,
        r5,
        thresholds=thresholds,
        summary=str(summ),
    )
    return r1, r3, r5, hit


def _normalize_code6(code: str) -> str:
    s = "".join(c for c in str(code).strip() if c.isdigit())
    if len(s) >= 6:
        return s[-6:].zfill(6)
    return s.zfill(6) if s else ""


def apply_feedback_to_latest_alert(
    cfg: dict[str, Any],
    root: Path,
    *,
    code: str,
    feedback: str,
) -> int:
    """
    将最近一条尚未标注的 trend_slip/drawdown 预警标记为 fp/tp。
    返回更新的行数（0 或 1）。
    """
    fb = str(feedback or "").strip().lower()
    if fb not in ("fp", "tp"):
        return 0
    c6 = _normalize_code6(code)
    if len(c6) != 6:
        return 0
    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None or not db_path.is_file():
        return 0
    types = tuple(sorted(BEARISH_ALERT_TYPES))
    with db_lock():
        conn = open_store_connection(db_path)
        try:
            init_schema(conn)
            row = conn.execute(
                f"""
                SELECT id FROM alert_events
                WHERE code = ? AND alert_type IN ({",".join("?" * len(types))})
                  AND (user_feedback IS NULL OR TRIM(user_feedback) = '')
                ORDER BY id DESC
                LIMIT 1
                """,
                (c6,) + types,
            ).fetchone()
            if not row:
                return 0
            conn.execute(
                "UPDATE alert_events SET user_feedback = ? WHERE id = ?",
                (fb, int(row[0])),
            )
            conn.commit()
        finally:
            conn.close()
    return 1


def distinct_fp_codes_since(
    cfg: dict[str, Any],
    root: Path,
    *,
    anchor_since: str,
) -> list[str]:
    """anchor_trade_date >= anchor_since 且 user_feedback='fp' 的去重股票代码（6 位）。"""
    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None or not db_path.is_file():
        return []
    since = str(anchor_since or "").strip()[:10]
    if len(since) != 10:
        return []
    with db_lock():
        conn = open_store_connection(db_path)
        try:
            init_schema(conn)
            cur = conn.execute(
                """
                SELECT DISTINCT code FROM alert_events
                WHERE user_feedback = 'fp' AND length(anchor_trade_date) >= 10
                  AND anchor_trade_date >= ?
                ORDER BY code
                """,
                (since,),
            )
            out = [_normalize_code6(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()
    return [c for c in out if len(c) == 6]
