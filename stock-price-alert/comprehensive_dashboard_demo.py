#!/usr/bin/env python3
"""
综合终端显示：美股 + 商品期货 + A 股
特别针对重仓盛屯矿业的用户优化。
"""

from display_with_us_context import show_us_context_banner, format_us_context_inline
from display_commodities import show_copper_dashboard, show_commodities_overview, format_commodity_display


def show_comprehensive_dashboard():
    """
    综合仪表板：启动时显示所有关键信息。
    """
    print("\n" + "=" * 90)
    print("🚀 股价监控启动 | 2026-06-03 09:30:00")
    print("=" * 90)

    print("\n📋 配置加载：15只标的 | 轮询 30s | 本金 528,166 元 | 最大仓位 50%")
    print("💎 重仓：盛屯矿业 002110 | 铜价相关性:高")

    # === 1. 美股背景 ===
    print("\n" + show_us_context_banner())

    # === 2. 大宗商品 ===
    print(show_commodities_overview())

    # === 3. 重仓专项 ===
    print(show_copper_dashboard())


def show_watchlist_with_context():
    """
    监控列表：每只股都展示对应的美股/商品期货背景。
    """
    print("\n\n" + "=" * 90)
    print("👁️  【盘中监控】- 实时持仓跟踪")
    print("=" * 90)

    holdings = [
        {
            "code": "002110",
            "name": "盛屯矿业",
            "industry": "有色金属",
            "price": 8.50,
            "chg": 1.2,
            "shares": 5000,
            "commodity": "copper",  # 新增：关联商品
        },
        {
            "code": "688008",
            "name": "澜起科技",
            "industry": "芯片",
            "price": 152.50,
            "chg": -1.61,
            "shares": 100,
        },
    ]

    for h in holdings:
        chg_arrow = "📈" if h["chg"] > 0 else "📉"
        total_pnl = h["price"] * h["shares"] * (h["chg"] / 100)

        # 第一行：基本股票信息 + 美股参考
        us_tag = format_us_context_inline(h["code"], h.get("industry", ""))
        print(
            f"  {h['code']} {h['name']:12} | 现价 ${h['price']:7.2f} {chg_arrow}{h['chg']:+6.2f}% | "
            f"持仓 {h['shares']:6}股 浮盈 {total_pnl:+8.0f}元 {us_tag}"
        )

        # 第二行：商品期货关联（仅对重仓有商品关联的股）
        if h.get("commodity"):
            comm_tag = format_commodity_display(h["commodity"])
            print(f"       └→ 商品背景: {comm_tag}")


def show_daily_picks_with_all_context():
    """
    日报选股：每只股附加美股 + 商品期货背景。
    """
    print("\n\n" + "=" * 90)
    print("📊 【盘前选股】- 今日优质池（综合参考）")
    print("=" * 90)

    picks = [
        {
            "code": "002110",
            "name": "盛屯矿业",
            "industry": "有色金属",
            "score": 8.8,
            "reason": "铜价低位、公司基本面强",
            "commodity": "copper",
        },
        {
            "code": "688008",
            "name": "澜起科技",
            "industry": "芯片",
            "score": 8.5,
            "reason": "箱体突破 + 量能确认",
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "industry": "新能源汽车",
            "score": 8.2,
            "reason": "MA5 上穿 MA20",
        },
    ]

    for i, pick in enumerate(picks, 1):
        if pick["score"] >= 8.5:
            prefix = "🟢"
        elif pick["score"] >= 7.8:
            prefix = "🟡"
        else:
            prefix = "🔵"

        # 第一行：基本信息 + 美股
        us_tag = format_us_context_inline(pick["code"], pick.get("industry", ""))
        print(
            f"{prefix} {i}. {pick['code']} {pick['name']:12} | "
            f"分数 {pick['score']:.1f} | {pick['reason']:20} {us_tag}"
        )

        # 第二行：商品期货关联
        if pick.get("commodity"):
            comm_tag = format_commodity_display(pick["commodity"])
            print(f"       └→ 商品: {comm_tag}")


def show_decision_support():
    """
    决策支持：买卖点时的多维参考。
    """
    print("\n\n" + "=" * 90)
    print("🎯 【决策支持】- 多维参考框架")
    print("=" * 90)

    decisions = [
        {
            "type": "买点",
            "code": "002110",
            "name": "盛屯矿业",
            "a_stock_signal": "支撑位放量",
            "us_context": "无直接对标",
            "commodity": "copper",
            "commodity_signal": "📉 铜价弱势",
            "verdict": "🟡 建议等待铜价反弹后再介入",
        },
        {
            "type": "买点",
            "code": "688008",
            "name": "澜起科技",
            "a_stock_signal": "MA 多头排列",
            "us_context": "✅ 美股强势",
            "commodity": None,
            "commodity_signal": None,
            "verdict": "✅ 建议介入",
        },
    ]

    for dec in decisions:
        print(f"\n  {dec['type']} | {dec['code']} {dec['name']:12}")
        print(f"    • A 股信号: {dec['a_stock_signal']}")
        if dec["us_context"]:
            print(f"    • 美股参考: {dec['us_context']}")
        if dec["commodity"]:
            print(f"    • 商品参考: {dec['commodity_signal']}")
        print(f"    ⟹ {dec['verdict']}")


def show_integration_summary():
    """显示集成摘要。"""
    print("\n\n" + "=" * 90)
    print("📝 【集成摘要】— 监控系统全景")
    print("=" * 90)

    summary = """
┌─ 美股背景 ────────────────────────┐
│ 纳指 QQQ↑ 芯片混合 科技强势       │
│ 用于参考: 光通信、新能源、科技股  │
└────────────────────────────────────┘

┌─ 商品期货 ────────────────────────┐
│ 铜价↓ 铁矿石↓ 原油↑ 黄金↓         │
│ 重点: 铜价弱势 → 盛屯矿业风险     │
└────────────────────────────────────┘

┌─ 重仓监控 ────────────────────────┐
│ 盛屯矿业(002110) — 铜产业链       │
│ 当前: 铜价↓-1.03% → 需要关注      │
└────────────────────────────────────┘

决策流程:
  1️⃣ 看美股背景 → 了解全球市场态势
  2️⃣ 看商品期货 → 了解上游原料价格
  3️⃣ 看 A 股本地 → 公司基本面和技术面
  4️⃣ 综合判断 → 买卖决策

特别关注:
  • 盛屯矿业与铜价的联动(高正相关)
  • 美股弱势+商品走低 → 风险叠加
  • 商品反弹+美股强 → 机会期
    """
    print(summary)


if __name__ == "__main__":
    # 完整的综合显示演示
    show_comprehensive_dashboard()
    show_watchlist_with_context()
    show_daily_picks_with_all_context()
    show_decision_support()
    show_integration_summary()

    print("\n" + "=" * 90)
    print("✅ 这是改造后的完整终端显示效果")
    print("=" * 90)
