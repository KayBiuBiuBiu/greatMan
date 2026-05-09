#!/usr/bin/env python3
"""
从 run_alert JSONL 中提取 event=watch_strategy_buy_filtered 的记录，
按事件日锚定日 K，估算其后 forward_days 个交易日收盘收益（需可访问东财日 K）。

示例::

  python scripts/analyze_buy_filter_outcomes.py \\
    --jsonl logs/run_alert.jsonl --forward-days 5

说明：事件时间若在盘中，锚定取「当日及之后第一根在数据中的日 K」的收盘；
若日志未启用或样本过少，输出会提示。
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from buy_filter_digest import (
    forward_close_return,
    infer_market,
    load_buy_filter_events,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="买入过滤拦截事件后续收益粗评")
    ap.add_argument(
        "--jsonl",
        type=Path,
        required=True,
        help="run_alert JSONL 路径（相对 stock-price-alert 或绝对路径）",
    )
    ap.add_argument("--forward-days", type=int, default=5, help="向前看的交易日根数")
    ap.add_argument("--ut", type=str, default=None, help="东财 ut，默认与主程序一致")
    ap.add_argument(
        "--max-events",
        type=int,
        default=200,
        help="最多拉取估算的事件条数（控制请求量）",
    )
    args = ap.parse_args()
    path = args.jsonl
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.is_file():
        print(f"找不到文件: {path}", file=sys.stderr)
        return 1

    events = load_buy_filter_events(path)

    if not events:
        print("未发现 watch_strategy_buy_filtered 事件（请确认 logging.enabled 与 JSONL 路径）。")
        return 0

    events = events[-int(args.max_events) :]
    rets: list[float] = []
    fail_n = 0
    by_reason: dict[str, list[float]] = defaultdict(list)
    for e in events:
        mkt = infer_market(e["code"])
        try:
            r = forward_close_return(
                e["code"],
                mkt,
                anchor=date.fromisoformat(e["date"]),
                forward_days=int(args.forward_days),
                ut=args.ut,
            )
        except Exception:
            r = None
        if r is None:
            fail_n += 1
            continue
        rets.append(r)
        key = e["reason"] or "(empty)"
        by_reason[key].append(r)

    n = len(events)
    print(f"样本事件: {n}（成功估算 {len(rets)}，失败 {fail_n}） forward_days={args.forward_days}")
    if rets:
        pct = [x * 100.0 for x in rets]
        print(
            f"收益%: 均值 {statistics.mean(pct):.2f}  中位 {statistics.median(pct):.2f}  "
            f"最小 {min(pct):.2f}  最大 {max(pct):.2f}"
        )
    for reason, xs in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))[:12]:
        ps = [x * 100.0 for x in xs]
        print(
            f"  [{len(xs)}] {reason[:80]}… | 均值 {statistics.mean(ps):.2f}%"
            if len(reason) > 80
            else f"  [{len(xs)}] {reason} | 均值 {statistics.mean(ps):.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
