#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
券商交割单日结：任意交易日查询当日盈亏，邮件 + 企业微信（走 config.notifications）。

默认统计今天。broker_xls/ 放「全历史」交割单（整体替换即可，文件名时间为导出时刻）；
按 --date 从文件中筛该交收日。替换文件后建议：broker_summary_sync.py --all-days。

示例：
  .venv/bin/python3 broker_day_report.py -c config.json
  .venv/bin/python3 broker_day_report.py -c config.json --date 2026-05-16
  .venv/bin/python3 broker_day_report.py -c config.json --no-send
  .venv/bin/python3 broker_day_report.py -c config.json --xls broker_xls/交割单_20260518_154126.xls
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

from weekly_report import run_broker_period_report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="券商交割单日结盈亏（邮件+企微）")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--date",
        "--as-of",
        dest="as_of",
        type=str,
        default="",
        help="交易日 YYYY-MM-DD（默认今天）",
    )
    ap.add_argument("--xls", type=Path, default=None, help="指定交割单文件")
    ap.add_argument("--mapping", type=Path, default=None)
    ap.add_argument("--no-send", action="store_true", help="只打印/写 JSON，不发送")
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
            print("--date 须为 YYYY-MM-DD", file=sys.stderr)
            return 1

    try:
        run_broker_period_report(
            period="daily",
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
        logging.exception("broker_day_report failed")
        print(f"日结生成失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
