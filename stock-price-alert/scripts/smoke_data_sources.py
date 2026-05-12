#!/usr/bin/env python3
"""一次性冒烟：合并 config、上证 K、Tushare 探测、个股日 K。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_alert import merge_full_config
from utils import configure_ssl_from_sources

import macro_risk as mr
from quote_eastmoney import fetch_kline_rows_for_secid, resolve_ut, secid_for
from quote_tushare import (
    fetch_sh_index_hist_index_daily,
    sh_index_free_fallback_enabled,
    tushare_sh_index_primary,
)


def main() -> int:
    cfg_path = ROOT / "config.json"
    if not cfg_path.is_file():
        print("缺少 config.json")
        return 1
    cfg = merge_full_config(json.loads(cfg_path.read_text(encoding="utf-8")))
    configure_ssl_from_sources(cfg.get("sources"))

    with mr._INDEX_KLINE_LOCK:
        mr._index_bar_cache.clear()

    bars = mr._fetch_sh_index_closes_network()
    print(
        "tushare_primary",
        tushare_sh_index_primary(),
        "sh_index_free_fallback",
        sh_index_free_fallback_enabled(),
    )
    if bars:
        c, _v = bars
        print("上证 closes len", len(c), "last", round(c[-1], 4))
    else:
        print("上证 closes", None)

    tu_hist = fetch_sh_index_hist_index_daily(limit=30)
    print("Tushare index_daily(30)", "ok" if tu_hist else "fail/无权限")

    src = cfg.get("sources") or {}
    ut = resolve_ut(
        (src.get("quote_ut") or src.get("eastmoney_ut") or "ea")
        if isinstance(src, dict)
        else "ea"
    )
    rows = fetch_kline_rows_for_secid(secid_for("600000", "sh"), ut, lmt=40)
    print("个股 600000 日K行数", len(rows) if rows else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
