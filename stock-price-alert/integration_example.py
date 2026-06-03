#!/usr/bin/env python3
"""
实时监控集成示例：
- 启动时显示美股背景
- 选股时附加美股参考
- 监控时用美股过滤
"""

from display_with_us_context import (
    show_us_context_banner,
    format_us_context_inline,
    format_us_context_full,
    filter_by_us_context,
)


def demo_daily_select():
    """日报选股展示示例。"""
    print("\n" + "=" * 80)
    print("📊 今日选股（日报）")
    print("=" * 80)

    # 显示美股背景横幅
    print(show_us_context_banner())

    # 模拟选股结果
    picks = [
        {"code": "688008", "name": "澜起科技", "industry": "芯片", "score": 8.5},
        {"code": "300750", "name": "宁德时代", "industry": "新能源汽车", "score": 8.2},
        {"code": "600522", "name": "中天科技", "industry": "光通信", "score": 8.0},
    ]

    print("\n【优质选股】")
    for pick in picks:
        us_inline = format_us_context_inline(pick["code"], pick["industry"])
        print(
            f"  {pick['code']} {pick['name']:12} 分数:{pick['score']:.1f} {us_inline}"
        )


def demo_watch_list():
    """监控列表显示示例。"""
    print("\n" + "=" * 80)
    print("👁️  持仓监控")
    print("=" * 80)

    holdings = [
        {"code": "688008", "name": "澜起科技", "industry": "芯片", "price": 150.0, "chg": -2.5},
        {"code": "300750", "name": "宁德时代", "industry": "新能源汽车", "price": 180.0, "chg": 3.2},
        {"code": "600000", "name": "浦发银行", "industry": "金融", "price": 15.5, "chg": 1.0},
    ]

    for h in holdings:
        # 检查是否满足美股过滤（示例：需要美股不全弱）
        us_filter_pass = filter_by_us_context(h["code"], h["industry"], require="not_weak")
        filter_icon = "✅" if us_filter_pass else "⚠️"

        # 显示行内美股信息
        us_inline = format_us_context_inline(h["code"], h["industry"])

        # 显示持仓
        chg_arrow = "📈" if h["chg"] > 0 else "📉"
        print(
            f"  {filter_icon} {h['code']} {h['name']:12} ${h['price']:8.2f} {chg_arrow}{h['chg']:+5.1f}% {us_inline}"
        )


def demo_detailed_analysis():
    """详细分析示例。"""
    print("\n" + "=" * 80)
    print("🔍 详细分析：澜起科技(688008)")
    print("=" * 80)

    print(format_us_context_full("688008", "芯片"))

    print("\n📋 建议：")
    print("  • NVDA 小幅下跌 -0.69%，但 TSM 和 ASML 都在涨")
    print("  • 这表示芯片链上游（设备、代工）仍强，下游芯片设计可能短期承压")
    print("  • 澜起作为芯片设计公司，关注 NVDA 动向是重要参考")


def demo_buy_filter():
    """买点过滤示例。"""
    print("\n" + "=" * 80)
    print("🎯 买点触发 —— 美股过滤")
    print("=" * 80)

    test_cases = [
        ("688008", "芯片", "strong", "🟢 美股强势，可考虑加仓"),
        ("688008", "芯片", "mixed", "🟡 美股混合，需谨慎"),
        ("688008", "芯片", "weak", "🔴 美股弱势，考虑减仓或观望"),
    ]

    for code, industry, require, message in test_cases:
        verdict = filter_by_us_context(code, industry, require=require)
        status = "通过 ✅" if verdict else "阻挡 ❌"
        print(f"  [{require:8}] {status} {message}")


def main():
    """展示所有集成场景。"""
    print("\n\n🌍 = = = = 美股集成到终端监控 = = = = 🌍\n")

    demo_daily_select()
    demo_watch_list()
    demo_detailed_analysis()
    demo_buy_filter()

    print("\n" + "=" * 80)
    print("💡 集成要点总结")
    print("=" * 80)
    print("""
1️⃣  日报开头：显示美股背景横幅（show_us_context_banner）
    → 快速了解全球市场态势

2️⃣  选股列表：每只股后附加美股参考（format_us_context_inline）
    → 在选股时即知道对标美股是否强势

3️⃣  详细分析：点击查看完整的美股背景分析（format_us_context_full）
    → 理解产业链上下游的全球动态

4️⃣  买卖过滤：在选股/买点前用美股过滤（filter_by_us_context）
    → 避免逆全球大趋势操作

5️⃣  自动化：在 strategy_engine 中集成
    → 如果美股弱势，自动降低信号权重或阻止买入
    """)


if __name__ == "__main__":
    main()
