#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
券商交割单周期报告：周报 / 月报 / 半年报 / 年报（均基于 broker_xls/ 交割单）。

命名约定：交割单_YYYYMMDD_HHMMSS.xls（如 交割单_20260518_154126.xls）

示例：
  .venv/bin/python3 broker_period_report.py -c config.json --period weekly
  .venv/bin/python3 broker_period_report.py -c config.json --period monthly
  .venv/bin/python3 broker_period_report.py -c config.json --period h1
  .venv/bin/python3 broker_period_report.py -c config.json --period h2
  .venv/bin/python3 broker_period_report.py -c config.json --period annual
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from weekly_report import PERIOD_LABELS, run_broker_period_report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="券商交割单周期报告（周/月/半年/年）")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--period",
        choices=sorted(PERIOD_LABELS.keys()),
        default="weekly",
        help="报告周期",
    )
    ap.add_argument("--as-of", type=str, default="", help="锚定日 YYYY-MM-DD")
    ap.add_argument("--xls", type=Path, default=None, help="指定交割单文件")
    ap.add_argument("--mapping", type=Path, default=None)
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1

    from run_alert import merge_full_config

    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    as_of: date | None = None
    if args.as_of.strip():
        try:
            as_of = datetime.strptime(args.as_of.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            print("--as-of 须为 YYYY-MM-DD", file=sys.stderr)
            return 1

    try:
        run_broker_period_report(
            period=args.period,
            cfg=cfg,
            root=ROOT,
            as_of=as_of,
            xls_path=args.xls,
            mapping_path=args.mapping,
            send=not args.no_send,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        logging.exception("broker_period_report failed")
        print(f"生成失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
