#!/usr/bin/env python3
"""
仓位建议回测：
1) `eval-db`：复用 backtest_alerts 逻辑，对 alert_events 中 alert_type=position_suggestion 补算收益与 hit。
2) `replay`：按日 K 库逐交易日回放持仓标的，调用与实盘相同的 _get_position_suggestion，统计命中率。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alert_log_store import (
    compute_position_suggestion_hit,
    forward_returns_vs_anchor,
    resolve_alert_db_path,
)
from kline_store import init_schema, open_store_connection
from position_tags import has_position_tag
from quote_eastmoney import kline_dict_from_ohlcv_series, secid_for
from run_alert import (
    _fill_position_suggestion_metrics,
    _get_position_suggestion,
    merge_full_config,
    normalize_stock_code,
)


def _infer_mkt(code: str, rule: dict[str, Any]) -> str:
    m = str(rule.get("market") or "").strip().lower()
    if m in ("sh", "sz", "1", "0"):
        if m in ("1", "sh"):
            return "sh"
        if m in ("0", "sz"):
            return "sz"
    c = str(code).strip()
    return "sh" if c.startswith("6") else "sz"


def _fetch_bars_asc(
    conn: Any, secid: str, end_td: str, limit_n: int
) -> list[tuple[Any, ...]]:
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close, volume
        FROM daily_klines
        WHERE secid = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (secid, end_td[:10], int(limit_n)),
    ).fetchall()
    return list(reversed(rows))


def _kline_calendar_span(conn: Any) -> tuple[str | None, str | None]:
    row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM daily_klines"
    ).fetchone()
    if not row or row[0] is None:
        return None, None
    return str(row[0])[:10], str(row[1])[:10]


def _rows_to_kline(rows: list[tuple[Any, ...]], td: str) -> dict[str, Any] | None:
    if len(rows) < 20:
        return None
    opens = [float(r[1]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]
    vols = [float(r[5] or 0) for r in rows]
    return kline_dict_from_ohlcv_series(
        opens,
        highs,
        lows,
        closes,
        vols,
        return_closes=True,
        kline_data_source="replay",
        kline_last_trade_date=td[:10],
    )


def run_replay(
    cfg: dict[str, Any],
    *,
    root: Path,
    since: str,
    until: str,
    min_bars: int,
    codes_filter: set[str] | None,
) -> dict[str, Any]:
    ks = cfg.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    dbp = Path(rel)
    if not dbp.is_absolute():
        dbp = root / dbp
    if not dbp.is_file():
        raise SystemExit(f"未找到日 K 库: {dbp}")

    ev = (cfg.get("alert_log") or {}).get("position_suggestion_eval") or {}
    if not isinstance(ev, dict):
        ev = {}

    wl = cfg.get("watchlist") or []
    rules: list[dict[str, Any]] = []
    for w in wl:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        if not has_position_tag(w):
            continue
        cp = float(w.get("cost_price") or 0.0)
        if cp <= 0:
            continue
        c6 = normalize_stock_code(str(w.get("code") or "").strip())
        if not c6:
            continue
        if codes_filter is not None and c6 not in codes_filter:
            continue
        rules.append(dict(w))

    if not rules:
        raise SystemExit("watchlist 中无带持仓标签且 cost_price>0 的标的，无法回放。")

    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "scored": 0, "hit": 0}
    )
    samples: list[dict[str, Any]] = []

    db_td_min: str | None = None
    db_td_max: str | None = None
    conn = open_store_connection(dbp)
    per_symbol: list[dict[str, Any]] = []
    calendar_in_range = 0
    simulated_days = 0
    skipped_short_history = 0
    skipped_kline = 0
    try:
        init_schema(conn)
        db_td_min, db_td_max = _kline_calendar_span(conn)
        for rule in rules:
            code = normalize_stock_code(str(rule.get("code") or "").strip()) or ""
            mkt = _infer_mkt(code, rule)
            sid = secid_for(code, mkt)
            drows = conn.execute(
                """
                SELECT trade_date FROM daily_klines
                WHERE secid = ? AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date ASC
                """,
                (sid, since[:10], until[:10]),
            ).fetchall()
            per_symbol.append(
                {
                    "code": code,
                    "secid": sid,
                    "trading_days_in_range": len(drows),
                }
            )
            calendar_in_range += len(drows)
            for (td,) in drows:
                td10 = str(td)[:10]
                bars = _fetch_bars_asc(conn, sid, td10, max(min_bars, 80))
                if len(bars) < min_bars:
                    skipped_short_history += 1
                    continue
                kd = _rows_to_kline(bars, td10)
                if not kd:
                    skipped_kline += 1
                    continue
                px = float(bars[-1][4])
                if px <= 0:
                    continue
                cost = float(rule.get("cost_price") or 0.0)
                pnl_pct = (px - cost) / cost * 100.0
                pack: dict[str, Any] = {
                    "rule": rule,
                    "q": {"code": code, "price": px},
                    "kline": kd,
                    "_market_mood_tier": "range",
                }
                _fill_position_suggestion_metrics(pack, px)
                act, why = _get_position_suggestion(
                    pack,
                    cfg,
                    pnl_pct=float(pnl_pct),
                    bearish_prob=None,
                )
                r1, r3, r5 = forward_returns_vs_anchor(conn, sid, td10, px)
                ex = {
                    "ps_action": act,
                    "ps_reason": why,
                    "pnl_pct": float(pnl_pct),
                    "replay": True,
                }
                hit = compute_position_suggestion_hit(ex, r1, r3, r5, ev)
                simulated_days += 1
                agg[act]["n"] += 1
                if hit is not None:
                    agg[act]["scored"] += 1
                    agg[act]["hit"] += int(hit)
                if len(samples) < 30:
                    samples.append(
                        {
                            "code": code,
                            "anchor": td10,
                            "action": act,
                            "pnl_pct": round(pnl_pct, 2),
                            "r5": None if r5 is None else round(float(r5) * 100.0, 3),
                            "hit": hit,
                            "reason": why[:80] if why else "",
                        }
                    )
    finally:
        conn.close()

    hints: list[str] = []
    s0, u0 = since[:10], until[:10]
    if calendar_in_range == 0 and rules:
        if db_td_min and db_td_max:
            if u0 < db_td_min:
                hints.append(
                    f"请求区间 [{s0},{u0}] 早于日K库最早交易日 {db_td_min}，无重叠。"
                )
            elif s0 > db_td_max:
                hints.append(
                    f"请求区间 [{s0},{u0}] 晚于日K库最后交易日 {db_td_max}，无重叠。"
                )
            else:
                hints.append(
                    "请求区间与库内有重叠，但当前 watchlist 标的在该区间内无K线（"
                    "检查代码/市场是否与库内 secid 一致）。"
                )
        else:
            hints.append("日K库中无任何 daily_klines 数据。")
    elif calendar_in_range > 0 and simulated_days == 0:
        hints.append(
            f"区间内有 {calendar_in_range} 个标的日，但均未完成模拟（"
            f"多因历史K线不足 min_bars={min_bars}：跳过 {skipped_short_history} 次；"
            f"kline 构建失败 {skipped_kline} 次）。"
        )

    by_action: dict[str, Any] = {}
    for act, v in sorted(agg.items()):
        n = int(v["n"])
        ns = int(v["scored"])
        nh = int(v["hit"])
        by_action[act] = {
            "n_days": n,
            "n_scored": ns,
            "hit_rate": (nh / ns) if ns else None,
        }
    return {
        "mode": "replay",
        "db_path": str(dbp),
        "since": since[:10],
        "until": until[:10],
        "min_bars": min_bars,
        "diagnostics": {
            "kline_db_min_date": db_td_min,
            "kline_db_max_date": db_td_max,
            "per_symbol": per_symbol,
            "calendar_days_in_range": calendar_in_range,
            "simulated_days": simulated_days,
            "skipped_short_history": skipped_short_history,
            "skipped_kline_build": skipped_kline,
            "hints": hints,
        },
        "by_action": by_action,
        "samples": samples,
    }


def run_eval_db(cfg: dict[str, Any], *, root: Path, since: str | None, force: bool) -> dict[str, Any]:
    """调用 backtest_alerts.run_eval，仅依赖库内已有 position_suggestion 事件。"""
    from backtest_alerts import run_eval

    return run_eval(
        cfg,
        root=root,
        since=since,
        force=force,
        reeval_missing_returns=False,
        limit=None,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="仓位建议：回放回测 / 库内事件评估")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("replay", help="按日 K 逐日模拟建议并统计命中")
    p1.add_argument("--since", type=str, required=True)
    p1.add_argument("--until", type=str, required=True)
    p1.add_argument("--min-bars", type=int, default=60)
    p1.add_argument(
        "--codes",
        type=str,
        default="",
        help="仅这些代码（逗号分隔六位），默认 watchlist 全部持仓标签标的",
    )
    p1.add_argument("--json-out", type=Path, default=None)

    p2 = sub.add_parser("eval-db", help="对 alert_events 中 position_suggestion 补算（同 backtest_alerts）")
    p2.add_argument("--since", type=str, default=None)
    p2.add_argument("--force", action="store_true")
    p2.add_argument("--json-out", type=Path, default=None)

    args = ap.parse_args()
    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)

    if args.cmd == "eval-db":
        dbp = resolve_alert_db_path(cfg, ROOT)
        if dbp is None:
            print("请在 config 中启用 alert_log.enabled。", file=sys.stderr)
            return 1
        rep = run_eval_db(cfg, root=ROOT, since=args.since, force=bool(args.force))
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        if args.json_out:
            args.json_out.write_text(
                json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return 0

    if args.cmd == "replay":
        cf: set[str] | None = None
        if str(args.codes).strip():
            cf = set()
            for p in str(args.codes).split(","):
                s = normalize_stock_code(p.strip()) or p.strip().zfill(6)
                if len(s) == 6 and s.isdigit():
                    cf.add(s)
        rep = run_replay(
            cfg,
            root=ROOT,
            since=args.since,
            until=args.until,
            min_bars=max(20, int(args.min_bars)),
            codes_filter=cf,
        )
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        if args.json_out:
            args.json_out.write_text(
                json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
