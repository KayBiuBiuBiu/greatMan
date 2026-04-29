from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class RiskAdvice:
    level: str
    max_position_ratio: float
    stop_loss_pct: float
    take_profit_pct: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def market_risk_level(index_mood_mult: float) -> str:
    if index_mood_mult <= 0.75:
        return "high"
    if index_mood_mult <= 0.95:
        return "medium"
    return "low"


def high_position_guard(price: float, ma20: float, high20: float) -> bool:
    if ma20 <= 0:
        return False
    over_ma = (price - ma20) / ma20
    near_high = price >= high20 * 0.98
    return over_ma >= 0.12 and near_high


def advise_position(signal_score: float, index_mood_mult: float, high_risk: bool) -> RiskAdvice:
    lvl = market_risk_level(index_mood_mult)
    if lvl == "high" or high_risk:
        return RiskAdvice(
            level="conservative",
            max_position_ratio=0.2,
            stop_loss_pct=3.5,
            take_profit_pct=6.0,
            reason="Market risk high or stock is over-extended",
        )
    if signal_score >= 80 and lvl == "low":
        return RiskAdvice(
            level="active",
            max_position_ratio=0.45,
            stop_loss_pct=5.0,
            take_profit_pct=12.0,
            reason="Strong signal under low macro risk",
        )
    return RiskAdvice(
        level="balanced",
        max_position_ratio=0.3,
        stop_loss_pct=4.0,
        take_profit_pct=8.0,
        reason="Default balanced risk profile",
    )


def build_risk_snapshot(price: float, kline: dict[str, Any], signal_score: float, index_mood_mult: float) -> dict[str, Any]:
    ma20 = float(kline.get("ma20") or 0.0)
    high20 = float(kline.get("high20") or 0.0)
    high_risk = high_position_guard(price, ma20, high20)
    advice = advise_position(signal_score, index_mood_mult, high_risk)
    return {
        "market_risk_level": market_risk_level(index_mood_mult),
        "high_position_risk": high_risk,
        "position_advice": advice.to_dict(),
    }

