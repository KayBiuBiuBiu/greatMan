#!/usr/bin/env python3
"""根据本地 daily_klines 预计算 MA/MACD/ATR% 等并写入 indicator_last（供监控读库合并）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_indicators import compute_and_store_indicator_last_for_secid
from kline_store import init_schema, open_store_connection, secid_bar_stats
from quote_eastmoney import secid_for


def _merge_cfg(raw: dict) -> dict:
    from run_alert import merge_full_config

    return merge_full_config(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="预计算日 K 指标写入 SQLite")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="最多处理 N 个 secid（0 表示不限制）",
    )
    args = ap.parse_args()
    if not args.config.exists():
        print(f"缺少配置: {args.config}", flush=True)
        return 1
    cfg = _merge_cfg(json.loads(args.config.read_text(encoding="utf-8")))
    ks = cfg.get("kline_store") or {}
    if not isinstance(ks, dict) or not bool(ks.get("enabled")):
        print("请启用 kline_store", flush=True)
        return 1
    rel = str(ks.get("db_path") or "data/daily_klines.db")
    dbp = Path(rel)
    if not dbp.is_absolute():
        dbp = ROOT / dbp
    if not dbp.is_file():
        print(f"库不存在: {dbp}", flush=True)
        return 1

    secids: list[str] = []
    for rule in cfg.get("watchlist") or []:
        if not isinstance(rule, dict) or not rule.get("enabled", True):
            continue
        code = str(rule.get("code") or "").strip().zfill(6)
        market = str(rule.get("market") or "sh").strip().lower()
        if len(code) != 6 or not code.isdigit():
            continue
        secids.append(secid_for(code, market))
    secids = sorted(set(secids))
    lim = int(args.limit or 0)
    if lim > 0:
        secids = secids[:lim]

    conn = open_store_connection(dbp)
    try:
        init_schema(conn)
        ok = 0
        for sid in secids:
            n, mx = secid_bar_stats(conn, sid)
            if n < 35 or not mx:
                print(f"[跳过] {sid} 根数不足或无日期", flush=True)
                continue
            row = conn.execute(
                """
                SELECT open, high, low, close, volume FROM daily_klines
                WHERE secid = ? ORDER BY trade_date ASC
                """,
                (sid,),
            ).fetchall()
            if len(row) < 35:
                continue
            opens = [float(r["open"]) for r in row]
            highs = [float(r["high"]) for r in row]
            lows = [float(r["low"]) for r in row]
            closes = [float(r["close"]) for r in row]
            vols = [float(r["volume"] or 0) for r in row]
            if compute_and_store_indicator_last_for_secid(
                conn,
                sid,
                opens=opens,
                highs=highs,
                lows=lows,
                closes=closes,
                vols=vols,
                last_trade_date=mx,
            ):
                ok += 1
                print(f"[OK] {sid} @ {mx}", flush=True)
            else:
                print(f"[跳过] {sid} 计算失败", flush=True)
        print(f"[完成] 写入 {ok}/{len(secids)} 个 secid → {dbp}", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
