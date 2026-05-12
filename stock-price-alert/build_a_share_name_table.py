#!/usr/bin/env python3
"""
生成 / 更新「本地主表」a_share_names.json（代码→简称）。
数据来源：Tushare stock_basic，经 data/stock_basic_cache.json（与全市场扫描共用）。

用法:
  python build_a_share_name_table.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "a_share_names.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mapping_from_cache_stocks(stocks: list[Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in stocks:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip().zfill(6)
        name = str(row.get("name") or "").strip()
        if len(sym) == 6 and sym.isdigit() and name:
            out[sym] = name
    return out


def main() -> int:
    cfg_path = ROOT / "config.json"
    if cfg_path.is_file():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            from run_alert import merge_full_config
            from utils import configure_ssl_from_sources

            configure_ssl_from_sources(merge_full_config(raw).get("sources"))
        except Exception:
            pass

    from quote_tushare import (
        _get_pro,
        configure_tushare_from_sources,
        fetch_a_share_name_map_tushare,
        resolved_stock_basic_cache_path,
    )
    from stock_basic_cache import ensure_stock_basic_cache, load_stock_basic_cache

    if cfg_path.is_file():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            configure_tushare_from_sources((raw or {}).get("sources"))
        except Exception:
            configure_tushare_from_sources(None)

    mapping: dict[str, str] = {}
    source = "unknown"
    pro = _get_pro()
    cache_path = resolved_stock_basic_cache_path(ROOT)

    if pro is not None:
        try:
            ensure_stock_basic_cache(cache_path, pro=pro, max_age_hours=168.0)
            blob = load_stock_basic_cache(cache_path)
            stocks = blob.get("stocks") or []
            mapping = _mapping_from_cache_stocks(stocks if isinstance(stocks, list) else [])
            if mapping:
                source = "stock_basic_cache"
        except Exception as e:
            print(f"stock_basic 缓存：{e}", file=sys.stderr)

    if not mapping and pro is not None:
        try:
            print("正在直连 Tushare stock_basic…")
            tu = fetch_a_share_name_map_tushare()
            if tu:
                mapping = tu
                source = "tushare_stock_basic_direct"
        except Exception as e:
            print(f"Tushare：{e}", file=sys.stderr)

    if not mapping:
        blob = load_stock_basic_cache(cache_path)
        stocks = blob.get("stocks") or []
        mapping = _mapping_from_cache_stocks(stocks if isinstance(stocks, list) else [])
        if mapping:
            source = "stock_basic_cache_stale"

    if not mapping:
        print(
            "无可用数据。请配置 Tushare 并执行: python3 scripts/update_stock_basic_cache.py",
            file=sys.stderr,
        )
        return 1

    meta = {
        "_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_count": len(mapping),
        "_source": source,
    }
    payload = {**meta, **mapping}
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {len(mapping)} 条 -> {OUT}（来源 {source}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
