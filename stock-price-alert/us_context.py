#!/usr/bin/env python3
"""
在日报生成或选股前展示美股走向。
可在 run_alert.py 的日报逻辑中调用 show_us_context()。
"""

from quote_us_stocks import get_us_quote


# 关键美股对标（针对 A 股不同行业）
KEY_US_BENCHMARKS = {
    "chip": {
        "name": "芯片/半导体",
        "symbols": ["NVDA", "TSM", "ASML"],
        "a_stock_examples": ["688004(二三四五)", "003000(中创新航)", "000651(格力电器)"],
    },
    "optical": {
        "name": "光通信",
        "symbols": ["QQQ"],  # 参考纳指整体
        "a_stock_examples": ["688008(澜起科技)", "600522(中天科技)", "300394(中手游)"],
    },
    "ev": {
        "name": "新能源/汽车",
        "symbols": ["QQQ", "TSLA"],
        "a_stock_examples": ["300750(宁德时代)", "600819(上海能源)"],
    },
    "tech": {
        "name": "科技/互联网",
        "symbols": ["QQQ"],
        "a_stock_examples": ["000858(五粮液)", "600000(浦发银行)"],
    },
}


def show_us_context():
    """显示美股背景，帮助理解 A 股走势。"""
    print("\n" + "="*80)
    print("🌍 美股背景 —— 用于判断 A 股今日走向")
    print("="*80)

    for category, info in KEY_US_BENCHMARKS.items():
        print(f"\n【{info['name']}】")

        all_strong = True
        all_weak = True

        for sym in info['symbols']:
            quote = get_us_quote(sym)
            if quote:
                change_pct = quote['change_pct']
                arrow = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"

                print(f"  {arrow} {sym:6} {change_pct:+6.2f}%", end="")

                if change_pct > 0:
                    all_weak = False
                elif change_pct < 0:
                    all_strong = False
                else:
                    all_weak = False
                    all_strong = False

                # 显示 PE 或市值参考
                if quote.get('pe_ratio'):
                    print(f"  | PE:{quote['pe_ratio']:6.1f}", end="")
                print()
            else:
                print(f"  ❌ {sym:6} 获取失败")
                all_strong = False
                all_weak = False

        # 汇总判断
        if all_strong:
            sentiment = "💪 强势 → A 股对应板块看涨"
        elif all_weak:
            sentiment = "😰 弱势 → A 股对应板块谨慎"
        else:
            sentiment = "😐 混合 → 择股要更谨慎"

        print(f"  {sentiment}")

    print("\n" + "="*80)


def us_context_for_buy_filter():
    """用于 A 股买点过滤的美股上下文判断。返回 bool: 是否适合买进。"""
    # 示例逻辑：只有纳指(QQQ)强势时，才买科技/新能源股
    qqq = get_us_quote("QQQ")
    nvda = get_us_quote("NVDA")

    if not qqq:
        return None  # 无法判断

    # QQQ 涨幅 > 0.5% 且 NVDA 不是大跌，认为美股科技态势好
    if qqq['change_pct'] > 0.5 and (not nvda or nvda['change_pct'] > -1.0):
        return True  # 适合买科技股

    if qqq['change_pct'] < -0.5:
        return False  # 不适合买科技股

    return None  # 不确定


if __name__ == "__main__":
    show_us_context()

    verdict = us_context_for_buy_filter()
    print(f"\n💡 建议: 科技股买点过滤 → {
        '✅ 美股态势好，可考虑' if verdict else
        '❌ 美股走弱，谨慎' if verdict is False else
        '❓ 不确定，可自主判断'
    }")
