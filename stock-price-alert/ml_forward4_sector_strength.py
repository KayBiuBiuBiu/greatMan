"""
选股阶段：用本地 daily_klines.db 计算申万一级相对上证 N 日超额，微调 ml_forward4（T+N 收涨 NB，N 见 FORWARD_UP_HORIZON_TRADING_DAYS）门槛。
不发起网络请求；数据不足时静默跳过。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kline_store import init_schema, open_store_connection
from quote_eastmoney import secid_for


def _parse_prob(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x < 0.0 or x > 1.0:
        return None
    return x


def _n_day_return_fraction(closes: list[float], n: int) -> float | None:
    if n < 1 or len(closes) < n + 1:
        return None
    c_old = float(closes[-1 - n])
    c_new = float(closes[-1])
    if c_old <= 0 or c_new <= 0:
        return None
    return c_new / c_old - 1.0


def read_closes_tail_asc(db_path: Path, secid: str, *, need: int) -> list[float] | None:
    """最近 need 根日 K 收盘价，升序；不足则 None。"""
    if not db_path.is_file() or need < 2:
        return None
    sid = str(secid).strip()
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        rows = conn.execute(
            """
            SELECT close FROM daily_klines
            WHERE secid = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (sid, int(need)),
        ).fetchall()
    finally:
        conn.close()
    if len(rows) < need:
        return None
    return [float(r[0]) for r in reversed(rows)]


def local_n_day_return_fraction(db_path: Path, secid: str, n: int) -> float | None:
    closes = read_closes_tail_asc(db_path, secid, need=n + 1)
    if not closes:
        return None
    return _n_day_return_fraction(closes, n)


def index_secid_from_ts_code(ts_code: str) -> str:
    """ts_code 如 000001.SH → kline_store 中 secid（与个股同步口径一致）。"""
    ts = str(ts_code or "000001.SH").strip().upper()
    if "." not in ts:
        return secid_for("000001", "sh")
    sym, suf = ts.split(".", 1)
    sym6 = "".join(ch for ch in sym if ch.isdigit()).zfill(6)
    if len(sym6) != 6:
        return secid_for("000001", "sh")
    suf = suf.strip().upper()
    if suf == "SH":
        return secid_for(sym6, "sh")
    if suf == "SZ":
        return secid_for(sym6, "sz")
    return secid_for("000001", "sh")


def precompute_sector_excess_vs_sh(
    cfg: dict[str, Any],
    db_path: Path,
    sw_ts_codes: set[str],
    *,
    lookback_days: int,
    index_ts_code: str = "000001.SH",
) -> tuple[dict[str, float], float | None]:
    """
    返回 (申万一级 ts_code -> 相对基准指数的 N 日超额收益比例),
    基准指数 N 日收益比例；指数数据不足时 ({}, None)。
    超额 = 板块 fraction - 指数 fraction。
    """
    _ = cfg
    n = max(1, int(lookback_days))
    bench = str(index_ts_code or "000001.SH").strip().upper()
    idx_secid = index_secid_from_ts_code(bench)

    idx_ret = local_n_day_return_fraction(db_path, idx_secid, n)
    if idx_ret is None:
        return {}, None

    out: dict[str, float] = {}
    for raw in sw_ts_codes:
        sw = str(raw).strip().upper()
        if not sw.endswith(".SI") or not sw[:-3].isdigit():
            continue
        sr = local_n_day_return_fraction(db_path, sw, n)
        if sr is None:
            continue
        out[sw] = float(sr) - float(idx_ret)
    return out, float(idx_ret)


def build_excess_frac_by_stock_code(
    codes: list[str],
    code_to_sw: dict[str, str],
    excess_by_sw: dict[str, float],
) -> dict[str, float]:
    """6 位代码 -> 超额（与 code_to_sw 对齐）。"""
    out: dict[str, float] = {}
    for c in codes:
        k = str(c).strip()
        sw = (code_to_sw.get(k) or "").strip().upper()
        if not sw:
            continue
        ex = excess_by_sw.get(sw)
        if ex is not None:
            out[k] = float(ex)
    return out


def sector_strength_adjust_gate_thresholds(
    mf4: dict[str, Any],
    excess_frac: float | None,
) -> tuple[float | None, float | None] | None:
    """
    基于超额收益调整当股的优质/观察门槛。
    返回 (qmin, wmin)；不需要板块修正时返回 None（调用方用配置原值）。
    """
    if excess_frac is None or not isinstance(mf4, dict):
        return None
    ss = mf4.get("sector_strength")
    if not isinstance(ss, dict) or not bool(ss.get("enabled", False)):
        return None
    try:
        thr = float(ss.get("outperform_threshold", 0.012) or 0.012)
    except (TypeError, ValueError):
        thr = 0.012
    try:
        qa = float(ss.get("quality_adjust", -0.02) or 0.0)
    except (TypeError, ValueError):
        qa = -0.02
    try:
        wa = float(ss.get("watch_adjust", -0.02) or 0.0)
    except (TypeError, ValueError):
        wa = -0.02
    try:
        lo = float(ss.get("clamp_min", 0.1) or 0.1)
    except (TypeError, ValueError):
        lo = 0.1
    try:
        hi = float(ss.get("clamp_max", 0.9) or 0.9)
    except (TypeError, ValueError):
        hi = 0.9
    lo = max(0.0, min(1.0, lo))
    hi = max(0.0, min(1.0, hi))
    if hi < lo:
        lo, hi = hi, lo

    qmin = _parse_prob(mf4.get("select_min_up_prob_quality"))
    wmin = _parse_prob(mf4.get("select_min_up_prob_watch"))
    if qmin is None and wmin is None:
        return None

    def _clamp(x: float | None) -> float | None:
        if x is None:
            return None
        return max(lo, min(hi, float(x)))

    q0, w0 = qmin, wmin
    if excess_frac >= thr:
        if qmin is not None:
            qmin = qmin + qa
        if wmin is not None:
            wmin = wmin + wa
    elif excess_frac <= -thr:
        if qmin is not None:
            qmin = qmin - qa
        if wmin is not None:
            wmin = wmin - wa
    else:
        return None

    q1, w1 = _clamp(qmin), _clamp(wmin)
    if q1 == q0 and w1 == w0:
        return None
    return q1, w1


def sector_strength_row_meta(
    mf4: dict[str, Any],
    excess_frac: float,
    *,
    q_before: float | None,
    w_before: float | None,
    q_after: float | None,
    w_after: float | None,
    sw_l1: str,
) -> dict[str, Any]:
    ss = mf4.get("sector_strength") if isinstance(mf4, dict) else None
    if not isinstance(ss, dict):
        return {}
    try:
        thr = float(ss.get("outperform_threshold", 0.012) or 0.012)
    except (TypeError, ValueError):
        thr = 0.012
    side = "neutral"
    if excess_frac >= thr:
        side = "outperform"
    elif excess_frac <= -thr:
        side = "underperform"
    return {
        "sw_l1": sw_l1,
        "excess_frac": round(float(excess_frac), 6),
        "side": side,
        "select_min_up_prob_quality": {"before": q_before, "after": q_after},
        "select_min_up_prob_watch": {"before": w_before, "after": w_after},
    }
