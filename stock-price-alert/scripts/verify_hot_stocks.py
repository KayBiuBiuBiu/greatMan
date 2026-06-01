#!/usr/bin/env python3
"""手动验证同花顺热股榜 ths_hot 接口与本地 hot_stock_cache。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="验证热股榜 fetch_hot_stocks / 缓存")
    parser.add_argument("-c", "--config", default=str(ROOT / "config.json"))
    parser.add_argument("--trade-date", default="", help="YYYYMMDD，默认今天")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="仅读本地缓存，不调 Tushare",
    )
    args = parser.parse_args()

    from run_alert import merge_full_config
    from quote_tushare import (
        _ths_hot_preferred_is_new,
        configure_tushare_from_sources,
        fetch_hot_stocks,
        fetch_hot_stocks_ranked,
        is_hot_stock,
        read_hot_stock_cache_meta,
    )
    from utils import configure_ssl_from_sources

    cfg_path = Path(args.config)
    cfg = merge_full_config(json.loads(cfg_path.read_text(encoding="utf-8")))
    configure_ssl_from_sources(cfg.get("sources"))
    configure_tushare_from_sources(cfg.get("sources"))

    td = str(args.trade_date or "").strip() or None
    prefer = _ths_hot_preferred_is_new()
    print(f"当前建议 is_new={prefer!r}（22:30 前为 N，之后为 Y）")
    print(f"模式: {'仅缓存' if args.cache_only else '强制刷新 API'}")

    if args.cache_only:
        codes = fetch_hot_stocks(trade_date=td, cache_only=True, top_n=args.top_n)
    else:
        codes = fetch_hot_stocks(
            trade_date=td, cache_only=False, top_n=args.top_n, force_refresh=True
        )

    meta = read_hot_stock_cache_meta()
    ranked = fetch_hot_stocks_ranked(trade_date=td, cache_only=True, top_n=args.top_n)

    print("\n--- hot_stock_cache 元数据 ---")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n--- 热股前 {args.top_n}（代码）---")
    for i, c in enumerate(codes, 1):
        print(f"  {i:2d}. {c}")
    print("\n--- 带排名 ---")
    for code, rank in ranked:
        print(f"  #{rank} {code}")

    if codes:
        sample = codes[0]
        print(f"\n样本 {sample} is_hot_stock(cache_only) = {is_hot_stock(sample, cache_only=True)}")
    else:
        print(
            "\n⚠️ 未获取到热股数据。"
            "盘中请确认 ths_hot(..., market='热股', is_new='N')；"
            "22:30 前 is_new='Y' 常为空。"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
