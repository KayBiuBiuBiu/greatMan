#!/usr/bin/env python3
"""
演示：如何在 run_alert.py 的终端显示中集成美股信息。
这是实际集成前的可视化效果展示。
"""

import sys
from display_with_us_context import show_us_context_banner, format_us_context_inline


def demo_terminal_display():
    """完整的终端显示模拟。"""

    # === 开始监控时的初始化显示 ===
    print("\n" + "=" * 90)
    print("🚀 股价监控启动 | 2026-06-03 09:30:00")
    print("=" * 90)

    print("\n📋 配置加载：15只标的 | 轮询 30s | 本金 528,166 元 | 最大仓位 50%")

    # 关键改造点 1：在这里显示美股背景横幅
    print("\n" + show_us_context_banner())

    print("\n" + "-" * 90)
    print("⏳ 等待盘前选股结果...")
    print("-" * 90)


    # === 盘前选股输出（改造后） ===
    print("\n\n📊 【盘前选股】- 今日优质池（量化选股结果）")
    print("=" * 90)

    # 改造点 2：在每只股旁附加美股标签
    picks = [
        {
            "code": "688008",
            "name": "澜起科技",
            "industry": "芯片",
            "score": 8.5,
            "reason": "箱体上边界突破 + 量能确认"
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "industry": "新能源汽车",
            "score": 8.2,
            "reason": "MA5 上穿 MA20 + 正向动量"
        },
        {
            "code": "600522",
            "name": "中天科技",
            "industry": "光通信",
            "score": 8.0,
            "reason": "低位放量 + 高位拦截区域"
        },
        {
            "code": "000651",
            "name": "格力电器",
            "industry": "消费",
            "score": 7.8,
            "reason": "近 5 日高点突破"
        },
    ]

    for i, pick in enumerate(picks, 1):
        us_inline = format_us_context_inline(pick["code"], pick["industry"])

        # 根据分数用不同颜色标记（ANSI 颜色代码）
        if pick["score"] >= 8.2:
            prefix = "🟢"
        elif pick["score"] >= 7.5:
            prefix = "🟡"
        else:
            prefix = "🔵"

        # 这是核心输出行 —— 加了美股标签
        print(f"{prefix} {i}. {pick['code']:6} {pick['name']:12} | "
              f"分数 {pick['score']:.1f} | {pick['reason']:20} {us_inline}")

    print("\n" + "=" * 90)
    print(f"✅ 共 {len(picks)} 只优质股 | 平均分 {sum(p['score'] for p in picks)/len(picks):.1f} | 美股态势已纳入参考")


    # === 盘中监控显示 ===
    print("\n\n" + "=" * 90)
    print("📡 【盘中监控】- 实时持仓跟踪（09:30 - 15:00）")
    print("=" * 90)

    holdings = [
        {
            "code": "688008",
            "name": "澜起科技",
            "industry": "芯片",
            "open_price": 155.0,
            "curr_price": 152.5,
            "chg_pct": -1.61,
            "hold_shares": 100,
        },
        {
            "code": "300750",
            "name": "宁德时代",
            "industry": "新能源汽车",
            "open_price": 175.0,
            "curr_price": 180.5,
            "chg_pct": 3.14,
            "hold_shares": 50,
        },
    ]

    # 模拟盘中行情
    print("\n⏰ 10:30:45 | 盘中快照")
    print("-" * 90)

    for h in holdings:
        us_inline = format_us_context_inline(h["code"], h["industry"])

        # 涨跌箭头
        arrow = "📈" if h["chg_pct"] > 0 else "📉" if h["chg_pct"] < 0 else "→"
        color_start = "\033[92m" if h["chg_pct"] > 0 else "\033[91m" if h["chg_pct"] < 0 else "\033[0m"
        color_end = "\033[0m"

        # 浮盈计算
        total_value = h["curr_price"] * h["hold_shares"]
        cost_value = h["open_price"] * h["hold_shares"]
        pnl = total_value - cost_value
        pnl_pct = (pnl / cost_value * 100) if cost_value else 0

        # 核心监控行 —— 附加美股参考
        print(
            f"  {h['code']} {h['name']:12} | 现价 ${h['curr_price']:7.2f} {arrow} {color_start}{h['chg_pct']:+6.2f}%{color_end} | "
            f"持仓 {h['hold_shares']:4}股 浮盈 {pnl:+8.0f}元({pnl_pct:+.2f}%) {us_inline}"
        )


    # === 买点触发示例 ===
    print("\n\n" + "=" * 90)
    print("🎯 【策略触发】- 买点/卖点信号")
    print("=" * 90)

    signals = [
        {
            "type": "买点",
            "code": "600522",
            "name": "中天科技",
            "industry": "光通信",
            "signal": "MA 均线多头排列",
            "us_status": "✅ 美股强势",
            "decision": "✅ 已纳入监控",
        },
        {
            "type": "卖点",
            "code": "688008",
            "name": "澜起科技",
            "industry": "芯片",
            "signal": "日线 MACD 死叉",
            "us_status": "⚠️  美股混合",
            "decision": "🟡 建议观望，不急减仓",
        },
    ]

    for sig in signals:
        print(f"\n  {sig['type']:3} | {sig['code']} {sig['name']:12} | "
              f"{sig['signal']:20} | 美股:{sig['us_status']} | 决策:{sig['decision']}")


    # === 底部状态栏 ===
    print("\n\n" + "-" * 90)
    print("📊 实时统计 | 持仓 2 只 | 浮盈 ≈-1,950 元 | 可用资金 ≈263,834 元 | "
          "美股态势:芯片混合 科技强势 新能源强势")
    print("-" * 90)

    print("\n⏳ 下次轮询: 30秒后 (10:31:15) ...\n")


def show_integration_points():
    """显示具体的改造位置。"""
    print("\n\n" + "=" * 90)
    print("🔧 改造实现细节")
    print("=" * 90)

    code_snippet = '''
┌─ 改造点 1: 启动时显示美股背景 ────────────────────────────────┐
│ 文件: run_alert.py 的 main() 函数                              │
│ 位置: 大约第 8600-8700 行（初始化后、轮询前）                  │
│                                                              │
│ from display_with_us_context import show_us_context_banner   │
│                                                              │
│ def main():                                                 │
│     # ... 加载配置等 ...                                      │
│     print(show_us_context_banner())  # ← 加这一行             │
│     # ... 开始轮询 ...                                        │
└────────────────────────────────────────────────────────────┘

┌─ 改造点 2: 选股结果附加美股标签 ────────────────────────────────┐
│ 文件: run_alert.py 或 quant_cli.py 的输出逻辑                  │
│                                                              │
│ from display_with_us_context import format_us_context_inline │
│                                                              │
│ for pick in quality_picks:                                  │
│     us_tag = format_us_context_inline(                       │
│         pick['code'],                                        │
│         pick.get('industry', '')                             │
│     )                                                        │
│     print(f"  {pick['code']} ... {pick['score']} {us_tag}") │
│                    ↑                              ↑          │
│              原有输出               新加的美股标签            │
└────────────────────────────────────────────────────────────┘

┌─ 改造点 3: 监控显示附加美股参考 ────────────────────────────────┐
│ 文件: run_alert.py 的 watch_pack 显示逻辑                      │
│ 位置: _emit_watch_line() 或类似的输出函数                      │
│                                                              │
│ for code in watchlist:                                      │
│     quote = get_quote(code)                                 │
│     us_info = format_us_context_inline(code, industry)      │
│     print(f"  {code} ${quote['price']} {us_info}")          │
│                                              ↑              │
│                                           新加美股信息        │
└────────────────────────────────────────────────────────────┘
    '''
    print(code_snippet)


def show_code_examples():
    """给出具体改造代码示例。"""
    print("\n\n" + "=" * 90)
    print("💻 具体改造代码示例")
    print("=" * 90)

    examples = '''
【改造 1: 启动时显示美股横幅】
────────────────────────────────────────────

# 在 run_alert.py 顶部导入
from display_with_us_context import show_us_context_banner

# 在 main() 函数里，大约第 8700 行：
def main() -> int:
    # ... 配置加载、参数解析等代码 ...

    # ↓↓↓ 加这三行 ↓↓↓
    if not args.quiet_trading_check:
        print(show_us_context_banner())
    # ↑↑↑ 加完了 ↑↑↑

    # ... 继续轮询 ...
    _realtime_hub_poll_loop(cfg, ...)


【改造 2: 选股列表加美股标签】
────────────────────────────────────────────

# 找到输出选股结果的地方（通常在 quant_cli.py 或 run_alert.py）
from display_with_us_context import format_us_context_inline

def output_quality_picks(picks):
    print("\\n【今日优质股】")
    for i, pick in enumerate(picks, 1):
        # ↓↓↓ 新加这行 ↓↓↓
        us_tag = format_us_context_inline(
            pick['code'],
            pick.get('industry', '')
        )
        # ↑↑↑ 新加完了 ↑↑↑

        # 原来的输出格式，加上 us_tag
        print(
            f"  {i}. {pick['code']:6} {pick['name']:12} | "
            f"分数 {pick['score']:.1f} {us_tag}"  # ← 加 us_tag
        )


【改造 3: 监控显示加美股参考】
────────────────────────────────────────────

# 在 watch_pack 循环里
from display_with_us_context import format_us_context_inline

for code in watch_codes:
    quote = get_live_quote(code)

    # ↓↓↓ 新加这行 ↓↓↓
    us_ref = format_us_context_inline(code, stock_industry.get(code, ''))
    # ↑↑↑ 新加完了 ↑↑↑

    # 输出时附加 us_ref
    rendered = (
        f"  {code} ${quote['price']:.2f} "
        f"{quote['chg_pct']:+.2f}% {us_ref}"  # ← 加上去
    )
    print(rendered)
    '''
    print(examples)


if __name__ == "__main__":
    # 显示完整的终端效果
    demo_terminal_display()

    # 显示改造细节
    show_integration_points()

    # 显示代码示例
    show_code_examples()

    print("\n" + "=" * 90)
    print("✅ 以上就是集成美股后的实际终端显示效果和改造方式")
    print("=" * 90)
