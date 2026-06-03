#!/usr/bin/env python3
"""
终端监控演示：每只股下面都加一条大白话的全球态势标签。
展示改造后的实际效果。
"""

from daily_sector_summary import format_stock_with_sector_summary


def show_watchlist_with_daily_summary():
    """
    显示监控列表，每只股下面加上"昨晚全球态势"标签。
    这是最直观的演示效果。
    """
    print("\n" + "=" * 90)
    print("👁️  【盘中监控】- 持仓实时跟踪 + 昨晚全球态势")
    print("=" * 90)

    holdings = [
        {
            "code": "002110",
            "name": "盛屯矿业",
            "sector": "有色金属",
            "price": 8.50,
            "chg": 1.2,
            "shares": 5000,
        },
        {
            "code": "688008",
            "name": "澜起科技",
            "sector": "芯片",
            "price": 152.50,
            "chg": -1.61,
            "shares": 100,
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "sector": "新能源汽车",
            "price": 180.50,
            "chg": 3.14,
            "shares": 50,
        },
        {
            "code": "600522",
            "name": "中天科技",
            "sector": "光通信",
            "price": 12.30,
            "chg": 2.5,
            "shares": 200,
        },
    ]

    for h in holdings:
        print(
            format_stock_with_sector_summary(
                h["code"],
                h["name"],
                h["sector"],
                h["price"],
                h["chg"],
                h["shares"],
            )
        )
        print()


def show_daily_picks_with_summary():
    """
    显示日报选股，每只股下面加上板块全球态势。
    """
    print("\n" + "=" * 90)
    print("📊 【盘前选股】- 今日优质池 + 昨晚全球背景")
    print("=" * 90)

    picks = [
        {
            "code": "002110",
            "name": "盛屯矿业",
            "sector": "有色金属",
            "score": 8.8,
            "price": 8.50,
            "chg": 1.2,
        },
        {
            "code": "688008",
            "name": "澜起科技",
            "sector": "芯片",
            "score": 8.5,
            "price": 152.50,
            "chg": -1.61,
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "sector": "新能源汽车",
            "score": 8.2,
            "price": 180.50,
            "chg": 3.14,
        },
    ]

    for i, pick in enumerate(picks, 1):
        if pick["score"] >= 8.5:
            prefix = "🟢"
        elif pick["score"] >= 8.0:
            prefix = "🟡"
        else:
            prefix = "🔵"

        # 第一行：基本信息
        print(
            f"{prefix} {i}. {pick['code']} {pick['name']:12} | "
            f"分数 {pick['score']:.1f}"
        )

        # 第二行：全球态势
        summary_line = format_stock_with_sector_summary(
            pick["code"],
            pick["name"],
            pick["sector"],
            pick["price"],
            pick["chg"],
        ).split("\n")[1]  # 只要第二行

        print("   " + summary_line)
        print()


def show_decision_framework():
    """
    显示决策框架：如何利用这个标签做决策。
    """
    print("\n" + "=" * 90)
    print("🎯 【如何利用这个标签做决策】")
    print("=" * 90)

    decisions = """
┌─ 情景 1: A 股涨，美股也涨，期货也涨 ─────────────┐
│ 持仓: 688008 澜起科技 📈+2% 美股芯片链↑ 💚很强   │
│ 决策: ✅ 加仓最好的时机，一切都在确认            │
└──────────────────────────────────────────────────┘

┌─ 情景 2: A 股涨，但美股不涨或期货跌 ────────────┐
│ 持仓: 002110 盛屯矿业 📈+1.2% 铜期↓-1% 💔很弱  │
│ 决策: 🟡 谨慎！虽然 A 股涨，但全球态势弱        │
│       → 先持仓观望，不急加仓                   │
│       → 如果明天美股和期货继续弱，准备减仓       │
└──────────────────────────────────────────────────┘

┌─ 情景 3: A 股跌，但美股涨，期货涨 ──────────────┐
│ 持仓: 300750 宁德时代 📉-0.5% 美股EV↑ 💚很强   │
│ 决策: 💚 全球态势很好 + 技术面好                │
│       → 这是底部布局的机会                      │
│       → 可考虑补仓或新进                        │
└──────────────────────────────────────────────────┘

┌─ 情景 4: A 股跌，美股也跌，期货也跌 ─────────────┐
│ 持仓: 600522 中天科技 📉-2% 美股弱 期货弱 💀   │
│ 决策: 🔴 三杀叠加 → 果断减仓                    │
│       → 等待底部确认再进场                      │
└──────────────────────────────────────────────────┘

═════════════════════════════════════════════════════

核心逻辑：
  ✅ A股涨 + 美股涨 + 期货涨     → 加仓（最强）
  🟡 A股涨 + 美股跌 or 期货跌   → 观望（有风险）
  🟡 A股跌 + 美股涨 + 期货涨    → 补仓（底部机会）
  🔴 A股跌 + 美股跌 + 期货跌    → 减仓（规避风险）

这条标签的作用就是：在买卖前，让你秒知道全球态势！
    """
    print(decisions)


def show_summary():
    """最后的总结。"""
    print("\n" + "=" * 90)
    print("✨ 这条标签的核心价值")
    print("=" * 90)

    summary = """
原来的显示：
  002110 盛屯矿业 $8.50 📈+1.20%
  → 只知道 A 股涨了，不知道全球怎样

现在的显示：
  002110 盛屯矿业 $8.50 📈+1.20%
       └→ 昨晚全球态势：📦 铜期↓-0.93% | 💔 偏弱，谨慎

用大白话告诉你：
  ✅ 这只股昨天 A 股涨了
  ✅ 但对应的商品（铜）在跌
  ✅ 整体态势是【偏弱】，建议【谨慎】

秒懂！一条标签解决所有问题！

════════════════════════════════════════════════════════════

让你能做出更聪明的决策：
  1️⃣  A 股数据（你已经看到了）
  2️⃣  美股对标态势（这条标签告诉你）
  3️⃣  商品期货走向（这条标签也告诉你）
  4️⃣  综合结论（这条标签直接说出来）

而不是要你分别查 5 个地方，然后自己综合判断！
    """
    print(summary)


if __name__ == "__main__":
    show_watchlist_with_daily_summary()
    show_daily_picks_with_summary()
    show_decision_framework()
    show_summary()

    print("\n" + "=" * 90)
    print("✅ 这就是改造后的实际效果")
    print("=" * 90)
