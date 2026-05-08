"""Strategy compatibility layer for runtime alerting."""

from __future__ import annotations

from typing import Any, Optional

from quant_core.strategies import evaluate_all_strategies

# 大白话说明（内部键为 strategy / action，与 quant_core.strategies 一致）
_SIGNAL_FRIENDLY: dict[tuple[str, str], str] = {
    ("range_arbitrage", "sell_range_high"): "股价处在区间偏上，按震荡思路可以先减一点、落袋为安",
    ("range_arbitrage", "buy_range_low"): "股价处在区间偏下，按震荡思路可以小仓分批低吸",
    ("ma_dip", "buy_watch"): "价格靠近均线和箱体下半，偏防守低吸，可先观察再动手",
    ("ma_dip", "risk_reduce"): "均线走弱、价格在均线下方，先控风险、可考虑减仓",
    ("box_breakout", "buy_breakout"): "价格冲出近 20 日箱体上沿，突破形态，可关注但别追高",
    ("box_breakout", "stop_loss_alert"): "价格跌穿近 20 日箱体下沿，形态走坏，注意止损",
}


def ma_box_strategy(
    price: float,
    data: dict[str, Any],
    *,
    min_score_by_strategy: dict[str, float] | None = None,
) -> Optional[str]:
    signals = evaluate_all_strategies(
        price, data, min_score_by_strategy=min_score_by_strategy
    )
    if not signals:
        return None
    best = max(signals, key=lambda x: float(x.score))
    label = {
        "ma_dip": "均线低吸",
        "box_breakout": "箱体突破",
        "range_arbitrage": "震荡套利",
    }.get(best.strategy, best.strategy)
    action = {
        "buy_watch": "观察低吸",
        "risk_reduce": "风控减仓",
        "buy_breakout": "突破关注",
        "stop_loss_alert": "止损预警",
        "buy_range_low": "低位分批",
        "sell_range_high": "高位止盈",
    }.get(best.action, best.action)
    if best.action in ("buy_watch", "buy_breakout", "buy_range_low"):
        side = "【买入信号】"
    elif best.action in ("risk_reduce", "stop_loss_alert", "sell_range_high"):
        side = "【卖出信号】"
    else:
        side = "【策略信号】"
    key = (best.strategy, best.action)
    tip = _SIGNAL_FRIENDLY.get(key)
    if tip:
        body = f"{tip}（参考分 {best.score:.1f}）"
    else:
        body = f"{label}｜{action}｜参考分 {best.score:.1f}"
    return f"{side} {body}"
