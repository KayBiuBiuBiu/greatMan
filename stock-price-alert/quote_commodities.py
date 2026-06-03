"""大宗商品期货行情：伦敦铜、铁矿石等，免费数据源。"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timedelta
from typing import Any

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

_commodity_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_commodity_lock = threading.Lock()
_commodity_cache_ttl_sec: float = 60.0


def set_commodity_cache_ttl(ttl_sec: float) -> None:
    """设置商品期货缓存 TTL（秒）。"""
    global _commodity_cache_ttl_sec
    _commodity_cache_ttl_sec = max(0.0, float(ttl_sec))


# 大宗商品期货代码映射
COMMODITY_SYMBOLS = {
    "copper": {
        "symbol": "HG=F",  # COMEX 铜期货
        "name": "伦敦铜/COMEX 铜",
        "zh_name": "铜价",
        "unit": "美元/磅",
    },
    "iron_ore": {
        "symbol": "SI=F",  # NYMEX 铁矿石期货（备选：ZIO=F）
        "name": "铁矿石期货",
        "zh_name": "铁矿石",
        "unit": "美元/吨",
    },
    "crude_oil": {
        "symbol": "CL=F",  # WTI 原油期货
        "name": "WTI 原油",
        "zh_name": "原油",
        "unit": "美元/桶",
    },
    "gold": {
        "symbol": "GC=F",  # COMEX 黄金期货
        "name": "COMEX 黄金",
        "zh_name": "黄金",
        "unit": "美元/盎司",
    },
    "lme_copper": {
        "symbol": "COPPER=F",  # LME 铜（替代方案）
        "name": "LME 铜期货",
        "zh_name": "LME 铜",
        "unit": "美元/吨",
    },
}


def get_commodity_price(commodity: str, *, cache_ttl_sec: float | None = None) -> dict[str, Any] | None:
    """
    获取大宗商品期货实时价格。

    commodity: "copper"、"iron_ore"、"crude_oil"、"gold" 等

    返回字典含：
      price: 当前价
      change: 涨跌额
      change_pct: 涨跌幅（%）
      timestamp: 获取时间（ISO）
      symbol: 代码
      name: 名称
    """
    if not YFINANCE_AVAILABLE:
        return None

    if commodity not in COMMODITY_SYMBOLS:
        return None

    info = COMMODITY_SYMBOLS[commodity]
    symbol = info["symbol"]
    ttl = cache_ttl_sec if cache_ttl_sec is not None else _commodity_cache_ttl_sec
    now = time.time()

    # 检查缓存
    if ttl > 0:
        with _commodity_lock:
            cached = _commodity_cache.get(commodity)
            if cached is not None:
                ts0, data = cached
                if now - ts0 < ttl:
                    return copy.deepcopy(data)

    try:
        ticker = yf.Ticker(symbol)
        info_dict = ticker.info

        price = info_dict.get("currentPrice") or info_dict.get("regularMarketPrice")
        if price is None:
            return None

        prev_close = info_dict.get("previousClose") or info_dict.get("regularMarketPreviousClose", 0)
        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0

        result = {
            "commodity": commodity,
            "symbol": symbol,
            "name": info["name"],
            "zh_name": info["zh_name"],
            "unit": info["unit"],
            "price": float(price),
            "change": float(change),
            "change_pct": float(change_pct),
            "prev_close": float(prev_close),
            "timestamp": datetime.now().isoformat(),
        }

        # 保存到缓存
        if ttl > 0:
            with _commodity_lock:
                _commodity_cache[commodity] = (now, copy.deepcopy(result))

        return result
    except Exception as e:
        print(f"Error fetching {commodity}: {e}")
        return None


def get_commodity_prices_batch(commodities: list[str], *, cache_ttl_sec: float | None = None) -> dict[str, dict[str, Any] | None]:
    """批量获取商品期货价格。"""
    result = {}
    for comm in commodities:
        result[comm] = get_commodity_price(comm, cache_ttl_sec=cache_ttl_sec)
    return result


def get_copper_price(*, cache_ttl_sec: float | None = None) -> dict[str, Any] | None:
    """便捷函数：直接获取铜价。"""
    return get_commodity_price("copper", cache_ttl_sec=cache_ttl_sec)


def get_iron_ore_price(*, cache_ttl_sec: float | None = None) -> dict[str, Any] | None:
    """便捷函数：直接获取铁矿石价格。"""
    return get_commodity_price("iron_ore", cache_ttl_sec=cache_ttl_sec)


def clear_commodity_cache() -> None:
    """清空商品缓存。"""
    with _commodity_lock:
        _commodity_cache.clear()


if __name__ == "__main__":
    # 测试
    print("大宗商品期货行情测试\n")

    print("铜价：")
    copper = get_copper_price()
    if copper:
        print(f"  {copper['name']:20} {copper['price']:8.2f} {copper['change_pct']:+6.2f}%")
    else:
        print("  获取失败")

    print("\n铁矿石：")
    iron = get_iron_ore_price()
    if iron:
        print(f"  {iron['name']:20} {iron['price']:8.2f} {iron['change_pct']:+6.2f}%")
    else:
        print("  获取失败")

    print("\n批量获取：")
    prices = get_commodity_prices_batch(["copper", "crude_oil", "gold"])
    for comm, price in prices.items():
        if price:
            print(f"  {price['zh_name']:8} {price['price']:8.2f} {price['change_pct']:+6.2f}%")
