from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StrategySignal:
    strategy: str
    action: str
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ma_dip_strategy(price: float, kline: dict[str, Any]) -> StrategySignal | None:
    ma5 = float(kline["ma5"])
    ma20 = float(kline["ma20"])
    low20 = float(kline["low20"])
    high20 = float(kline["high20"])
    mid = (low20 + high20) / 2.0
    if ma5 >= ma20 and ma20 <= price <= mid:
        strength = min(1.0, max(0.0, (mid - price) / max(mid - ma20, 0.001)))
        return StrategySignal(
            strategy="ma_dip",
            action="buy_watch",
            score=70 + 20 * strength,
            reason="MA5>=MA20 and price near lower half of 20d box",
        )
    if ma5 < ma20 and price < ma20:
        return StrategySignal(
            strategy="ma_dip",
            action="risk_reduce",
            score=55,
            reason="MA5<MA20 and price below MA20",
        )
    return None


def box_breakout_strategy(price: float, kline: dict[str, Any]) -> StrategySignal | None:
    high20 = float(kline["high20"])
    low20 = float(kline["low20"])
    box_w = max(high20 - low20, 0.001)
    if price > high20:
        pct = (price - high20) / box_w
        return StrategySignal(
            strategy="box_breakout",
            action="buy_breakout",
            score=75 + min(15, pct * 100),
            reason="Price breaks above 20d high",
        )
    if price < low20:
        return StrategySignal(
            strategy="box_breakout",
            action="stop_loss_alert",
            score=60,
            reason="Price breaks below 20d low",
        )
    return None


def range_arbitrage_strategy(price: float, kline: dict[str, Any]) -> StrategySignal | None:
    high20 = float(kline["high20"])
    low20 = float(kline["low20"])
    if high20 <= low20:
        return None
    lower_zone = low20 + (high20 - low20) * 0.2
    upper_zone = high20 - (high20 - low20) * 0.2
    if price <= lower_zone:
        return StrategySignal(
            strategy="range_arbitrage",
            action="buy_range_low",
            score=72,
            reason="Price enters lower 20% of range",
        )
    if price >= upper_zone:
        return StrategySignal(
            strategy="range_arbitrage",
            action="sell_range_high",
            score=72,
            reason="Price enters upper 20% of range",
        )
    return None


_SELL_LIKE_ACTIONS = frozenset(
    {"sell_range_high", "stop_loss_alert", "risk_reduce"}
)


def evaluate_all_strategies(
    price: float,
    kline: dict[str, Any],
    *,
    min_score_by_strategy: dict[str, float] | None = None,
) -> list[StrategySignal]:
    """
    min_score_by_strategy: 策略名 -> 最低参考分；低于则丢弃该策略信号（仅影响买入侧候选，卖出仍保留）。
    """
    signals: list[StrategySignal] = []
    floors = min_score_by_strategy or {}
    for fn in (ma_dip_strategy, box_breakout_strategy, range_arbitrage_strategy):
        sig = fn(price, kline)
        if sig is None:
            continue
        floor = float(floors.get(sig.strategy, 0.0) or 0.0)
        if floor > 0 and float(sig.score) < floor and sig.action in (
            "buy_watch",
            "buy_breakout",
            "buy_range_low",
        ):
            continue
        signals.append(sig)
    return signals


def precompute_signal_proximity_hints(
    price: float,
    kline: dict[str, Any],
    *,
    min_score_by_strategy: dict[str, float] | None = None,
    up_pct: float = 2.0,
    down_pct: float = 2.0,
) -> list[str]:
    """
    用现价附近的假设价格跑一遍三策略，提示「再涨跌约 x% 时可能触发的卖出/风控类信号」。
    kline 为日 K 特征（ma5/ma20/low20/high20 等），与 evaluate_all_strategies 一致。
    """
    if price <= 0 or not isinstance(kline, dict):
        return []
    cur = evaluate_all_strategies(
        price, kline, min_score_by_strategy=min_score_by_strategy
    )
    cur_sellish = {s.action for s in cur if s.action in _SELL_LIKE_ACTIONS}
    hints: list[str] = []
    for label, pct in (("上涨", float(up_pct)), ("下跌", float(down_pct))):
        if pct <= 0:
            continue
        sign = 1.0 if label == "上涨" else -1.0
        px = price * (1.0 + sign * pct / 100.0)
        if px <= 0:
            continue
        fut = evaluate_all_strategies(
            px, kline, min_score_by_strategy=min_score_by_strategy
        )
        for fs in fut:
            if fs.action not in _SELL_LIKE_ACTIONS:
                continue
            if fs.action in cur_sellish:
                continue
            hints.append(
                f"若股价{label}约{pct:g}%（≈{px:.2f}），可能触发 {fs.strategy}·{fs.action} "
                f"（参考分 {fs.score:.1f}）"
            )
            break
    return hints

