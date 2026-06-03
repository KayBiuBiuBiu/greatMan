"""
为每只股生成一条大白话的日报标签。
根据板块关联的美股和期货，简明地说出：昨天这个行业板块的全球态势。

示例输出：
  🌍 美股纳指涨 + 📦铜期跌 | 综合：偏弱，谨慎
  🌍 美股芯片涨 + 📦无期货 | 综合：看好
"""

from __future__ import annotations

from typing import Any
from quote_us_stocks import get_us_quote
from quote_commodities import get_commodity_price


# 板块 → 美股对标 + 商品期货的映射
SECTOR_CONTEXT = {
    "芯片": {
        "us_stocks": ["NVDA", "TSM", "ASML"],
        "us_desc": "芯片链",
        "commodities": [],
        "zh_name": "芯片",
    },
    "半导体": {
        "us_stocks": ["NVDA", "TSM", "ASML"],
        "us_desc": "芯片链",
        "commodities": [],
        "zh_name": "半导体",
    },
    "光通信": {
        "us_stocks": ["QQQ"],
        "us_desc": "纳指",
        "commodities": [],
        "zh_name": "光通信",
    },
    "新能源": {
        "us_stocks": ["QQQ", "TSLA"],
        "us_desc": "科技/新能源",
        "commodities": [],
        "zh_name": "新能源",
    },
    "新能源汽车": {
        "us_stocks": ["TSLA", "QQQ"],
        "us_desc": "EV/纳指",
        "commodities": [],
        "zh_name": "新能源汽车",
    },
    "有色金属": {
        "us_stocks": [],
        "us_desc": "",
        "commodities": ["copper"],
        "zh_name": "有色金属",
    },
    "消费": {
        "us_stocks": ["SPY"],
        "us_desc": "标普500",
        "commodities": [],
        "zh_name": "消费",
    },
    "医药": {
        "us_stocks": ["XLV"],
        "us_desc": "医疗",
        "commodities": [],
        "zh_name": "医药",
    },
    "金融": {
        "us_stocks": ["SPY"],
        "us_desc": "标普500",
        "commodities": [],
        "zh_name": "金融",
    },
    "纺织服饰": {
        "us_stocks": [],
        "us_desc": "",
        "commodities": [],
        "zh_name": "纺织服饰",
    },
}


def get_sector_daily_summary(code: str, sector: str = "") -> str:
    """
    根据板块，生成一条大白话的日报标签。

    返回格式：
      🌍 美股纳指↑+0.46% | 📦 铜期↓-1.01% | 💡 综合判断：偏弱，建议观望
    """
    # 查找板块配置
    sector_info = None
    if sector:
        sector_info = SECTOR_CONTEXT.get(sector)

    if not sector_info:
        # 从代码推断（备选方案，这里简化处理）
        return ""

    parts = []

    # 获取美股信息
    if sector_info.get("us_stocks"):
        us_prices = {}
        for sym in sector_info["us_stocks"]:
            q = get_us_quote(sym)
            if q:
                us_prices[sym] = q["change_pct"]

        if us_prices:
            # 判断美股整体方向
            avg_pct = sum(us_prices.values()) / len(us_prices)
            arrow = "↑" if avg_pct > 0 else "↓"

            parts.append(
                f"🌍 美股{sector_info['us_desc']}{arrow}{avg_pct:+.2f}%"
            )

    # 获取期货信息
    if sector_info.get("commodities"):
        comm_prices = {}
        for comm in sector_info["commodities"]:
            p = get_commodity_price(comm)
            if p:
                comm_prices[comm] = (p["change_pct"], p["zh_name"])

        if comm_prices:
            for comm, (pct, zh_name) in comm_prices.items():
                arrow = "↑" if pct > 0 else "↓"
                parts.append(f"📦 {zh_name}{arrow}{pct:+.2f}%")

    # 综合判断
    if parts:
        # 计算综合态势
        all_pcts = []
        if sector_info.get("us_stocks"):
            for sym in sector_info["us_stocks"]:
                q = get_us_quote(sym)
                if q:
                    all_pcts.append(q["change_pct"])

        if sector_info.get("commodities"):
            for comm in sector_info["commodities"]:
                p = get_commodity_price(comm)
                if p:
                    all_pcts.append(p["change_pct"])

        if all_pcts:
            avg = sum(all_pcts) / len(all_pcts)
            if avg > 1.0:
                verdict = "💚 很强势，可加仓"
            elif avg > 0.2:
                verdict = "💙 偏强，可考虑"
            elif avg > -0.2:
                verdict = "💛 混合信号，观望"
            elif avg > -1.0:
                verdict = "💔 偏弱，谨慎"
            else:
                verdict = "💀 很弱势，减仓"
        else:
            verdict = "❓ 无参考数据"

        return " | ".join(parts) + f" | {verdict}"

    return ""


def format_stock_with_sector_summary(code: str, name: str, sector: str,
                                     price: float, chg_pct: float,
                                     shares: int = 0) -> str:
    """
    格式化单只股的显示，加上板块日报标签。

    返回格式：
      002110 盛屯矿业    现价 $8.50 📈+1.20%  持仓 5000股
        └→ 昨晚全球态势：🌍 美股无对标 | 📦 铜期↓-1.01% | 💔 很弱势，减仓
    """
    # 第一行：基本信息
    if chg_pct > 0:
        chg_arrow = "📈"
    elif chg_pct < 0:
        chg_arrow = "📉"
    else:
        chg_arrow = "→"

    line1 = f"  {code} {name:12} | 现价 ${price:7.2f} {chg_arrow}{chg_pct:+6.2f}%"

    if shares > 0:
        line1 += f" | 持仓 {shares:6}股"

    # 第二行：板块日报标签
    summary = get_sector_daily_summary(code, sector)
    if summary:
        line2 = f"       └→ 昨晚全球态势：{summary}"
    else:
        line2 = ""

    return line1 + ("\n" + line2 if line2 else "")


if __name__ == "__main__":
    # 测试
    print("=" * 90)
    print("【大白话日报标签测试】")
    print("=" * 90)

    test_cases = [
        {
            "code": "002110",
            "name": "盛屯矿业",
            "sector": "有色金属",
            "price": 8.50,
            "chg_pct": 1.2,
            "shares": 5000,
        },
        {
            "code": "688008",
            "name": "澜起科技",
            "sector": "芯片",
            "price": 152.50,
            "chg_pct": -1.61,
            "shares": 100,
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "sector": "新能源汽车",
            "price": 180.50,
            "chg_pct": 3.14,
            "shares": 50,
        },
        {
            "code": "600522",
            "name": "中天科技",
            "sector": "光通信",
            "price": 12.30,
            "chg_pct": 2.5,
            "shares": 200,
        },
    ]

    for tc in test_cases:
        print(
            format_stock_with_sector_summary(
                tc["code"],
                tc["name"],
                tc["sector"],
                tc["price"],
                tc["chg_pct"],
                tc["shares"],
            )
        )
        print()
