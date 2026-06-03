"""
商品期货与相关 A 股的映射和显示。
用于在监控时关联商品价格与重仓股。
"""

from __future__ import annotations

from typing import Any
from quote_commodities import get_commodity_price, get_commodity_prices_batch


# 商品期货与 A 股上市公司的关联映射
COMMODITY_TO_A_STOCKS = {
    "copper": {
        "name": "铜价",
        "stocks": [
            {"code": "002110", "name": "盛屯矿业", "role": "重仓", "exposure": "高"},
            {"code": "601600", "name": "中国铝业", "role": "铝铜产业链", "exposure": "中"},
            {"code": "601899", "name": "紫金矿业", "role": "贵金属采矿", "exposure": "中"},
        ],
    },
    "iron_ore": {
        "name": "铁矿石",
        "stocks": [
            {"code": "601388", "name": "中国国旅", "role": "钢铁相关", "exposure": "中"},
            {"code": "601005", "name": "晋阳煤业", "role": "能源相关", "exposure": "中"},
        ],
    },
    "crude_oil": {
        "name": "原油",
        "stocks": [
            {"code": "601808", "name": "中国石油", "role": "能源龙头", "exposure": "高"},
            {"code": "600583", "name": "海油工程", "role": "油气设备", "exposure": "中"},
        ],
    },
    "gold": {
        "name": "黄金",
        "stocks": [
            {"code": "601899", "name": "紫金矿业", "role": "贵金属采矿", "exposure": "高"},
            {"code": "600988", "name": "中国银行", "role": "金融机构", "exposure": "低"},
        ],
    },
}

# 重仓观察列表（根据实际持仓调整）
HEAVY_HOLDINGS = {
    "002110": {  # 盛屯矿业
        "name": "盛屯矿业",
        "commodities": ["copper"],  # 主要看铜
        "role": "铜产业链参与者",
        "correlation": "高正相关",
    },
}


def format_commodity_display(commodity: str) -> str:
    """
    格式化商品期货显示。

    返回格式：
      [商品 价格 涨跌幅% | A股相关]
    """
    price_data = get_commodity_price(commodity)
    if not price_data:
        return ""

    arrow = "↑" if price_data["change_pct"] > 0 else "↓" if price_data["change_pct"] < 0 else "→"

    # 获取关联 A 股
    a_stocks = COMMODITY_TO_A_STOCKS.get(commodity, {}).get("stocks", [])
    stock_names = [s["name"] for s in a_stocks[:2]]  # 最多显示 2 个
    stock_str = "(" + "/".join(stock_names) + ")" if stock_names else ""

    return (
        f"[{price_data['zh_name']:8} {arrow}{price_data['change_pct']:+5.2f}% "
        f"${price_data['price']:.2f}{stock_str}]"
    )


def get_commodity_context_for_stock(code: str) -> dict[str, Any] | None:
    """
    获取某只 A 股对应的商品期货背景。

    用于查看重仓股（如盛屯矿业）时关联商品价格。
    """
    if code not in HEAVY_HOLDINGS:
        return None

    holding = HEAVY_HOLDINGS[code]
    commodities = holding.get("commodities", [])

    if not commodities:
        return None

    prices = {}
    for comm in commodities:
        p = get_commodity_price(comm)
        if p:
            prices[comm] = p

    if not prices:
        return None

    return {
        "stock_code": code,
        "stock_name": holding["name"],
        "commodities": prices,
        "correlation": holding["correlation"],
    }


def show_copper_dashboard() -> str:
    """
    显示铜价仪表板（给盛屯矿业用户）。

    包含：
    - COMEX 铜价实时行情
    - 关联 A 股列表
    - 相关性判断
    """
    copper = get_commodity_price("copper")
    if not copper:
        return "铜价获取失败"

    lines = [
        "\n" + "=" * 70,
        "🔶 【铜价仪表板】— 盛屯矿业重仓参考",
        "=" * 70,
        f"  现价: ${copper['price']:.2f}/磅",
        f"  涨跌: {copper['change_pct']:+.2f}% ({copper['change']:.2f})",
        f"  前收: ${copper['prev_close']:.2f}",
    ]

    # 显示关联的 A 股
    stocks = COMMODITY_TO_A_STOCKS.get("copper", {}).get("stocks", [])
    lines.append("\n  关联 A 股：")
    for stock in stocks:
        lines.append(
            f"    • {stock['name']} ({stock['code']}) — {stock['role']} "
            f"(曝光度: {stock['exposure']})"
        )

    # 判断
    if copper["change_pct"] > 0.5:
        sentiment = "💪 铜价强势 → 有利于盛屯矿业"
    elif copper["change_pct"] < -0.5:
        sentiment = "😰 铜价弱势 → 需要关注盛屯矿业走向"
    else:
        sentiment = "😐 铜价横盘 → 关注支撑位"

    lines.append(f"\n  {sentiment}")
    lines.append("=" * 70)

    return "\n".join(lines)


def show_commodities_overview() -> str:
    """显示所有大宗商品概览。"""
    commodities = ["copper", "iron_ore", "crude_oil", "gold"]
    prices = get_commodity_prices_batch(commodities)

    lines = [
        "\n" + "=" * 70,
        "📦 【大宗商品期货概览】",
        "=" * 70,
    ]

    for comm in commodities:
        price = prices.get(comm)
        if price:
            arrow = "📈" if price["change_pct"] > 0 else "📉" if price["change_pct"] < 0 else "→"
            lines.append(
                f"  {arrow} {price['zh_name']:8} ${price['price']:8.2f} "
                f"{price['change_pct']:+6.2f}%"
            )
        else:
            lines.append(f"  ❌ {COMMODITY_TO_A_STOCKS[comm]['name']:8} 获取失败")

    lines.append("=" * 70)
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    print(show_copper_dashboard())
    print(show_commodities_overview())

    print("\n" + "=" * 70)
    print("📊 盛屯矿业(002110)与铜价关联显示")
    print("=" * 70)

    ctx = get_commodity_context_for_stock("002110")
    if ctx:
        print(f"\n股票: {ctx['stock_name']}")
        print(f"相关商品: {', '.join(c for c in ctx['commodities'].keys())}")
        print(f"相关性: {ctx['correlation']}")

        for comm, price in ctx["commodities"].items():
            print(
                f"\n  {price['zh_name']:10} ${price['price']:8.2f} "
                f"{price['change_pct']:+6.2f}%"
            )
