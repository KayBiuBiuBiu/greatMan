"""1W 量级风控：补仓档位、止盈止损、仓位上限；补仓后摊薄成本与回本涨幅。"""

from __future__ import annotations

from typing import Any, Optional


class RiskManager:
    def __init__(self, cfg: dict[str, Any]) -> None:
        cap = cfg["capital"]
        self.total_cap = float(cap["total"])
        self.max_total_pos = self.total_cap * float(cap["max_total_position_ratio"])
        self.max_single_pos = self.total_cap * float(cap["max_single_stock_ratio"])

        br = cfg["buy_rule"]
        self.base_pos = float(br["base_position"])
        self.add1_ratio = float(br["add_1_ratio"])
        self.add1_money = float(br["add_1_money"])
        self.add2_ratio = float(br["add_2_ratio"])
        self.add2_money = float(br["add_2_money"])
        self.forbid_add_ratio = float(br["forbid_add_ratio"])

        rr = cfg["risk_rule"]
        self.sl_ratio = float(rr["stop_loss_ratio"])
        self.tp_short = float(rr["take_profit_short"])
        self.tp_wave = float(rr["take_profit_wave"])

    def get_current_loss_ratio(self, now_price: float, cost_price: float) -> float:
        """相对成本的收益率，亏损为负，如 -0.06 表示 -6%。cost<=0 视为 0。"""
        if cost_price <= 0:
            return 0.0
        return round((now_price - cost_price) / cost_price, 6)

    def calc_profit_pct(self, now_price: float, cost_price: float) -> float:
        """持仓盈亏百分比（软件常用显示）。"""
        if cost_price <= 0:
            return 0.0
        return round((now_price - cost_price) / cost_price * 100.0, 2)

    def calc_after_add(
        self,
        old_cost: float,
        old_share: int,
        new_price: float,
        new_money: float,
    ) -> dict[str, Any]:
        """
        补仓后：新股数、摊薄成本、补仓后相对现价盈亏%、从现价涨到摊薄成本所需涨幅%。
        """
        if new_price <= 0:
            return {
                "new_share": 0,
                "new_avg_cost": 0.0,
                "after_profit_pct": 0.0,
                "need_rise_pct": 0.0,
            }
        new_share = int(new_money / new_price)
        if new_share <= 0:
            old_s = max(old_share, 0)
            if old_s <= 0 or old_cost <= 0:
                return {
                    "new_share": 0,
                    "new_avg_cost": 0.0,
                    "after_profit_pct": 0.0,
                    "need_rise_pct": 0.0,
                }
            ap = self.calc_profit_pct(new_price, old_cost)
            need = (
                round((old_cost - new_price) / new_price * 100.0, 2)
                if old_cost > new_price
                else 0.0
            )
            return {
                "new_share": 0,
                "new_avg_cost": round(old_cost, 3),
                "after_profit_pct": ap,
                "need_rise_pct": need,
            }

        total_share = max(old_share, 0) + new_share
        total_cost_val = max(old_cost, 0.0) * max(old_share, 0) + new_price * new_share
        new_avg = round(total_cost_val / total_share, 3) if total_share > 0 else 0.0
        after_pct = (
            round((new_price - new_avg) / new_avg * 100.0, 2) if new_avg > 0 else 0.0
        )
        need_rise = 0.0
        if new_avg > new_price > 0:
            need_rise = round((new_avg - new_price) / new_price * 100.0, 2)
        return {
            "new_share": new_share,
            "new_avg_cost": new_avg,
            "after_profit_pct": after_pct,
            "need_rise_pct": need_rise,
        }

    def check_add_order(
        self, now_price: float, cost_price: float
    ) -> Optional[dict[str, Any]]:
        """按亏损深度给出补仓档位；未触发返回 None。"""
        if cost_price <= 0:
            return None
        loss = self.get_current_loss_ratio(now_price, cost_price)
        if loss <= self.forbid_add_ratio:
            pct = abs(self.forbid_add_ratio) * 100
            return {
                "allow": False,
                "msg": f"亏损已超过约定阈值（约≥{pct:.0f}%），策略禁止补仓",
            }
        if loss <= self.add2_ratio:
            return {"allow": True, "level": "二档补仓", "money": self.add2_money}
        if loss <= self.add1_ratio:
            return {"allow": True, "level": "一档补仓", "money": self.add1_money}
        return None

    def check_stop_take(self, now_price: float, cost_price: float) -> Optional[str]:
        if cost_price <= 0:
            return None
        ratio = (now_price - cost_price) / cost_price
        if ratio <= self.sl_ratio:
            return "🔴 触及硬性止损线"
        if ratio >= self.tp_wave:
            return "🟢 波段止盈目标到位"
        if ratio >= self.tp_short:
            return "🟡 短线止盈目标到位"
        return None

    def profit_pct(self, now_price: float, cost_price: float) -> float:
        """兼容简短命名。"""
        return self.calc_profit_pct(now_price, cost_price)

    def after_add(
        self,
        old_cost: float,
        old_share: int,
        price: float,
        money: float,
    ) -> dict[str, Any]:
        d = self.calc_after_add(old_cost, old_share, price, money)
        return {
            "new_share": d["new_share"],
            "avg_cost": d["new_avg_cost"],
            "profit_pct": d["after_profit_pct"],
            "need_rise_pct": d["need_rise_pct"],
        }

    def check_add(self, now_price: float, cost_price: float) -> Optional[dict[str, Any]]:
        """仅返回允许补仓档位；禁止补仓或无触发返回 None。"""
        o = self.check_add_order(now_price, cost_price)
        if o is None or not o.get("allow", True):
            return None
        return {"level": o["level"], "money": float(o["money"])}

    def check_single_position_value(self, market_value: float) -> Optional[str]:
        if market_value > self.max_single_pos:
            return (
                f"单票持仓市值约 {market_value:.0f} 元，超过单票上限 {self.max_single_pos:.0f} 元"
            )
        return None

    def check_total_position_value(self, total_mv: float) -> Optional[str]:
        if total_mv > self.max_total_pos:
            return (
                f"持仓总市值约 {total_mv:.0f} 元，超过总仓位上限 {self.max_total_pos:.0f} 元"
            )
        return None

    def pos_warning(self, used: float) -> Optional[str]:
        """兼容旧命名：等同总仓位校验。"""
        return self.check_total_position_value(used)
