"""
为每只股票显示全球背景：对应美股 + 伦铜 + 综合判断。

这个模块整合了：
- daily_sector_summary.py 的板块映射逻辑
- quote_us_stocks.py 的美股实时行情
- quote_commodities.py 的伦铜期货行情

目标：在终端的每只股票旁显示一行简洁的全球态势。
示例输出：
  002110 盛屯矿业  | 现价 ¥8.50 📈+1.20%
    └→ 🌍 美股无对标 | 📦 Cu↑+1.5% | 💔 偏弱
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from quote_us_stocks import get_us_quote, get_us_quotes_batch
from quote_commodities import get_commodity_price
from daily_sector_summary import SECTOR_CONTEXT


# 股票代码 → 板块名称映射（从 data/stock_to_sw.json 加载）
# SW 代码 → 中文板块名称的映射
SW_CODE_TO_NAME = {
    "801010.SI": "农林牧渔",
    "801020.SI": "采矿业",
    "801030.SI": "食品饮料",
    "801040.SI": "有色金属",  # 盛屯矿业 002110
    "801050.SI": "木材家具",
    "801060.SI": "造纸",
    "801070.SI": "石油化工",
    "801080.SI": "化学制品",  # 澜起科技 688008
    "801090.SI": "医药生物",
    "801100.SI": "金属非金",
    "801110.SI": "机械设备",
    "801120.SI": "电气设备",
    "801130.SI": "电子",
    "801140.SI": "汽车",
    "801150.SI": "房地产",
    "801160.SI": "建筑装饰",
    "801170.SI": "建筑材料",
    "801180.SI": "基础化工",
    "801190.SI": "钢铁",
    "801200.SI": "有色金属",
    "801210.SI": "电力",
    "801220.SI": "煤炭",
    "801230.SI": "石油天然气",
    "801240.SI": "消费者服务",
    "801250.SI": "商业贸易",
    "801260.SI": "运输",
    "801270.SI": "电信服务",
    "801280.SI": "计算机",
    "801290.SI": "传媒",
    "801300.SI": "国防军工",
    "801310.SI": "综合",
    "801320.SI": "医疗保健",
    "801330.SI": "金融保险",
    "801340.SI": "房地产服务",
    "801350.SI": "能源",
    "801360.SI": "材料",
    "801370.SI": "工业",
    "801380.SI": "消费者周期",
    "801390.SI": "消费者防御",
    "801400.SI": "信息技术",
    "801410.SI": "通信",
    "801420.SI": "公用事业",
    # 新能源相关
    "801730.SI": "新能源汽车",  # 宁德时代 300750
    "801740.SI": "光学光电",
    "801750.SI": "汽车零部件",
    "801760.SI": "电池",
    "801770.SI": "新能源",
    "801780.SI": "新能源汽车",
    "801790.SI": "电动车",
    "801800.SI": "风电",
    "801810.SI": "光伏",
    "801820.SI": "储能",
    "801830.SI": "氢能",
    "801840.SI": "充电桩",
    "801850.SI": "新能源整车",
    "801860.SI": "车联网",
    "801870.SI": "智能驾驶",
    # 其他行业
    "801880.SI": "船舶",
    "801890.SI": "飞机",
    "801900.SI": "航天",
    "801910.SI": "铁路",
    "801920.SI": "公路",
    "801930.SI": "港口",
    "801940.SI": "机场",
    "801950.SI": "物流",
    "801960.SI": "仓储",
    "801970.SI": "快递",
    "801980.SI": "环保",
    "801990.SI": "水处理",
    "801A00.SI": "固废处理",
    "801A10.SI": "污水处理",
    "801A20.SI": "环卫",
    "801A30.SI": "节能",
    "801A40.SI": "环境监测",
    "801A50.SI": "生态保护",
    # 行业代码
    "800000.SI": "所有行业",
}

# 映射板块名称到 SECTOR_CONTEXT 中的键
SECTOR_NAME_MAPPING = {
    # 直接映射（已在 SECTOR_CONTEXT 中定义）
    "芯片": "芯片",
    "半导体": "半导体",
    "光通信": "光通信",
    "新能源": "新能源",
    "新能源汽车": "新能源汽车",
    "有色金属": "有色金属",
    "消费": "消费",
    "医药": "医药",
    "金融": "金融",
    # 间接映射
    "电子": "芯片",
    "化学制品": "新能源",  # 澜起科技 688008 归类为化学制品，但更接近芯片
    "电气设备": "新能源",
    "消费电子": "新能源汽车",
    "汽车": "新能源汽车",
    "食品饮料": "消费",
    "金融保险": "金融",
    "医药生物": "医药",
    "采矿业": "有色金属",
    # 其他通用映射
    "建筑装饰": "消费",
    "建筑材料": "消费",
    "环保": "消费",
}

_STOCK_TO_SW_CACHE: dict[str, str] = {}


def _load_stock_to_sw_mapping() -> dict[str, str]:
    """从 data/stock_to_sw.json 加载股票到 SW 代码的映射。"""
    global _STOCK_TO_SW_CACHE
    if _STOCK_TO_SW_CACHE:
        return _STOCK_TO_SW_CACHE

    try:
        root = Path(__file__).resolve().parent
        sw_file = root / "data" / "stock_to_sw.json"
        if sw_file.exists():
            with open(sw_file) as f:
                data = json.load(f)
                _STOCK_TO_SW_CACHE = data.get("by_code", {})
    except Exception:
        pass

    return _STOCK_TO_SW_CACHE


def get_sector_for_stock(code: str) -> str | None:
    """
    获取某只股票所属的板块（中文名称）。

    返回值可以直接用于 SECTOR_CONTEXT 字典查询。
    """
    # 从 stock_to_sw.json 获取 SW 代码
    sw_mapping = _load_stock_to_sw_mapping()
    sw_code = sw_mapping.get(code)

    if not sw_code:
        return None

    # 从 SW 代码获取中文板块名称
    sw_name = SW_CODE_TO_NAME.get(sw_code)
    if not sw_name:
        return None

    # 尝试映射到 SECTOR_CONTEXT 中的键
    # 如果直接存在，返回；否则返回 SW 名称
    if sw_name in SECTOR_CONTEXT:
        return sw_name

    return SECTOR_NAME_MAPPING.get(sw_name, sw_name)


def get_stock_global_context(
    code: str, name: str = "", sector: str = ""
) -> dict[str, Any] | None:
    """
    获取某只股票的全球背景：美股 + 伦铜 + 综合判断。

    返回字典含：
      us_info: 美股信息 (symbols_data, direction, change_pct, description)
      commodity_info: 伦铜信息 (price, change_pct, zh_name)
      verdict: 综合判断 (text, emoji, strength)
      display_line: 格式化的一行展示
    """
    # 如果没有提供板块，尝试从代码推断
    if not sector:
        sector = get_sector_for_stock(code)

    # 查找板块配置
    sector_info = None
    if sector:
        sector_info = SECTOR_CONTEXT.get(sector)

    if not sector_info:
        return None

    result = {
        "code": code,
        "name": name,
        "sector": sector,
        "us_info": None,
        "commodity_info": None,
        "verdict": None,
        "display_line": "",
    }

    # 获取美股信息
    us_info = _fetch_us_context(sector_info)
    if us_info:
        result["us_info"] = us_info

    # 获取期货信息
    commodity_info = _fetch_commodity_context(sector_info)
    if commodity_info:
        result["commodity_info"] = commodity_info

    # 综合判断
    verdict = _compute_verdict(us_info, commodity_info)
    result["verdict"] = verdict

    # 生成显示行
    result["display_line"] = _format_display_line(us_info, commodity_info, verdict)

    return result


def _fetch_us_context(sector_info: dict[str, Any]) -> dict[str, Any] | None:
    """获取美股背景信息。"""
    us_stocks = sector_info.get("us_stocks", [])
    if not us_stocks:
        return None

    us_prices = {}
    for sym in us_stocks:
        q = get_us_quote(sym)
        if q:
            us_prices[sym] = q["change_pct"]

    if not us_prices:
        return None

    avg_pct = sum(us_prices.values()) / len(us_prices)
    direction = "↑" if avg_pct > 0 else "↓" if avg_pct < 0 else "→"

    return {
        "symbols": us_stocks,
        "symbols_data": us_prices,
        "avg_pct": avg_pct,
        "direction": direction,
        "description": sector_info.get("us_desc", ""),
    }


def _fetch_commodity_context(sector_info: dict[str, Any]) -> dict[str, Any] | None:
    """获取商品期货背景信息。"""
    commodities = sector_info.get("commodities", [])
    if not commodities:
        return None

    # 这里只处理 "copper"，其他商品类似
    if "copper" not in commodities:
        return None

    copper = get_commodity_price("copper")
    if not copper:
        return None

    return {
        "commodity": "copper",
        "price": copper["price"],
        "change_pct": copper["change_pct"],
        "zh_name": "伦铜",
        "direction": "↑" if copper["change_pct"] > 0 else "↓" if copper["change_pct"] < 0 else "→",
    }


def _compute_verdict(
    us_info: dict[str, Any] | None,
    commodity_info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """综合美股和伦铜信息，判断整体态势。"""
    if not us_info and not commodity_info:
        return None

    all_pcts = []
    if us_info:
        all_pcts.append(us_info["avg_pct"])
    if commodity_info:
        all_pcts.append(commodity_info["change_pct"])

    if not all_pcts:
        return None

    avg = sum(all_pcts) / len(all_pcts)

    if avg > 1.0:
        verdict_text = "很强势，加仓"
        emoji = "💚"
        strength = "strong"
    elif avg > 0.2:
        verdict_text = "偏强，可入"
        emoji = "💙"
        strength = "bullish"
    elif avg > -0.2:
        verdict_text = "混合，观望"
        emoji = "💛"
        strength = "neutral"
    elif avg > -1.0:
        verdict_text = "偏弱，谨慎"
        emoji = "💔"
        strength = "bearish"
    else:
        verdict_text = "很弱势，减仓"
        emoji = "💀"
        strength = "very_bearish"

    return {
        "text": verdict_text,
        "emoji": emoji,
        "strength": strength,
        "avg_pct": avg,
    }


def _format_display_line(
    us_info: dict[str, Any] | None,
    commodity_info: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
) -> str:
    """格式化为一行展示。"""
    parts = []

    if us_info:
        desc = us_info.get("description", "")
        arrow = us_info["direction"]
        pct = us_info["avg_pct"]
        parts.append(f"🌍 美股{desc}{arrow}{pct:+.2f}%")
    else:
        parts.append("🌍 美股无对标")

    if commodity_info:
        arrow = commodity_info["direction"]
        pct = commodity_info["change_pct"]
        parts.append(f"📦 伦铜{arrow}{pct:+.2f}%")

    if verdict:
        emoji = verdict["emoji"]
        text = verdict["text"]
        parts.append(f"{emoji} {text}")

    return " | ".join(parts) if parts else ""


def format_stock_with_global_context(
    code: str,
    name: str,
    price: float,
    chg_pct: float,
    sector: str = "",
    shares: int = 0,
) -> str:
    """
    格式化单只股的显示，加上全球背景。

    返回格式：
      002110 盛屯矿业  | 现价 ¥8.50 📈+1.20%
        └→ 🌍 美股无对标 | 📦 伦铜↑+1.5% | 💔 偏弱

    或单行格式（如需要）。
    """
    # 第一行：基本信息
    if chg_pct > 0:
        chg_arrow = "📈"
    elif chg_pct < 0:
        chg_arrow = "📉"
    else:
        chg_arrow = "→"

    line1 = f"  {code} {name:12} | 现价 ¥{price:7.2f} {chg_arrow}{chg_pct:+6.2f}%"

    if shares > 0:
        line1 += f" | 持仓 {shares:6}股"

    # 第二行：全球背景
    ctx = get_stock_global_context(code, name, sector)
    if ctx and ctx["display_line"]:
        line2 = f"       └→ {ctx['display_line']}"
    else:
        line2 = ""

    return line1 + ("\n" + line2 if line2 else "")


def format_stock_with_global_context_compact(
    code: str,
    name: str,
    price: float,
    chg_pct: float,
    sector: str = "",
) -> str:
    """
    紧凑一行格式（用于列表显示）。

    返回格式：
      002110 盛屯矿业 | ¥8.50 📈+1.20% | 🌍 Cu↑+1.5% | 💔
    """
    if chg_pct > 0:
        chg_arrow = "📈"
    elif chg_pct < 0:
        chg_arrow = "📉"
    else:
        chg_arrow = "→"

    line = f"{code} {name:8} | ¥{price:7.2f} {chg_arrow}{chg_pct:+6.2f}%"

    ctx = get_stock_global_context(code, name, sector)
    if ctx and ctx["display_line"]:
        line += f" | {ctx['display_line']}"

    return line


if __name__ == "__main__":
    # 测试
    print("=" * 100)
    print("【全球背景显示测试】")
    print("=" * 100)

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
    ]

    print("\n【详细格式】")
    for tc in test_cases:
        print(
            format_stock_with_global_context(
                tc["code"],
                tc["name"],
                tc["price"],
                tc["chg_pct"],
                tc["sector"],
                tc["shares"],
            )
        )
        print()

    print("\n【紧凑格式】")
    for tc in test_cases:
        print(
            format_stock_with_global_context_compact(
                tc["code"],
                tc["name"],
                tc["price"],
                tc["chg_pct"],
                tc["sector"],
            )
        )
