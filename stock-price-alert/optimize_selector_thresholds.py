#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 picks_history 快照 + daily_klines.db，网格搜索 select_candidate_filters 阈值组合，
使过滤后样本的锚定→T+N 收盘收益（与 backtest_picks_performance 一致）在样本量约束下最优。

与实盘选股一致：
  - 区间位置：复用 quant_core.selector._range_position_in_window（近 N 日，锚定日收盘）。
  - 卖出侧参考分：复用 quant_core.selector._max_strategy_sell_side_score + _kline_dict_for_strategies
    及 config 中 strategy_signal.min_score_by_strategy。

用法:
  .venv/bin/python3 optimize_selector_thresholds.py -c config.json
  .venv/bin/python3 optimize_selector_thresholds.py -c config.json --sell-min 60 --sell-max 80 --sell-step 5
  .venv/bin/python3 optimize_selector_thresholds.py -c config.json --range-only --json-out data/selector_threshold_grid.json

注意：样本少时最优阈值不稳定；应用前请备份 config，勿盲目自动改生产参数。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest_picks_performance import (
    code_to_secid,
    forward_close_return,
    iter_history_files,
    load_picks_records,
    resolve_db_path,
)
from kline_store import open_store_connection
from quant_core.selector import (
    _kline_dict_for_strategies,
    _max_strategy_sell_side_score,
    _range_position_in_window,
    _strategy_min_score_by_strategy,
)
from run_alert import merge_full_config


def _rows_for_secid(conn: Any, cache: dict[str, list[Any]], secid: str) -> list[Any]:
    if secid not in cache:
        cache[secid] = conn.execute(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM daily_klines
            WHERE secid = ?
            ORDER BY trade_date ASC
            """,
            (str(secid).strip(),),
        ).fetchall()
    return cache[secid]


def _index_at_anchor(rows: list[Any], anchor: str) -> int | None:
    ad = str(anchor).strip()[:10]
    i0: int | None = None
    for i, r in enumerate(rows):
        td = str(r[0])[:10]
        if td <= ad:
            i0 = i
        else:
            break
    return i0


def _df_through_anchor(rows: list[Any], i0: int) -> pd.DataFrame | None:
    if i0 is None or i0 < 0:
        return None
    part = rows[: i0 + 1]
    if not part:
        return None
    vol_default = 1_000_000.0
    return pd.DataFrame(
        {
            "close": [float(r[4]) for r in part],
            "high": [float(r[2]) for r in part],
            "low": [float(r[3]) for r in part],
            "volume": [
                float(r[5]) if len(r) > 5 and r[5] is not None else vol_default
                for r in part
            ],
        }
    )


def build_enriched_frame(
    records: list[dict[str, Any]],
    db_path: Path,
    cfg: dict[str, Any],
    *,
    horizon: int,
    range_lookback_days: int,
) -> pd.DataFrame:
    """每行：anchor、code、forward_ret、range_pos、sell_side_max（与选股过滤语义一致）。"""
    conn = open_store_connection(db_path)
    cache: dict[str, list[Any]] = {}
    ms = _strategy_min_score_by_strategy(cfg)
    n_day = max(5, min(252, int(range_lookback_days)))

    rows_out: list[dict[str, Any]] = []
    try:
        for rec in records:
            try:
                sid = code_to_secid(rec["code"])
            except Exception:
                continue
            raw = _rows_for_secid(conn, cache, sid)
            i0 = _index_at_anchor(raw, rec["anchor_date"])
            if i0 is None:
                continue
            fr, _mdd = forward_close_return(conn, sid, rec["anchor_date"], horizon)
            if fr is None:
                continue
            df_a = _df_through_anchor(raw, i0)
            if df_a is None or len(df_a) < n_day:
                continue
            rp = _range_position_in_window(df_a, n_day)
            kl = _kline_dict_for_strategies(df_a)
            price = float(df_a["close"].iloc[-1])
            if kl is None:
                sell_mx = 0.0
            else:
                sell_mx = float(
                    _max_strategy_sell_side_score(price, kl, min_score_by_strategy=ms)
                )
            row = dict(rec)
            row["forward_ret"] = float(fr)
            row["range_pos"] = float(rp) if rp is not None else np.nan
            row["sell_side_max"] = sell_mx
            row["secid"] = sid
            rows_out.append(row)
    finally:
        conn.close()

    return pd.DataFrame(rows_out)


def grid_search_selector_filters(
    df: pd.DataFrame,
    *,
    range_min: float,
    range_max: float,
    range_step: float,
    sell_min: float,
    sell_max: float,
    sell_step: float,
    range_only: bool,
    require_range_pos: bool,
    min_samples: int,
    recent_blend_weight: float = 0.0,
    recent_anchor_cutoff: str | None = None,
    min_recent_samples: int = 5,
    trade_blend_weight: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """
    对已有 enriched DataFrame 做阈值网格；返回 (grid 行列表, 最优 eligible 组合或 None)。
    无短窗叠合时：mean_ret 主序，其次 win_rate、样本数 n。
    recent_blend_weight>0 且 recent_anchor_cutoff 为 YYYY-MM-DD 时，对 anchor_date≥cutoff 子样本
    与全样本 mean_ret 加权合成 combined_mean_ret，排序以 combined_mean_ret 为先。
    trade_blend_weight>0 且 df 含 trade_norm 列时：在 combined_mean_ret 与过滤子集 mean_trade_norm 间再加权，
    得到 combined_objective 作为主排序键（同一格内 mean_trade_norm 随过滤样本变化，可与 forward 目标一起优化）。
    """
    r_grid = np.arange(range_min, range_max + range_step * 0.5, range_step)
    if range_only:
        s_grid = np.array([1.0e9], dtype=float)
    else:
        s_grid = np.arange(sell_min, sell_max + sell_step * 0.5, sell_step)
    grid_rows: list[dict[str, Any]] = []
    min_n = max(1, int(min_samples))
    w_rec = max(0.0, min(1.0, float(recent_blend_weight)))
    w_trade = max(0.0, min(1.0, float(trade_blend_weight)))
    df_recent = df
    ts_cut: pd.Timestamp | None = None
    if w_rec > 1e-9 and recent_anchor_cutoff and "anchor_date" in df.columns:
        try:
            ts_cut = pd.Timestamp(str(recent_anchor_cutoff)[:10])
            ad = pd.to_datetime(df["anchor_date"], errors="coerce")
            df_recent = df.loc[ad >= ts_cut]
        except Exception:
            df_recent = df
            ts_cut = None

    for rm in r_grid:
        for sm in s_grid:
            ev = evaluate_mask(
                df,
                range_max=float(rm),
                sell_max=float(sm),
                require_range_pos=require_range_pos,
            )
            if ev is None:
                grid_rows.append(
                    {
                        "range_position_max": round(float(rm), 4),
                        "strategy_sell_score_max": round(float(sm), 4),
                        "n": 0,
                        "mean_ret": None,
                        "win_rate": None,
                        "mean_ret_recent": None,
                        "n_recent": 0,
                        "combined_mean_ret": None,
                        "mean_trade_norm": None,
                        "combined_objective": None,
                        "eligible": False,
                    }
                )
                continue
            ev2 = dict(ev)
            ev2["range_position_max"] = round(float(rm), 4)
            ev2["strategy_sell_score_max"] = round(float(sm), 4)
            ev2["eligible"] = ev2["n"] >= min_n
            mr = ev2.get("mean_ret")
            ev_r = None
            n_r = 0
            mrr = None
            comb = mr
            if (
                w_rec > 1e-9
                and ts_cut is not None
                and not df_recent.empty
                and len(df_recent) < len(df)
            ):
                ev_r = evaluate_mask(
                    df_recent,
                    range_max=float(rm),
                    sell_max=float(sm),
                    require_range_pos=require_range_pos,
                )
                if ev_r is not None and int(ev_r["n"]) >= max(1, int(min_recent_samples)):
                    mrr = float(ev_r["mean_ret"])
                    n_r = int(ev_r["n"])
                    if mr is not None:
                        comb = (1.0 - w_rec) * float(mr) + w_rec * mrr
            ev2["mean_ret_recent"] = mrr
            ev2["n_recent"] = n_r
            ev2["combined_mean_ret"] = comb
            mt_full = float(ev.get("mean_trade_norm", 0.0) or 0.0)
            mt_blend = mt_full
            if (
                w_rec > 1e-9
                and ev_r is not None
                and int(ev_r.get("n", 0)) >= max(1, int(min_recent_samples))
            ):
                mt_recent = float(ev_r.get("mean_trade_norm", 0.0) or 0.0)
                mt_blend = (1.0 - w_rec) * mt_full + w_rec * mt_recent
            ev2["mean_trade_norm"] = mt_blend
            comb_ret = (
                float(comb) if comb is not None else (float(mr) if mr is not None else 0.0)
            )
            if w_trade > 1e-12:
                ev2["combined_objective"] = (1.0 - w_trade) * comb_ret + w_trade * mt_blend
            else:
                ev2["combined_objective"] = comb_ret
            grid_rows.append(ev2)
    eligible = [g for g in grid_rows if g.get("eligible")]
    if not eligible:
        return grid_rows, None

    def _sort_key(x: dict[str, Any]) -> tuple[float, float, float, float, int]:
        co = x.get("combined_objective")
        cm = x.get("combined_mean_ret")
        mr = x.get("mean_ret")
        wr = float(x.get("win_rate") or 0.0)
        n = int(x.get("n") or 0)
        if co is not None:
            primary = float(co)
        else:
            primary = float(cm) if cm is not None else (float(mr) if mr is not None else -1e9)
        secondary = float(cm) if cm is not None else (float(mr) if mr is not None else -1e9)
        tertiary = float(mr) if mr is not None else -1e9
        return (primary, secondary, tertiary, wr, n)

    best = max(eligible, key=_sort_key)
    return grid_rows, best


def load_enriched_selector_optimization_frame(
    cfg: dict[str, Any],
    *,
    config_path: Path,
    history_dir: Path | None,
    horizon: int,
    range_lookback_days: int | None,
    include_quality: bool = True,
    include_watch: bool = True,
    include_reject: bool = False,
) -> tuple[pd.DataFrame, int, int, int]:
    """
    加载 picks_history、合并 enriched 指标。返回 (df, n_files, n_records, range_lookback_days_eff)。
    """
    db_path = resolve_db_path(cfg)
    if not db_path.is_file():
        raise FileNotFoundError(f"日 K 库不存在: {db_path}")
    hdir = history_dir
    if hdir is None:
        hdir = config_path.parent / "data" / "picks_history"
    else:
        hdir = hdir.resolve() if hdir.is_absolute() else (ROOT / hdir).resolve()
    paths = list(iter_history_files(hdir))
    if not paths:
        raise FileNotFoundError(f"未找到历史快照: {hdir}")
    records = load_picks_records(
        paths,
        include_quality=include_quality,
        include_watch=include_watch,
        include_reject=include_reject,
    )
    qs = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
    scf = qs.get("select_candidate_filters") if isinstance(qs.get("select_candidate_filters"), dict) else {}
    rl_raw = range_lookback_days
    if rl_raw is None:
        try:
            rl_raw = int(scf.get("range_lookback_days", 20))
        except (TypeError, ValueError):
            rl_raw = 20
    rl_eff = max(5, min(252, int(rl_raw)))
    df = build_enriched_frame(
        records,
        db_path,
        cfg,
        horizon=int(horizon),
        range_lookback_days=rl_eff,
    )
    return df, len(paths), len(records), rl_eff


def evaluate_mask(
    df: pd.DataFrame,
    *,
    range_max: float,
    sell_max: float,
    require_range_pos: bool,
) -> dict[str, Any] | None:
    """
    保留：range_pos <= range_max 且 sell_side_max < sell_max（与 selector 剔除 sell_mx >= sell_max 一致）。
    require_range_pos：为 True 时丢弃 range_pos 为 NaN 的行（无法计算位置则不参与该阈值组合）。
    """
    m = pd.Series(True, index=df.index)
    if require_range_pos:
        m &= df["range_pos"].notna()
        m &= df["range_pos"] <= float(range_max)
    else:
        m &= df["range_pos"].isna() | (df["range_pos"] <= float(range_max))
    m &= df["sell_side_max"] < float(sell_max)
    sub = df.loc[m]
    n = int(len(sub))
    if n <= 0:
        return None
    r = sub["forward_ret"].astype(float)
    mt = 0.0
    if "trade_norm" in sub.columns:
        tn = pd.to_numeric(sub["trade_norm"], errors="coerce").fillna(0.0)
        mt = float(tn.mean())
    return {
        "n": n,
        "mean_ret": float(r.mean()),
        "median_ret": float(r.median()),
        "win_rate": float((r > 0).mean()),
        "std_ret": float(r.std(ddof=0)) if n > 1 else 0.0,
        "mean_trade_norm": mt,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="网格搜索 select_candidate_filters 的 range_position_max × strategy_sell_score_max"
    )
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--history-dir",
        type=Path,
        default=None,
        help="默认 config 同级 data/picks_history",
    )
    ap.add_argument("--horizon", type=int, default=5, help="与 backtest_picks_performance 一致")
    ap.add_argument(
        "--range-lookback-days",
        type=int,
        default=None,
        help="默认读 quant_selector.select_candidate_filters.range_lookback_days，缺省 20",
    )
    ap.add_argument("--range-min", type=float, default=0.5)
    ap.add_argument("--range-max", type=float, default=0.85)
    ap.add_argument("--range-step", type=float, default=0.05)
    ap.add_argument("--sell-min", type=float, default=50.0)
    ap.add_argument("--sell-max", type=float, default=85.0)
    ap.add_argument("--sell-step", type=float, default=5.0)
    ap.add_argument(
        "--range-only",
        action="store_true",
        help="只扫区间阈值，卖出分上限取极大值（等价于不筛卖出侧）",
    )
    ap.add_argument(
        "--no-require-range-pos",
        action="store_true",
        help="缺区间位置的行仍参与：仅按卖出分过滤（默认会丢弃无法算位置的行）",
    )
    ap.add_argument("--min-samples", type=int, default=15, help="低于此样本数的组合不参与最优排名")
    ap.add_argument("--include-reject", action="store_true")
    ap.add_argument("--no-watch", action="store_true")
    ap.add_argument("--no-quality", action="store_true")
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="写出全部网格结果 JSON",
    )
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    db_path = resolve_db_path(cfg)
    if not db_path.is_file():
        print(f"日 K 库不存在: {db_path}", file=sys.stderr)
        return 1

    hdir = args.history_dir
    if hdir is None:
        hdir = args.config.parent / "data" / "picks_history"
    else:
        hdir = hdir.resolve() if hdir.is_absolute() else (ROOT / hdir).resolve()
    paths = list(iter_history_files(hdir))
    if not paths:
        print(f"未找到历史快照: {hdir}", file=sys.stderr)
        return 1

    include_q = not args.no_quality
    include_w = not args.no_watch
    include_r = bool(args.include_reject)
    if not include_q and not include_w and not include_r:
        print("至少启用一类池", file=sys.stderr)
        return 1

    records = load_picks_records(
        paths,
        include_quality=include_q,
        include_watch=include_w,
        include_reject=include_r,
    )
    qs = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
    scf = qs.get("select_candidate_filters") if isinstance(qs.get("select_candidate_filters"), dict) else {}
    rl_raw = args.range_lookback_days
    if rl_raw is None:
        try:
            rl_raw = int(scf.get("range_lookback_days", 20))
        except (TypeError, ValueError):
            rl_raw = 20
    range_lookback_days = max(5, min(252, int(rl_raw)))

    require_rp = not bool(args.no_require_range_pos)

    df = build_enriched_frame(
        records,
        db_path,
        cfg,
        horizon=int(args.horizon),
        range_lookback_days=range_lookback_days,
    )
    print(
        f"有效样本: {len(df)}（快照 picks 含 forward+区间+策略分，"
        f"lookback={range_lookback_days}，horizon={args.horizon}）",
        flush=True,
    )
    if df.empty:
        print("无样本。请检查 picks_history 锚定日是否早于日 K MAX(trade_date)-N。", file=sys.stderr)
        return 1

    base = {
        "n": int(len(df)),
        "mean_ret": float(df["forward_ret"].mean()),
        "win_rate": float((df["forward_ret"] > 0).mean()),
    }
    print(
        f"基线（不过滤）: n={base['n']}, mean_ret={base['mean_ret']:.4f}, win_rate={base['win_rate']:.2%}",
        flush=True,
    )

    grid_rows, _ = grid_search_selector_filters(
        df,
        range_min=float(args.range_min),
        range_max=float(args.range_max),
        range_step=float(args.range_step),
        sell_min=float(args.sell_min),
        sell_max=float(args.sell_max),
        sell_step=float(args.sell_step),
        range_only=bool(args.range_only),
        require_range_pos=require_rp,
        min_samples=max(1, int(args.min_samples)),
    )
    min_n = max(1, int(args.min_samples))
    eligible = [g for g in grid_rows if g.get("eligible")]
    if not eligible:
        print(f"无满足 min_samples>={min_n} 的组合，可降低 --min-samples 或积累更多快照。", file=sys.stderr)
    else:
        best = max(eligible, key=lambda x: (x["mean_ret"], x["win_rate"], x["n"]))
        best_wr = max(eligible, key=lambda x: (x["win_rate"], x["mean_ret"], x["n"]))
        print("\n=== 推荐（按 mean_ret 优先，需 n>=min_samples）===", flush=True)
        print(
            f"  range_position_max={best['range_position_max']}, "
            f"strategy_sell_score_max={best['strategy_sell_score_max']}\n"
            f"  n={best['n']}, mean_ret={best['mean_ret']:.4f}, "
            f"median_ret={best.get('median_ret', 0):.4f}, win_rate={best['win_rate']:.2%}",
            flush=True,
        )
        print("\n=== 按胜率优先 ===", flush=True)
        print(
            f"  range_position_max={best_wr['range_position_max']}, "
            f"strategy_sell_score_max={best_wr['strategy_sell_score_max']}\n"
            f"  n={best_wr['n']}, mean_ret={best_wr['mean_ret']:.4f}, win_rate={best_wr['win_rate']:.2%}",
            flush=True,
        )
        print(
            "\n可将上述键写入 config.json → quant_selector.select_candidate_filters；"
            "建议人工复核后再改，并保留备份。",
            flush=True,
        )

    if args.json_out:
        out_p = args.json_out.resolve() if args.json_out.is_absolute() else (ROOT / args.json_out).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "horizon": int(args.horizon),
            "range_lookback_days": range_lookback_days,
            "baseline": base,
            "min_samples": min_n,
            "grid": grid_rows,
        }
        if eligible:
            payload["best_mean_ret"] = max(eligible, key=lambda x: (x["mean_ret"], x["win_rate"], x["n"]))
            payload["best_win_rate"] = max(eligible, key=lambda x: (x["win_rate"], x["mean_ret"], x["n"]))
        out_p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n已写: {out_p}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
