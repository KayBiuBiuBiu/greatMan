"""Strategy compatibility layer for runtime alerting."""

from __future__ import annotations

from typing import Any, Optional

from quant_core.strategies import evaluate_all_strategies


def ma_box_strategy(price: float, data: dict[str, Any]) -> Optional[str]:
    signals = evaluate_all_strategies(price, data)
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
    return f"{side} {label}｜{action}｜score {best.score:.1f}"
