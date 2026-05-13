#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性修正 watchlist 中指定代码的持股与加权成本（不跑监控逻辑）。

典型场景：历史上多次 buy/hold 被错误覆盖后，手工对齐为正确总股数与均价。

默认修正盛屯矿业 600711：
  8600 × 13.2864 + 12300 × 13.2073 → 20900 股，加权成本约 13.239848

用法:
  cd stock-price-alert
  python3 scripts/fix_watchlist_weighted_hold.py -c config.json
  python3 scripts/fix_watchlist_weighted_hold.py -c config.json --code 000537 --shares 1000 --cost 10.5

也可在终端用（会走合并逻辑）:
  hold 600711 20900 13.239848
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_alert import normalize_stock_code, save_config_atomic  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="修正 watchlist 单标的股数与成本价")
    ap.add_argument(
        "-c",
        "--config",
        type=Path,
        default=ROOT / "config.json",
        help="config.json 路径",
    )
    ap.add_argument("--code", type=str, default="600711", help="六位股票代码")
    ap.add_argument(
        "--shares",
        type=int,
        default=20900,
        help="修正后的总持股（默认 8600+12300）",
    )
    ap.add_argument(
        "--cost",
        type=float,
        default=None,
        help="修正后的加权成本；默认按 8600@13.2864 + 12300@13.2073 计算",
    )
    args = ap.parse_args()
    code = normalize_stock_code(args.code.strip())
    if not code:
        print("代码无效", file=sys.stderr)
        return 1
    cfg_path = args.config.resolve()
    if not cfg_path.is_file():
        print(f"找不到配置文件: {cfg_path}", file=sys.stderr)
        return 1
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    wl = raw.get("watchlist")
    if not isinstance(wl, list):
        print("watchlist 不是列表", file=sys.stderr)
        return 1
    cost = args.cost
    if cost is None and code == "600711" and int(args.shares) == 20900:
        cost = (8600 * 13.2864 + 12300 * 13.2073) / 20900.0
    if cost is None or cost <= 0:
        print("请提供 --cost > 0，或使用默认 600711/20900 组合", file=sys.stderr)
        return 1
    cost_r = round(float(cost), 6)
    found = False
    for w in wl:
        if not isinstance(w, dict):
            continue
        if normalize_stock_code(str(w.get("code") or "")) == code:
            w["hold_shares"] = int(args.shares)
            w["cost_price"] = cost_r
            w["code"] = code
            found = True
            break
    if not found:
        print(f"watchlist 中未找到 {code}", file=sys.stderr)
        return 1
    if not save_config_atomic(cfg_path, raw):
        print("写入失败（权限或磁盘）", file=sys.stderr)
        return 1
    print(
        f"已更新 {code}: hold_shares={int(args.shares)} cost_price={cost_r}\n"
        f"文件: {cfg_path}\n"
        f"验证: python3 run_alert.py ... 控制台执行 showhold，或检查 config.json 该条。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
