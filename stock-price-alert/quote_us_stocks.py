"""美股实时行情：yfinance + 缓存层。支持 NASDAQ、NYSE 等标的。"""

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

_us_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_us_quote_lock = threading.Lock()
_us_quote_cache_ttl_sec: float = 60.0


def set_us_quote_cache_ttl(ttl_sec: float) -> None:
    """设置美股行情缓存 TTL（秒）。"""
    global _us_quote_cache_ttl_sec
    _us_quote_cache_ttl_sec = max(0.0, float(ttl_sec))


def _normalize_us_symbol(symbol: str) -> str:
    """规范化美股代码：去 NASDAQ: 前缀，转大写。"""
    s = str(symbol).strip()
    if s.startswith("NASDAQ:"):
        s = s[7:]
    elif s.startswith("NYSE:"):
        s = s[5:]
    return s.upper()


def get_us_quote(symbol: str, *, cache_ttl_sec: float | None = None) -> dict[str, Any] | None:
    """
    获取美股实时行情。

    返回字典含：
      price: 当前价
      change: 涨跌额
      change_pct: 涨跌幅（%）
      timestamp: 获取时间（ISO）
      symbol: 规范化后的代码
      market_cap: 市值（可能为 None）
      pe_ratio: 市盈率（可能为 None）
    """
    if not YFINANCE_AVAILABLE:
        return None

    norm_sym = _normalize_us_symbol(symbol)
    if not norm_sym:
        return None

    ttl = cache_ttl_sec if cache_ttl_sec is not None else _us_quote_cache_ttl_sec
    now = time.time()

    if ttl > 0:
        with _us_quote_lock:
            cached = _us_quote_cache.get(norm_sym)
            if cached is not None:
                ts0, data = cached
                if now - ts0 < ttl:
                    return copy.deepcopy(data)

    try:
        ticker = yf.Ticker(norm_sym)
        info = ticker.info

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            return None

        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose", 0)
        change = price - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0

        result = {
            "symbol": norm_sym,
            "price": float(price),
            "change": float(change),
            "change_pct": float(change_pct),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "timestamp": datetime.now().isoformat(),
        }

        if ttl > 0:
            with _us_quote_lock:
                _us_quote_cache[norm_sym] = (now, copy.deepcopy(result))

        return result
    except Exception as e:
        print(f"Error fetching US quote for {norm_sym}: {e}")
        return None


def get_us_quotes_batch(symbols: list[str], *, cache_ttl_sec: float | None = None) -> dict[str, dict[str, Any] | None]:
    """批量获取美股行情。返回 {symbol: quote_dict or None}。"""
    result = {}
    for sym in symbols:
        result[sym] = get_us_quote(sym, cache_ttl_sec=cache_ttl_sec)
    return result


def get_us_kline(symbol: str, period: str = "1mo", interval: str = "1d") -> dict[str, Any] | None:
    """
    获取美股 K 线数据。

    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    interval: 1m, 5m, 15m, 30m, 60m, 1d, 1wk, 1mo

    返回：
      dates: 日期列表
      closes: 收盘价列表
      highs: 最高价列表
      lows: 最低价列表
      volumes: 成交量列表
    """
    if not YFINANCE_AVAILABLE:
        return None

    norm_sym = _normalize_us_symbol(symbol)
    if not norm_sym:
        return None

    try:
        ticker = yf.Ticker(norm_sym)
        hist = ticker.history(period=period, interval=interval)

        if hist.empty:
            return None

        return {
            "symbol": norm_sym,
            "dates": hist.index.strftime("%Y-%m-%d").tolist(),
            "closes": hist["Close"].tolist(),
            "highs": hist["High"].tolist(),
            "lows": hist["Low"].tolist(),
            "volumes": hist["Volume"].tolist(),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Error fetching US kline for {norm_sym}: {e}")
        return None


def clear_us_quote_cache() -> None:
    """清空美股行情缓存。"""
    with _us_quote_lock:
        _us_quote_cache.clear()
