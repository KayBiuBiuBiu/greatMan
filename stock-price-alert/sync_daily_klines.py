#!/usr/bin/env python3
"""盘后/定时：将 watchlist + daily_picks 优质股 的个股与解析到的板块日 K 写入 SQLite。

与 `run_alert` 在存在 `daily_picks.json` 时的监控池对齐，避免「优质股不在 watchlist」导致日 K 仍走网络。

根数与深度由 `kline_store.sync_fetch_lmt`（单次目标根数）与 `sync_target_bars`
（本地不足该根数时不做增量跳过）控制，便于 `backtest_alerts` 计算 T+5 与 hit。

用法:
  cd stock-price-alert && python3 sync_daily_klines.py
  python3 sync_daily_klines.py -c /path/to/config.json
  python3 sync_daily_klines.py --skip-daily-picks   # 仅同步 watchlist
  python3 sync_daily_klines.py --full               # 忽略本地新鲜度，全量重拉
  python3 sync_daily_klines.py --min-rows 80 --max-stale-days 2
  python3 sync_daily_klines.py --progress-every 30  # 大列表时每 N 个 secid 打一行进度
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quote_eastmoney import fetch_kline_rows_for_secid, resolve_ut, secid_for
from kline_store import (
    init_schema,
    open_store_connection,
    secid_incremental_skip_ok,
    touch_full_sync,
    upsert_bars,
)
from sector_em import resolve_sector_bk


def _sw_sector_secid(bk: str | None) -> str | None:
    if not bk:
        return None
    s = str(bk).strip().upper()
    if len(s) >= 9 and s.endswith(".SI") and s[:-3].isdigit():
        return s
    return None


def _collect_secids_from_daily_picks(
    cfg: dict,
    *,
    config_path: Path,
    root: Path,
) -> set[str]:
    """与盘中「daily_picks 优质股」对齐：优质池里不在 watchlist 的代码也要同步日 K。"""
    from run_alert import _infer_market, _load_quality_codes

    out: set[str] = set()
    picks_path = config_path.parent / "daily_picks.json"
    for c in sorted(_load_quality_codes(picks_path)):
        market = _infer_market(c)
        out.add(secid_for(c, market))
        bk = resolve_sector_bk(
            c,
            market,
            cfg,
            root=root,
            fallback_industry=None,
        )
        sw = _sw_sector_secid(bk)
        if sw:
            out.add(sw)
    return out


def _merge_cfg(raw: dict) -> dict:
    from run_alert import merge_full_config

    return merge_full_config(raw)


def run_sync_daily_klines(
    cfg: dict,
    *,
    config_path: Path,
    full: bool = False,
    skip_daily_picks: bool = False,
    min_rows: int | None = None,
    max_stale_days: int | None = None,
    progress_every: int = 0,
) -> int:
    """
    将 watchlist +（可选）daily_picks 优质股及板块日 K 写入 SQLite。
    供 CLI 与 `run_alert` 选股完成后同进程调用（与命令行脚本行为一致）。
    """
    ks = cfg.get("kline_store") or {}
    if not isinstance(ks, dict) or not bool(ks.get("enabled")):
        return 0
    from utils import configure_ssl_from_sources

    configure_ssl_from_sources(cfg.get("sources"))
    rel = str(ks.get("db_path") or "data/daily_klines.db")
    dbp = Path(rel)
    if not dbp.is_absolute():
        dbp = ROOT / dbp
    src = cfg.get("sources") or {}
    ut = resolve_ut(
        (src.get("quote_ut") or src.get("eastmoney_ut") or "ea")
        if isinstance(src, dict)
        else "ea"
    )

    min_rows_eff = min_rows
    if min_rows_eff is None:
        min_rows_eff = int(ks.get("sync_skip_min_bars") or 50)
    max_stale = max_stale_days
    if max_stale is None:
        max_stale = int(ks.get("sync_max_stale_calendar_days") or 2)
    fetch_lmt = int(ks.get("sync_fetch_lmt") or 1020)
    fetch_lmt = max(40, fetch_lmt)
    target_bars = ks.get("sync_target_bars")
    try:
        target_bars_i = int(target_bars) if target_bars is not None else 0
    except (TypeError, ValueError):
        target_bars_i = 0
    if target_bars_i < 0:
        target_bars_i = 0
    incremental = not bool(full)

    conn = open_store_connection(dbp)
    try:
        init_schema(conn)
        secids: set[str] = set()
        for rule in cfg.get("watchlist") or []:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            code = str(rule.get("code") or "").strip().zfill(6)
            market = str(rule.get("market") or "sh").strip().lower()
            if len(code) != 6 or not code.isdigit():
                continue
            secids.add(secid_for(code, market))
            ind = str(rule.get("industry") or "")
            bk = resolve_sector_bk(
                code,
                market,
                cfg,
                root=ROOT,
                fallback_industry=ind or None,
            )
            sw = _sw_sector_secid(bk)
            if sw:
                secids.add(sw)

        n_watch = len(secids)
        if not bool(skip_daily_picks):
            extra = _collect_secids_from_daily_picks(
                cfg, config_path=config_path, root=ROOT
            )
            secids |= extra
            print(
                f"[范围] watchlist 展开 {n_watch} 个 secid；"
                f"合并 daily_picks 后共 {len(secids)} 个（--skip-daily-picks 可关闭）",
                flush=True,
            )
        else:
            print(
                f"[范围] 仅 watchlist，共 {len(secids)} 个 secid（已 --skip-daily-picks）",
                flush=True,
            )

        ordered = sorted(secids)
        total = len(ordered)
        print(
            f"[开始] 待同步 secid 共 {total} 个（含个股与板块）"
            f"｜增量={'开' if incremental else '关'} min_rows={min_rows_eff} max_stale_days={max_stale}"
            f" fetch_lmt={fetch_lmt} target_bars={target_bars_i or '—'}",
            flush=True,
        )
        nbar = 0
        skipped = 0
        prog_every_eff = max(0, int(progress_every or 0))
        for i, secid in enumerate(ordered, start=1):
            if prog_every_eff and (i == 1 or i == total or i % prog_every_eff == 0):
                print(f"[进度] {i}/{total} {secid}", flush=True)
            if incremental and secid_incremental_skip_ok(
                conn,
                secid,
                min_rows=min_rows_eff,
                max_stale_calendar_days=max_stale,
                target_bars=target_bars_i if target_bars_i > 0 else None,
            ):
                skipped += 1
                print(f"[跳过-增量] {secid} 本地已够新", flush=True)
                continue
            rows = fetch_kline_rows_for_secid(secid, ut, lmt=fetch_lmt)
            if not rows:
                print(f"[跳过] 无数据 {secid}", flush=True)
                continue
            n = upsert_bars(conn, secid, rows)
            nbar += n
            print(f"[OK] {secid} 写入 {n} 条", flush=True)
        touch_full_sync(conn)
        print(
            f"[完成] 写入约 {nbar} 行，增量跳过 {skipped}，库: {dbp.resolve()}",
            flush=True,
        )
    finally:
        conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="同步日 K 到本地 SQLite")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--full",
        action="store_true",
        help="不做增量跳过，对每个 secid 都拉取并写入",
    )
    ap.add_argument(
        "--min-rows",
        type=int,
        default=None,
        help="增量模式下本地至少多少根日 K 才允许跳过（默认取 kline_store.sync_skip_min_bars 或 50）",
    )
    ap.add_argument(
        "--max-stale-days",
        type=int,
        default=None,
        help="增量模式下最新 trade_date 距今天历日超过此时则重拉（默认取 kline_store.sync_max_stale_calendar_days 或 2）",
    )
    ap.add_argument(
        "--progress-every",
        type=int,
        default=0,
        metavar="N",
        help="每处理 N 个 secid 打印一行进度（0 关闭）",
    )
    ap.add_argument(
        "--skip-daily-picks",
        action="store_true",
        help="不把 daily_picks.json 优质股并入同步列表（仅 watchlist）",
    )
    args = ap.parse_args()
    if not args.config.exists():
        print(f"缺少配置: {args.config}", flush=True)
        return 1
    cfg = _merge_cfg(json.loads(args.config.read_text(encoding="utf-8")))
    ks = cfg.get("kline_store") or {}
    if not isinstance(ks, dict) or not bool(ks.get("enabled")):
        print("请在 config 中设置 kline_store.enabled 为 true 并指定 db_path", flush=True)
        return 1
    return run_sync_daily_klines(
        cfg,
        config_path=args.config,
        full=bool(args.full),
        skip_daily_picks=bool(args.skip_daily_picks),
        min_rows=args.min_rows,
        max_stale_days=args.max_stale_days,
        progress_every=int(args.progress_every or 0),
    )


if __name__ == "__main__":
    raise SystemExit(main())
