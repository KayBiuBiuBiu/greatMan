"""候选排序：形态分、历史胜率估计、风险档、低吸逻辑（不参与持仓标签标的排名）。"""

from __future__ import annotations

from typing import Any, Optional

from strategy_engine import ma_box_strategy


def _box_position(price: float, low20: float, high20: float) -> float:
    span = max(high20 - low20, 1e-6)
    return (price - low20) / span


def estimate_win_rate_pct(closes: list[float], *, window: int = 20, fwd: int = 5) -> float:
    """过去约 120 根 K 上，简易「均线多头 + 箱体下半」信号的后验胜率。"""
    if len(closes) < window + fwd + 8:
        return 52.0
    wins = 0
    total = 0
    for i in range(window, len(closes) - fwd):
        seg = closes[i - window : i]
        if len(seg) < window:
            continue
        ma5 = sum(seg[-5:]) / 5
        ma20 = sum(seg[-20:]) / 20
        last20 = seg[-20:]
        low20, high20 = min(last20), max(last20)
        mid = (low20 + high20) / 2.0
        price = seg[-1]
        if ma5 <= ma20:
            continue
        if price > mid or price < low20:
            continue
        entry = price
        exit_idx = i - 1 + fwd
        if exit_idx >= len(closes):
            continue
        exitp = closes[exit_idx]
        total += 1
        if exitp > entry:
            wins += 1
    if total <= 0:
        return 52.0
    return round(wins / total * 100.0, 1)


def risk_level_label(
    price: float,
    low20: float,
    high20: float,
    closes: list[float],
) -> str:
    """粗分档：波动 + 箱体位置。"""
    rng = max(high20 - low20, 1e-6)
    vol = 0.0
    if len(closes) >= 21:
        tail = closes[-20:]
        chg = [abs(tail[i] - tail[i - 1]) / max(tail[i - 1], 1e-6) for i in range(1, len(tail))]
        vol = sum(chg) / max(len(chg), 1)
    pos = _box_position(price, low20, high20)
    if vol > 0.045 or pos > 0.92:
        return "高"
    if vol > 0.028 or pos > 0.78:
        return "中"
    return "低"


def dip_logic_text(
    price: float,
    ma5: float,
    ma20: float,
    low20: float,
    high20: float,
    sig: Optional[str],
) -> str:
    parts: list[str] = []
    bp = _box_position(price, low20, high20)
    if ma5 > ma20 and bp > 0.62:
        parts.append(
            "短线趋势还行，但股价快到前面高点附近了，这时候回调买进去不一定能涨，胜算一般。"
        )
    else:
        if ma5 > ma20:
            parts.append("短期均线位于中期均线上方")
        if bp <= 0.45:
            parts.append("股价处于近20日箱体偏下区域")
        elif bp <= 0.62:
            parts.append("股价处于箱体中下区域")
        else:
            parts.append("股价临近箱体上沿附近，回踩低吸确定性一般")
    if sig and "低吸" in sig:
        parts.append("与均线箱体低吸模板一致")
    elif sig and "跌破" in sig:
        parts.append("跌破箱体下沿，左侧博弈需谨慎")
    return "；".join(parts) if parts else "中性震荡，谨慎观察"


def liquidity_score(amount_yuan: float, float_mv_yuan: float, *, cfg: dict[str, Any]) -> float:
    """成交额与市值适中偏好（抑制极小 liquidity 垃圾票）。"""
    sr = cfg.get("scan_rule") or {}
    min_amt = float(sr.get("min_daily_amount_wan", 6500)) * 10000.0
    lo_mv = float(sr.get("min_float_mv_yi", 28)) * 1e8
    hi_mv = float(sr.get("max_float_mv_yi", 750)) * 1e8
    s = 0.0
    if amount_yuan >= min_amt * 1.2:
        s += 12
    elif amount_yuan >= min_amt:
        s += 8
    else:
        s += 3
    if lo_mv <= float_mv_yuan <= hi_mv:
        s += 8
    elif float_mv_yuan < lo_mv:
        s += 2
    else:
        s += 5
    return min(20.0, s)


def speculative_penalty(
    amount_yuan: float,
    float_mv_yuan: float,
    closes: list[float],
    *,
    cfg: dict[str, Any],
) -> float:
    """过滤游资小票、极端爆炒：成交额过小或波动过猛降权。"""
    sr = cfg.get("scan_rule") or {}
    min_amt = float(sr.get("min_daily_amount_wan", 6500)) * 10000.0
    pen = 1.0
    if amount_yuan < min_amt * 0.85:
        pen *= 0.75
    if float_mv_yuan < float(sr.get("min_float_mv_yi", 28)) * 1e8 * 0.85:
        pen *= 0.82
    if len(closes) >= 6:
        c0, c5 = closes[-1], closes[-6]
        if c5 > 0:
            r5 = abs(c0 - c5) / c5
            if r5 > 0.28:
                pen *= 0.78
            elif r5 > 0.18:
                pen *= 0.88
    return float(max(0.45, min(1.0, pen)))


def composite_pick_score(
    price: float,
    kline: dict[str, Any],
    closes: list[float],
    *,
    industry: str,
    stock_name: str,
    amount_yuan: float,
    float_mv_yuan: float,
    macro_mult: float,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """返回排序用总分及展示字段。"""
    ma5 = float(kline["ma5"])
    ma20 = float(kline["ma20"])
    low20 = float(kline["low20"])
    high20 = float(kline["high20"])
    ss = cfg.get("strategy_signal") or {}
    min_by = ss.get("min_score_by_strategy") if isinstance(ss, dict) else None
    sig = ma_box_strategy(
        price,
        kline,
        min_score_by_strategy=min_by if isinstance(min_by, dict) else None,
    )

    pattern = 0.0
    if ma5 > ma20:
        pattern += 28.0
    bp = _box_position(price, low20, high20)
    if bp <= 0.42:
        pattern += 32.0
    elif bp <= 0.58:
        pattern += 18.0
    else:
        pattern += 6.0
    if sig and "低吸" in sig:
        pattern += 28.0
    elif sig and "减仓" in sig:
        pattern -= 10.0
    pattern = max(0.0, min(100.0, pattern))

    win_pct = estimate_win_rate_pct(closes)
    liq = liquidity_score(amount_yuan, float_mv_yuan, cfg=cfg)
    spec = speculative_penalty(amount_yuan, float_mv_yuan, closes, cfg=cfg)

    fundamental_bonus = 6.0 if macro_mult >= 1.02 else 0.0
    total = (
        pattern * 0.42
        + win_pct * 0.22
        + liq * 1.1
        + fundamental_bonus
    ) * macro_mult * spec

    risk = risk_level_label(price, low20, high20, closes)
    logic = dip_logic_text(price, ma5, ma20, low20, high20, sig)

    profit_prob = max(15.0, min(92.0, win_pct * 0.92 + (pattern / 100.0) * 6.0))

    return {
        "pattern_score": round(pattern, 1),
        "win_rate_pct": win_pct,
        "profit_prob_pct": round(profit_prob, 1),
        "risk_level": risk,
        "dip_logic": logic,
        "sort_score": round(total, 4),
        "strategy_hint": sig or "",
    }
