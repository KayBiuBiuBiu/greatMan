"""全市场 stock_basic 本地缓存（替代东财 clist）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REL_PATH = "data/stock_basic_cache.json"
_META_UPDATED = "_updated"
_META_SOURCE = "_source"


def default_cache_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parent
    return base / DEFAULT_REL_PATH


def load_stock_basic_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"stocks": [], _META_UPDATED: None, _META_SOURCE: None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"stocks": [], _META_UPDATED: None, _META_SOURCE: None}
    if not isinstance(raw, dict):
        return {"stocks": [], _META_UPDATED: None, _META_SOURCE: None}
    st = raw.get("stocks")
    if not isinstance(st, list):
        st = []
    return {
        "stocks": st,
        _META_UPDATED: raw.get(_META_UPDATED),
        _META_SOURCE: raw.get(_META_SOURCE) or "tushare_stock_basic",
    }


def cache_age_hours(path: Path) -> float | None:
    data = load_stock_basic_cache(path)
    s = data.get(_META_UPDATED)
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - t
        return max(0.0, delta.total_seconds() / 3600.0)
    except ValueError:
        return None


def refresh_stock_basic_cache_file(path: Path, *, pro: Any) -> int:
    """调用 Tushare stock_basic 全量写入 path；返回股票条数。"""
    df = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,area,industry,market,list_date,exchange",
    )
    if df is None or getattr(df, "empty", True):
        return 0
    stocks: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        stocks.append(
            {
                "ts_code": str(row.get("ts_code") or "").strip(),
                "symbol": str(row.get("symbol") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "area": str(row.get("area") or "").strip(),
                "industry": str(row.get("industry") or "").strip(),
                "market": str(row.get("market") or "").strip(),
                "list_date": str(row.get("list_date") or "").strip(),
                "exchange": str(row.get("exchange") or "").strip(),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        _META_UPDATED: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        _META_SOURCE: "tushare_stock_basic",
        "stocks": stocks,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(stocks)


def ensure_stock_basic_cache(
    path: Path,
    *,
    pro: Any,
    max_age_hours: float = 168.0,
) -> dict[str, Any]:
    """若缓存不存在或超过 max_age_hours，则刷新。"""
    age = cache_age_hours(path)
    if age is None or age > max_age_hours:
        refresh_stock_basic_cache_file(path, pro=pro)
    return load_stock_basic_cache(path)
