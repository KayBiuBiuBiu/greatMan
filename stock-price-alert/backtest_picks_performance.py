#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史优选股回测评估

读取 data/picks_history/*.json（或单日 daily_picks.json），结合 daily_klines.db
计算锚定日后第 N 个交易日收盘相对锚定日收盘的收益率，按画像维度分组统计。

用法：
  .venv/bin/python3 backtest_picks_performance.py -c config.json
  .venv/bin/python3 backtest_picks_performance.py -c config.json --history-dir data/picks_history --horizon 5
  .venv/bin/python3 backtest_picks_performance.py -c config.json --single daily_picks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import open_store_connection
from quote_eastmoney import secid_for
from run_alert import merge_full_config


def _infer_market(code6: str) -> str:
    c = str(code6).strip().zfill(6)
    if c.startswith(("6", "9")):
        return "sh"
    return "sz"


def code_to_secid(code: str) -> str:
    c = str(code).strip().zfill(6)
    return secid_for(c, _infer_market(c))


def resolve_db_path(cfg: dict[str, Any]) -> Path:
    ks = cfg.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def _parse_snapshot_date(path: Path, data: dict[str, Any]) -> str | None:
    stem = path.stem
    try:
        datetime.strptime(stem, "%Y-%m-%d")
        return stem[:10]
    except ValueError:
        pass
    ga = data.get("generated_at")
    if isinstance(ga, str) and len(ga) >= 10:
        try:
            datetime.strptime(ga[:10], "%Y-%m-%d")
            return ga[:10]
        except ValueError:
            pass
    return None


def iter_history_files(history_dir: Path) -> Iterator[Path]:
    if not history_dir.is_dir():
        return
    for p in sorted(history_dir.glob("*.json")):
        if p.is_file():
            yield p


def load_picks_records(
    paths: list[Path],
    *,
    include_quality: bool,
    include_watch: bool,
    include_reject: bool,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    key_map: list[tuple[str, str]] = []
    if include_quality:
        key_map.extend([("优质股", "优质股"), ("优质标的", "优质股")])
    if include_watch:
        key_map.extend([("观察股", "观察股"), ("观察标的", "观察股")])
    if include_reject:
        key_map.extend([("淘汰股", "淘汰股"), ("淘汰标的", "淘汰股")])

    seen_file_rows: set[tuple[str, str, str]] = set()

    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        anchor = _parse_snapshot_date(path, data)
        if not anchor:
            continue

        for src_key, bucket_label in key_map:
            rows = data.get(src_key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("code") or row.get("symbol") or row.get("代码")
                if not code:
                    continue
                code6 = str(code).strip().zfill(6)
                dedup = (anchor, code6, bucket_label)
                if dedup in seen_file_rows:
                    continue
                seen_file_rows.add(dedup)

                bt = row.get("backtest") if isinstance(row.get("backtest"), dict) else {}
                y1 = bt.get("1y") if isinstance(bt.get("1y"), dict) else {}
                prob = row.get("ml_forward4_up_prob")
                reason = str(row.get("reason") or "")
                reason_short = reason.split("｜")[0].strip()[:80] if reason else ""

                records.append(
                    {
                        "anchor_date": anchor,
                        "code": code6,
                        "name": str(row.get("name") or ""),
                        "bucket": bucket_label,
                        "score": _safe_float(row.get("score")),
                        "sw_l1": str(row.get("sw_l1") or ""),
                        "reason": reason,
                        "reason_head": reason_short or "（空）",
                        "bt_1y_profit": _safe_float(y1.get("profit")),
                        "bt_1y_win": _safe_float(y1.get("win")),
                        "ml_up_prob": _safe_float(prob),
                        "kmeans_cluster": row.get("kmeans_cluster"),
                        "ml_gate": str(row.get("ml_forward4_gate") or ""),
                    }
                )
    return records


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def forward_close_return(
    conn: Any,
    secid: str,
    anchor: str,
    horizon: int,
) -> tuple[float | None, float | None]:
    """
    锚定日收盘 -> 之后第 horizon 个交易日收盘的简单收益。
    若 anchor 非交易日，取 <= anchor 的最后一根为锚定。
    返回 (return, max_drawdown_path) ；mdd 为锚定至 T+N 区间内 (low/entry_close - 1) 的最小值（需 high/low）。
    """
    rows = conn.execute(
        """
        SELECT trade_date, open, high, low, close
        FROM daily_klines
        WHERE secid = ?
        ORDER BY trade_date ASC
        """,
        (str(secid).strip(),),
    ).fetchall()
    if not rows:
        return None, None
    ad = str(anchor).strip()[:10]
    i0 = None
    for i, r in enumerate(rows):
        td = str(r[0])[:10]
        if td <= ad:
            i0 = i
        else:
            break
    if i0 is None:
        return None, None
    if i0 + int(horizon) >= len(rows):
        return None, None
    entry = float(rows[i0][4])
    if entry <= 0:
        return None, None
    last = rows[i0 + int(horizon)]
    exit_close = float(last[4])
    ret = (exit_close - entry) / entry
    # 区间内最大回撤（相对 entry）：用每日最低价
    path_low = min(float(rows[j][3]) for j in range(i0, i0 + int(horizon) + 1))
    mdd = path_low / entry - 1.0
    return float(ret), float(mdd)


def _db_max_trade_date(db_path: Path) -> str | None:
    conn = open_store_connection(db_path)
    try:
        r = conn.execute("SELECT MAX(trade_date) FROM daily_klines").fetchone()
        if r and r[0]:
            return str(r[0])[:10]
    except Exception:
        pass
    finally:
        conn.close()
    return None


def attach_forward_metrics(
    records: list[dict[str, Any]],
    db_path: Path,
    horizon: int,
    *,
    compute_mdd: bool,
) -> pd.DataFrame:
    conn = open_store_connection(db_path)
    try:
        out_rows: list[dict[str, Any]] = []
        for rec in records:
            try:
                sid = code_to_secid(rec["code"])
            except Exception:
                continue
            r, mdd = forward_close_return(conn, sid, rec["anchor_date"], horizon)
            if r is None:
                continue
            row = dict(rec)
            row["forward_ret"] = r
            row["secid"] = sid
            if compute_mdd and mdd is not None:
                row["path_mdd"] = mdd
            out_rows.append(row)
    finally:
        conn.close()
    return pd.DataFrame(out_rows)


def _bin_score(s: pd.Series) -> pd.Series:
    # 与当前选股分制一致（约 5～8+）；缺失单独一档
    out = pd.Series("missing_score", index=s.index, dtype=object)
    m = s.notna()
    out.loc[m] = pd.cut(
        s.loc[m].astype(float),
        bins=[-np.inf, 6.0, 6.5, 7.0, 7.5, np.inf],
        labels=["<=6", "6-6.5", "6.5-7", "7-7.5", ">7.5"],
    ).astype(str)
    return out


def _bin_prob(p: pd.Series) -> pd.Series:
    out = pd.Series("missing_ml_prob", index=p.index, dtype=object)
    m = p.notna()
    out.loc[m] = pd.cut(
        p.loc[m].astype(float),
        bins=[-0.001, 0.35, 0.45, 0.55, 0.65, 1.01],
        labels=["0-35%", "35-45%", "45-55%", "55-65%", "65-100%"],
    ).astype(str)
    return out


def summarize_groups(df: pd.DataFrame, *, min_n: int) -> dict[str, pd.DataFrame]:
    summaries: dict[str, pd.DataFrame] = {}
    if df.empty:
        return summaries

    d = df.copy()
    d["score_bin"] = _bin_score(d["score"])
    d["prob_bin"] = _bin_prob(d["ml_up_prob"])

    dims: list[tuple[str, str]] = [
        ("score_bin", "形态评分段"),
        ("prob_bin", "ml_forward4 概率段"),
        ("bucket", "池（优质/观察）"),
        ("reason_head", "reason 首段"),
    ]
    if d["sw_l1"].notna().any() and (d["sw_l1"].astype(str).str.len() > 2).any():
        dims.append(("sw_l1", "申万一级"))

    for col, _title in dims:
        if col not in d.columns:
            continue
        g = (
            d.groupby(col, dropna=False)["forward_ret"]
            .agg(
                mean_return="mean",
                median_return="median",
                std="std",
                count="count",
                win_rate=lambda x: float((x > 0).mean()) if len(x) else 0.0,
            )
            .sort_values("mean_return", ascending=False)
        )
        g = g[g["count"] >= int(min_n)]
        summaries[col] = g

    if "path_mdd" in d.columns:
        g2 = (
            d.groupby("score_bin", dropna=False)
            .agg(mean_ret=("forward_ret", "mean"), mean_mdd=("path_mdd", "mean"), n=("forward_ret", "count"))
            .sort_values("mean_ret", ascending=False)
        )
        summaries["score_bin_mdd"] = g2[g2["n"] >= int(min_n)]

    return summaries


def print_text_report(summaries: dict[str, pd.DataFrame], min_n: int) -> None:
    print(f"\n=== 分组汇总（每组至少 {min_n} 条）===\n")
    titles = {
        "score_bin": "按形态评分段 (score)",
        "prob_bin": "按 ml_forward4_up_prob",
        "bucket": "按池",
        "reason_head": "按 reason 首段（｜ 前）",
        "sw_l1": "按申万一级",
        "score_bin_mdd": "评分段 × 平均路径回撤（至 T+N）",
    }
    for k, sdf in summaries.items():
        title = titles.get(k, k)
        print(f"--- {title} ---")
        if sdf is None or sdf.empty:
            print("（样本不足）\n")
            continue
        print(sdf.to_string())
        print()


def build_recommendations(summaries: dict[str, pd.DataFrame]) -> list[str]:
    lines: list[str] = []
    sb = summaries.get("score_bin")
    if sb is not None and not sb.empty:
        best = sb.index[0]
        worst = sb.index[-1]
        lines.append(
            f"评分段：平均收益最高为 [{best}]（mean={sb.iloc[0]['mean_return']:.4f}），"
            f"最低为 [{worst}]（mean={sb.iloc[-1]['mean_return']:.4f}）。"
        )
    pb = summaries.get("prob_bin")
    if pb is not None and not pb.empty:
        lines.append(
            f"ML 概率段：head mean 最高 [{pb.index[0]}]，最低 [{pb.index[-1]}]（注意过拟合与样本量）。"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="历史 daily_picks 画像 × 未来收益回测")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--history-dir",
        type=Path,
        default=None,
        help="快照目录，默认 config 同级的 data/picks_history",
    )
    ap.add_argument(
        "--single",
        type=Path,
        default=None,
        help="只分析单个 JSON（如 daily_picks.json），忽略 history-dir",
    )
    ap.add_argument("--horizon", type=int, default=5, help="未来 N 个交易日（默认 5）")
    ap.add_argument("--min-group-n", type=int, default=20, help="分组最少样本数")
    ap.add_argument("--include-reject", action="store_true", help="纳入淘汰池（样本大、噪声高）")
    ap.add_argument("--no-watch", action="store_true", help="不纳入观察池")
    ap.add_argument("--no-quality", action="store_true", help="不纳入优质池")
    ap.add_argument("--mdd", action="store_true", help="计算锚定→T+N 路径最大回撤（相对入场收盘）")
    ap.add_argument(
        "--out-prefix",
        type=Path,
        default=None,
        help="输出前缀：写 <prefix>_detail.csv 与 <prefix>_summary.json",
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

    if args.single:
        paths = [args.single.resolve() if not args.single.is_absolute() else args.single]
        if not paths[0].is_file():
            print(f"找不到文件: {paths[0]}", file=sys.stderr)
            return 1
    else:
        hdir = args.history_dir
        if hdir is None:
            hdir = args.config.parent / "data" / "picks_history"
        else:
            hdir = hdir.resolve() if hdir.is_absolute() else (ROOT / hdir).resolve()
        paths = list(iter_history_files(hdir))
        if not paths:
            print(
                f"未找到历史快照: {hdir}\n"
                f"请将 daily_picks.json 按日期复制为 YYYY-MM-DD.json，"
                f"或开启 quant_selector.picks_history_snapshot.enabled 自动备份。",
                file=sys.stderr,
            )
            return 1

    include_q = not args.no_quality
    include_w = not args.no_watch
    include_r = bool(args.include_reject)
    if not include_q and not include_w and not include_r:
        print("至少启用一类池（默认优质+观察）", file=sys.stderr)
        return 1

    records = load_picks_records(
        paths,
        include_quality=include_q,
        include_watch=include_w,
        include_reject=include_r,
    )
    print(f"加载 picks 行数: {len(records)}（来自 {len(paths)} 个文件）", flush=True)
    if len(records) < 10:
        print("样本过少，无法稳定统计。", file=sys.stderr)
        return 1

    mx = _db_max_trade_date(db_path)
    if mx:
        print(f"日 K 库最新交易日: {mx}（锚定日须显著早于该日，才能留出未来 {args.horizon} 根 K 线）", flush=True)

    df = attach_forward_metrics(records, db_path, int(args.horizon), compute_mdd=args.mdd)
    print(f"有效 forward 样本: {len(df)}（horizon={args.horizon}）", flush=True)
    if df.empty:
        print(
            "无有效收益样本。常见原因：\n"
            "  1) 快照日期过新（接近库内 MAX(trade_date)），尚不存在 T+N 收盘；\n"
            "  2) 个股在库中缺 secid / 缺 K 线；\n"
            "请使用更早日期的 picks_history/*.json，或同步日 K 后再跑。",
            file=sys.stderr,
        )
        return 1

    summaries = summarize_groups(df, min_n=int(args.min_group_n))
    print_text_report(summaries, int(args.min_group_n))
    recs = build_recommendations(summaries)
    if recs:
        print("=== 启发式结论（非因果，需更多快照验证）===\n")
        for ln in recs:
            print(ln)
        print()

    out_pre = args.out_prefix
    if out_pre is None:
        out_pre = args.config.parent / "data" / "picks_backtest"
    else:
        out_pre = out_pre.resolve() if out_pre.is_absolute() else (ROOT / out_pre).resolve()
    out_pre.parent.mkdir(parents=True, exist_ok=True)
    csv_p = Path(str(out_pre) + "_detail.csv")
    df.to_csv(csv_p, index=False)
    print(f"明细 CSV: {csv_p}", flush=True)

    ser: dict[str, Any] = {
        "horizon_trading_days": int(args.horizon),
        "n_files": len(paths),
        "n_picks_loaded": len(records),
        "n_forward_ok": len(df),
        "overall_mean_ret": float(df["forward_ret"].mean()),
        "overall_win_rate": float((df["forward_ret"] > 0).mean()),
        "summaries": {k: v.reset_index().to_dict(orient="records") for k, v in summaries.items()},
        "recommendations": recs,
    }
    json_p = Path(str(out_pre) + "_summary.json")
    json_p.write_text(json.dumps(ser, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"汇总 JSON: {json_p}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
