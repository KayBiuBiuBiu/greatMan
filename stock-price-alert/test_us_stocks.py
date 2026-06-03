#!/usr/bin/env python3
"""测试美股行情模块。"""

from quote_us_stocks import get_us_quote, get_us_quotes_batch, get_us_kline

def test_single_quote():
    """测试单个美股行情。"""
    print("=" * 60)
    print("测试 1: 单个美股行情")
    print("=" * 60)

    symbols = ["QQQ", "SOX", "NVDA", "TSLA"]
    for sym in symbols:
        quote = get_us_quote(sym)
        if quote:
            print(f"\n{sym}:")
            print(f"  价格: ${quote['price']:.2f}")
            print(f"  涨跌: {quote['change_pct']:.2f}%")
            print(f"  市值: {quote.get('market_cap', 'N/A')}")
            print(f"  PE: {quote.get('pe_ratio', 'N/A')}")
        else:
            print(f"\n{sym}: 获取失败")


def test_batch_quotes():
    """测试批量获取。"""
    print("\n" + "=" * 60)
    print("测试 2: 批量获取美股行情")
    print("=" * 60)

    us_symbols = ["QQQ", "SPY", "IWM", "VTI"]
    results = get_us_quotes_batch(us_symbols)

    for sym, quote in results.items():
        if quote:
            print(f"{sym}: ${quote['price']:.2f} ({quote['change_pct']:+.2f}%)")
        else:
            print(f"{sym}: 获取失败")


def test_kline():
    """测试 K 线数据。"""
    print("\n" + "=" * 60)
    print("测试 3: 美股 K 线（最近 5 个交易日）")
    print("=" * 60)

    kline = get_us_kline("QQQ", period="1mo", interval="1d")
    if kline:
        print(f"\n{kline['symbol']} 最近 K 线:")
        for i in range(min(5, len(kline['dates']))):
            date = kline['dates'][i]
            close = kline['closes'][i]
            high = kline['highs'][i]
            low = kline['lows'][i]
            vol = kline['volumes'][i]
            print(f"  {date}: 收{close:.2f} 高{high:.2f} 低{low:.2f} 量{vol/1e6:.1f}M")
    else:
        print("获取失败")


def test_comparison():
    """对比美股与 A 股特定行业的关联性（演示）。"""
    print("\n" + "=" * 60)
    print("测试 4: 美股对标指数与 A 股行业参考")
    print("=" * 60)

    us_benchmark = {
        "QQQ": "纳斯达克 100（科技/新能源参考）",
        "SOX": "费城半导体指数（芯片对标）",
        "XLV": "医疗健康（医药参考）",
        "XLI": "工业（机械/重工参考）",
    }

    print("\n美股走势概览（用于判断 A 股对应行业）：\n")
    for sym, desc in us_benchmark.items():
        quote = get_us_quote(sym)
        if quote:
            status = "↑" if quote['change_pct'] > 0 else "↓"
            print(f"{status} {sym:6} {desc:20} {quote['change_pct']:+6.2f}%")
        else:
            print(f"  {sym:6} {desc:20} 获取失败")


if __name__ == "__main__":
    test_single_quote()
    test_batch_quotes()
    test_kline()
    test_comparison()
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
