#!/usr/bin/env python3
"""刷新 data/stock_to_sw.json（申万一级：股票代码 → 801xxx.SI）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    cfg_path = ROOT / "config.json"
    if not cfg_path.is_file():
        print("缺少 config.json", file=sys.stderr)
        return 1
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    from run_alert import merge_full_config
    from utils import configure_ssl_from_sources

    cfg = merge_full_config(raw)
    configure_ssl_from_sources(cfg.get("sources"))
    from quote_tushare import _get_pro, configure_tushare_from_sources, resolved_stock_to_sw_path
    from sw_member_cache import refresh_stock_to_sw_cache

    configure_tushare_from_sources(cfg.get("sources"))
    pro = _get_pro()
    if pro is None:
        print("请启用 sources.tushare 并配置 token", file=sys.stderr)
        return 1
    path = resolved_stock_to_sw_path(ROOT)
    n = refresh_stock_to_sw_cache(path, pro=pro)
    print(f"已写入 {n} 条映射 -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
