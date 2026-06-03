"""
终端集成：在股票显示中加入美股背景信息。
- 日报选股时显示相关美股走势
- 监控显示时附加美股参考信息
- 可作为买点/卖点的确认过滤
"""

from __future__ import annotations

from typing import Any
from quote_us_stocks import get_us_quote, get_us_kline


# 映射 A 股行业代码到美股标的
INDUSTRY_TO_US = {
    "光通信": ["QQQ"],
    "芯片": ["NVDA", "TSM", "ASML"],
    "半导体": ["NVDA", "TSM", "ASML"],
    "新能源": ["QQQ", "TSLA"],
    "新能源汽车": ["TSLA", "QQQ"],
    "新能源车": ["TSLA", "QQQ"],
    "消费": ["SPY"],
    "医药": ["XLV"],
    "医疗": ["XLV"],
    "金融": ["SPY"],
    "机械": ["XLI"],
    "工业": ["XLI"],
}

# 股票代码到行业的简易映射（可根据实际调整）
CODE_TO_INDUSTRY = {
    "600522": "光通信",  # 中天科技
    "688008": "芯片",    # 澜起科技
    "000651": "消费",    # 格力电器
    "300750": "新能源汽车",  # 宁德时代
    "600000": "金融",    # 浦发银行
}


def get_us_context_for_stock(code: str, industry: str = "") -> dict[str, Any] | None:
    """
    获取某只 A 股对应的美股背景信息。

    返回：
      us_symbols: 对标美股列表
      us_quotes: {symbol: quote} 的美股行情
      sentiment: 总体判断（strong/weak/mixed）
      explanation: 文字说明
    """
    # 从代码或行业推断
    inferred_industry = CODE_TO_INDUSTRY.get(code) or industry or ""

    us_symbols = INDUSTRY_TO_US.get(inferred_industry, [])
    if not us_symbols:
        return None

    us_quotes = {}
    strong_count = 0
    weak_count = 0

    for sym in us_symbols:
        q = get_us_quote(sym)
        if q:
            us_quotes[sym] = q
            if q["change_pct"] > 0.5:
                strong_count += 1
            elif q["change_pct"] < -0.5:
                weak_count += 1

    if not us_quotes:
        return None

    # 判断整体态势
    total = len(us_quotes)
    if strong_count >= total * 0.7:
        sentiment = "strong"
    elif weak_count >= total * 0.7:
        sentiment = "weak"
    else:
        sentiment = "mixed"

    return {
        "industry": inferred_industry,
        "us_symbols": us_symbols,
        "us_quotes": us_quotes,
        "sentiment": sentiment,
        "strong_count": strong_count,
        "weak_count": weak_count,
        "total": total,
    }


def format_us_context_inline(code: str, industry: str = "") -> str:
    """
    生成行内 US 背景显示（用于股票列表）。

    示例输出：
      "[美股 QQQ↑+0.46% TSM↑+2.54%]"
      "[美股 NVDA↓-0.69%]"
    """
    ctx = get_us_context_for_stock(code, industry)
    if not ctx or not ctx["us_quotes"]:
        return ""

    parts = []
    for sym, quote in ctx["us_quotes"].items():
        arrow = "↑" if quote["change_pct"] > 0 else "↓" if quote["change_pct"] < 0 else "→"
        parts.append(f"{sym}{arrow}{quote['change_pct']:+.2f}%")

    return f"[美股 {' '.join(parts)}]"


def format_us_context_full(code: str, industry: str = "") -> str:
    """
    生成完整 US 背景显示（用于详细分析）。

    示例输出:
    🌍 美股背景（芯片产业链）:
      NVDA $222.82 -0.69% | PE:34.1
      TSM  $446.69 +2.54% | PE:38.2
      ASML $1705.37 +4.72% | PE:56.5
      → 判断：混合，需谨慎选择
    """
    ctx = get_us_context_for_stock(code, industry)
    if not ctx or not ctx["us_quotes"]:
        return ""

    lines = [f"\n🌍 美股背景（{ctx['industry']}产业链）:"]

    for sym, quote in ctx["us_quotes"].items():
        arrow = "📈" if quote["change_pct"] > 0 else "📉" if quote["change_pct"] < 0 else "→"
        pe_str = ""
        if quote.get("pe_ratio"):
            pe_str = f" | PE:{quote['pe_ratio']:.1f}"
        lines.append(
            f"  {arrow} {sym:6} ${quote['price']:8.2f} {quote['change_pct']:+6.2f}%{pe_str}"
        )

    # 添加判断
    sentiment_msg = {
        "strong": "💪 强势 → A 股对应板块看涨信号",
        "weak": "😰 弱势 → A 股对应板块谨慎信号",
        "mixed": "😐 混合 → 需结合 A 股本地面结合 A 股本地面判断",
    }
    lines.append(f"  {sentiment_msg.get(ctx['sentiment'], '?')}")

    return "\n".join(lines)


def filter_by_us_context(code: str, industry: str = "", require: str = "any") -> bool:
    """
    用美股背景作为买卖过滤。

    require:
      "any" — 任意美股存在（默认，几乎总是通过）
      "strong" — 美股总体强势
      "not_weak" — 美股不全弱
    """
    ctx = get_us_context_for_stock(code, industry)
    if not ctx:
        return True  # 无美股对标，不过滤

    if require == "any":
        return len(ctx["us_quotes"]) > 0
    elif require == "strong":
        return ctx["sentiment"] == "strong"
    elif require == "not_weak":
        return ctx["sentiment"] != "weak"

    return True


def show_us_context_banner(industry: str = "") -> str:
    """
    生成行业级别的美股背景横幅（用于日报开头）。

    示例输出:
    ┌─ 🌍 美股背景概览 ────────────────────────────────┐
    │ 芯片:     NVDA↓-0.69%  TSM↑+2.54%  ASML↑+4.72% 😐混合
    │ 科技:     QQQ↑+0.46%                            💪强势
    │ 新能源:   TSLA↑+1.89%  QQQ↑+0.46%              💪强势
    └──────────────────────────────────────────────────┘
    """
    # 重点行业
    industries = ["芯片", "科技", "新能源", "消费", "医药"]

    lines = ["┌─ 🌍 美股背景概览 " + "─" * 40 + "┐"]

    for ind in industries:
        ctx = get_us_context_for_stock("", ind)
        if ctx and ctx["us_quotes"]:
            parts = []
            for sym, quote in ctx["us_quotes"].items():
                arrow = "↑" if quote["change_pct"] > 0 else "↓"
                parts.append(f"{sym}{arrow}{quote['change_pct']:+.2f}%")

            sentiment_emoji = {
                "strong": "💪强势",
                "weak": "😰弱势",
                "mixed": "😐混合",
            }[ctx["sentiment"]]

            line = f"│ {ind:8} {' '.join(parts):30} {sentiment_emoji:8}"
            lines.append(line)

    lines.append("└" + "─" * 51 + "┘")
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("测试 1: 行内显示")
    print("=" * 60)
    print(f"688008(澜起科技): {format_us_context_inline('688008', '芯片')}")
    print(f"300750(宁德时代): {format_us_context_inline('300750', '新能源汽车')}")

    print("\n" + "=" * 60)
    print("测试 2: 完整显示")
    print("=" * 60)
    print(format_us_context_full("688008", "芯片"))

    print("\n" + "=" * 60)
    print("测试 3: 美股背景横幅")
    print("=" * 60)
    print(show_us_context_banner())

    print("\n" + "=" * 60)
    print("测试 4: 过滤逻辑")
    print("=" * 60)
    print(f"芯片股不过滤: {filter_by_us_context('688008', '芯片', require='any')}")
    print(f"芯片股需强势: {filter_by_us_context('688008', '芯片', require='strong')}")
