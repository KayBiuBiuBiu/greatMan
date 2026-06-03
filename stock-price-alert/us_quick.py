#!/usr/bin/env python3
"""快速查询美股走势，辅助判断 A 股行业走向。"""

import sys
from quote_us_stocks import get_us_quote, get_us_kline


# 美股对标映射表
US_BENCHMARKS = {
    "qqq": {
        "symbol": "QQQ",
        "name": "纳斯达克 100",
        "cn_sectors": ["科技", "新能源", "互联网"],
        "desc": "美国科技/成长股指数 → 参考：光通信、芯片、新能源整体态势",
    },
    "spy": {
        "symbol": "SPY",
        "name": "标普 500",
        "cn_sectors": ["大市值", "消费", "金融"],
        "desc": "美国大盘 → 参考：消费、金融、龙头地产走向",
    },
    "sox": {
        "symbol": "SOX",
        "name": "费城半导体指数",
        "cn_sectors": ["芯片", "半导体"],
        "desc": "美国芯片 → A 股芯片、光通信强弱判断（必看）",
    },
    "nvda": {
        "symbol": "NVDA",
        "name": "英伟达",
        "cn_sectors": ["芯片"],
        "desc": "全球芯片龙头 → 判断科技股 AI 热度",
    },
    "asml": {
        "symbol": "ASML",
        "name": "阿斯麦",
        "cn_sectors": ["芯片设备"],
        "desc": "芯片制造设备龙头 → 芯片产业链判断",
    },
    "tsl": {
        "symbol": "TSM",
        "name": "台积电",
        "cn_sectors": ["芯片代工"],
        "desc": "全球最大芯片代工厂 → A 股芯片链强弱",
    },
    "xlv": {
        "symbol": "XLV",
        "name": "医疗健康",
        "cn_sectors": ["医药", "医疗"],
        "desc": "美国医疗板块 → A 股医药参考",
    },
    "xli": {
        "symbol": "XLI",
        "name": "工业",
        "cn_sectors": ["机械", "重工"],
        "desc": "美国工业 → A 股机械、重工参考",
    },
}


def format_quote(quote: dict) -> str:
    """格式化行情显示。"""
    if not quote:
        return "❌ 获取失败"

    price = quote["price"]
    change_pct = quote["change_pct"]
    arrow = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"

    pe = quote.get("pe_ratio")
    pe_str = f" | PE:{pe:.1f}" if pe else ""

    return f"{arrow} ${price:.2f} {change_pct:+.2f}%{pe_str}"


def show_benchmark(key: str) -> None:
    """显示单个美股对标。"""
    if key not in US_BENCHMARKS:
        print(f"❌ 未知指数: {key}")
        print(f"可用: {', '.join(sorted(US_BENCHMARKS.keys()))}")
        return

    info = US_BENCHMARKS[key]
    quote = get_us_quote(info["symbol"])

    print(f"\n{'='*70}")
    print(f"📊 {info['name']} ({info['symbol']})")
    print(f"{'='*70}")
    print(f"行情: {format_quote(quote)}")
    print(f"A 股参考: {', '.join(info['cn_sectors'])}")
    print(f"说明: {info['desc']}")
    print()


def show_all_benchmarks() -> None:
    """显示所有美股对标。"""
    print(f"\n{'='*70}")
    print("🌍 美股行业对标 —— 用于判断 A 股走向")
    print(f"{'='*70}\n")

    for key in sorted(US_BENCHMARKS.keys()):
        info = US_BENCHMARKS[key]
        quote = get_us_quote(info["symbol"])
        status = format_quote(quote)
        print(f"• {info['name']:20} ({info['symbol']:6}) → {status}")
        print(f"  参考: {', '.join(info['cn_sectors'])}")
        print()


def show_kline(symbol: str, period: str = "1mo") -> None:
    """显示 K 线。"""
    norm_sym = symbol.upper()
    kline = get_us_kline(norm_sym, period=period, interval="1d")

    if not kline:
        print(f"❌ 获取 {symbol} K 线失败")
        return

    print(f"\n{'='*70}")
    print(f"📈 {norm_sym} 近期 K 线 ({period})")
    print(f"{'='*70}\n")

    # 最多显示 10 条
    display_count = min(10, len(kline['dates']))
    for i in range(display_count):
        date = kline['dates'][i]
        close = kline['closes'][i]
        high = kline['highs'][i]
        low = kline['lows'][i]
        vol = kline['volumes'][i] / 1e6

        pct_change = ((close - kline['closes'][i+1]) / kline['closes'][i+1] * 100) if i+1 < len(kline['closes']) else 0
        arrow = "↑" if pct_change > 0 else "↓" if pct_change < 0 else "→"

        print(f"  {date} {arrow} 收${close:.2f} 高${high:.2f} 低${low:.2f} 量{vol:.1f}M")


def main():
    """主入口。"""
    if len(sys.argv) < 2:
        show_all_benchmarks()
        print("用法:")
        print("  python us_quick.py              # 显示所有对标")
        print("  python us_quick.py qqq          # 显示纳指")
        print("  python us_quick.py sox          # 显示芯片指数")
        print("  python us_quick.py NVDA kline  # 显示 NVDA K 线")
        return

    cmd = sys.argv[1].lower()

    if cmd == "all":
        show_all_benchmarks()
    elif len(sys.argv) > 2 and sys.argv[2].lower() == "kline":
        show_kline(cmd)
    else:
        show_benchmark(cmd)


if __name__ == "__main__":
    main()
