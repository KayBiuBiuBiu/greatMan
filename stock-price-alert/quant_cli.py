#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_core.backtest import run_backtest_pack
from quant_core.selector import run_daily_selector, save_daily_selector_result


def _load_cfg(cfg_path: Path) -> dict:
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Quant system CLI")
    ap.add_argument("-c", "--config", type=Path, default=Path(__file__).parent / "config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("daily-select", help="Run pre-market selection for all strategies")
    p1.add_argument("--limit", type=int, default=250)
    p1.add_argument("--top", type=int, default=20, help="Top picks per strategy")
    p1.add_argument("--output", type=Path, default=Path(__file__).parent / "daily_picks.json")

    p2 = sub.add_parser("backtest", help="Run 1y/3y/5y backtest")
    p2.add_argument("--code", required=True, help="6-digit stock code, e.g. 600711")
    p2.add_argument("--years", default="1,3,5", help="comma separated, e.g. 1,3,5")
    p2.add_argument("--output", type=Path, default=Path(__file__).parent / "backtest_report.json")

    args = ap.parse_args()
    cfg = _load_cfg(args.config)

    if args.cmd == "daily-select":
        result = run_daily_selector(cfg, limit=args.limit, top_n_per_strategy=args.top)
        save_daily_selector_result(result, args.output)
        print(f"[ok] daily picks saved: {args.output}")
        for k, rows in (result.get("strategies") or {}).items():
            print(f"  - {k}: {len(rows)}")
        return 0

    if args.cmd == "backtest":
        years = [int(x.strip()) for x in str(args.years).split(",") if x.strip()]
        report = run_backtest_pack(args.code, years_list=years)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ok] backtest report saved: {args.output}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

