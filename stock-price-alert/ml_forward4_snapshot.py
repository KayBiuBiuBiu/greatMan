#!/usr/bin/env python3
"""
记录某日全市场 forward4 的 P(up)，并在未来交易日回填真实 T+N 标签，输出精确率与可靠性分箱。

示例：
  # 5 月 11 日收盘后（锚定日）记录预测
  .venv/bin/python3 ml_forward4_snapshot.py -c config.json record --anchor-date 2026-05-11

  # 回填日须为锚定日后第 N 个交易日（N=horizon_trading_days，见每条 jsonl 记录）
  .venv/bin/python3 ml_forward4_snapshot.py -c config.json backfill \\
      --snapshot data/forward4_snapshots/p_up_2026-05-11.jsonl --report-out data/forward4_snapshots/eval_2026-05-11.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import init_schema, open_store_connection
from ml_forward4 import (
    FORWARD_UP_HORIZON_TRADING_DAYS,
    compute_forward4_features_for_secid,
    list_stock_secids,
    load_forward4_model_cached,
    predict_forward4_up_probability,
    resolve_forward4_model_path,
    resolve_kline_db_path,
)
from ml_forward4_prob_tools import dump_eval_report, eval_metrics_dict
from run_alert import merge_full_config


def _closes_from_anchor(
    conn: Any,
    secid: str,
    anchor: str,
    horizon: int,
) -> tuple[float | None, float | None, str | None]:
    """返回 (close_T, close_T+N, date_T+N)；缺数据则 None。"""
    rows = conn.execute(
        """
        SELECT trade_date, close
        FROM daily_klines
        WHERE secid = ?
        ORDER BY trade_date ASC
        """,
        (str(secid).strip(),),
    ).fetchall()
    ad = str(anchor).strip()[:10]
    i0 = None
    for i, r in enumerate(rows):
        if str(r[0])[:10] == ad:
            i0 = i
            break
    if i0 is None or i0 + int(horizon) >= len(rows):
        return None, None, None
    c0 = float(rows[i0][1])
    rN = rows[i0 + int(horizon)]
    return c0, float(rN[1]), str(rN[0])[:10]


def cmd_record(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    db_path = resolve_kline_db_path(cfg, ROOT)
    if not db_path.is_file():
        print(f"日 K 库不存在: {db_path}", file=sys.stderr)
        return 1
    mpath = resolve_forward4_model_path(cfg, ROOT)
    model = load_forward4_model_cached(mpath)
    if not model:
        print(f"无法加载模型: {mpath}", file=sys.stderr)
        return 1
    horizon = int(model.get("horizon_trading_days") or FORWARD_UP_HORIZON_TRADING_DAYS)
    min_r = int((cfg.get("ml_forward4") or {}).get("min_bars_infer") or 80)
    anchor = str(args.anchor_date).strip()[:10]
    if len(anchor) != 10:
        print("anchor-date 须为 YYYY-MM-DD", file=sys.stderr)
        return 1

    out = Path(args.snapshot_out)
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cap = int(args.max_secids) if int(args.max_secids) > 0 else 10**9
    conn = open_store_connection(db_path)
    n_ok = 0
    n_skip = 0
    try:
        init_schema(conn)
        secids = list_stock_secids(conn)[:cap]
        with out.open("w", encoding="utf-8") as f:
            for i, sid in enumerate(secids, start=1):
                if i % 500 == 0:
                    print(f"[进度] {i}/{len(secids)} ok={n_ok} skip={n_skip}", flush=True)
                feats = compute_forward4_features_for_secid(
                    conn, sid, anchor, min_rows=min_r
                )
                if feats is None:
                    n_skip += 1
                    continue
                p = predict_forward4_up_probability(model, feats)
                if p is None:
                    n_skip += 1
                    continue
                rec = {
                    "anchor_trade_date": anchor,
                    "secid": sid,
                    "p_up": round(float(p), 6),
                    "horizon_trading_days": horizon,
                    "model_path": str(mpath),
                    "recorded_iso": datetime.now().isoformat(timespec="seconds"),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_ok += 1
    finally:
        conn.close()
    print(f"✅ 已写入 {out} | 有效 {n_ok} | 跳过 {n_skip}", flush=True)
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    db_path = resolve_kline_db_path(cfg, ROOT)
    if not db_path.is_file():
        print(f"日 K 库不存在: {db_path}", file=sys.stderr)
        return 1
    snap = Path(args.snapshot)
    if not snap.is_file():
        print(f"找不到快照: {snap}", file=sys.stderr)
        return 1

    lines: list[dict[str, Any]] = []
    for ln in snap.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        lines.append(json.loads(ln))

    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        ys: list[int] = []
        ps: list[float] = []
        meta: list[dict[str, Any]] = []
        for rec in lines:
            sid = str(rec.get("secid") or "").strip()
            ad = str(rec.get("anchor_trade_date") or "")[:10]
            h = int(rec.get("horizon_trading_days") or FORWARD_UP_HORIZON_TRADING_DAYS)
            p = rec.get("p_up")
            if not sid or len(ad) != 10 or p is None:
                continue
            c0, cN, dN = _closes_from_anchor(conn, sid, ad, h)
            if c0 is None or cN is None:
                continue
            y = 1 if cN > c0 else 0
            ys.append(y)
            ps.append(float(p))
            meta.append(
                {
                    "secid": sid,
                    "y_true": y,
                    "close_anchor": c0,
                    f"close_T+{h}": cN,
                    "eval_trade_date": dN,
                }
            )
    finally:
        conn.close()

    if len(ys) < 20:
        print(f"有效回填样本过少: {len(ys)}", file=sys.stderr)
        return 1

    thr = float(args.threshold)
    pred = [1 if p >= thr else 0 for p in ps]
    tp = sum(1 for a, b in zip(pred, ys) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(pred, ys) if a == 1 and b == 0)
    prec = tp / max(1, tp + fp)
    m = eval_metrics_dict(ys, ps, n_bins=int(args.n_bins))
    out_payload = {
        "snapshot": str(snap),
        "n": len(ys),
        "threshold": thr,
        "precision_at_threshold": prec,
        "tp": tp,
        "fp": fp,
        "positives_rate": sum(ys) / len(ys),
        "auc": m["auc"],
        "brier": m["brier"],
        "reliability_bins": m["reliability_bins"],
        "rows": meta[:500],
    }
    if args.report_out:
        rp = Path(args.report_out)
        if not rp.is_absolute():
            rp = (ROOT / rp).resolve()
        dump_eval_report(rp, out_payload)
        print(f"✅ 评估已写出: {rp}", flush=True)
    print(
        f"n={len(ys)} prec@{thr:g}={prec:.4f} AUC={m['auc']} Brier={m['brier']}",
        flush=True,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Forward4 快照记录与回填评估")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sr = sub.add_parser("record", help="写入某日全市场 p_up 快照（jsonl）")
    sr.add_argument("--anchor-date", type=str, required=True)
    sr.add_argument(
        "--snapshot-out",
        type=str,
        default="",
        help="输出路径，默认 data/forward4_snapshots/p_up_<date>.jsonl",
    )
    sr.add_argument("--max-secids", type=int, default=0)
    sr.set_defaults(func=cmd_record)

    sb = sub.add_parser("backfill", help="根据日 K 回填标签并算可靠性")
    sb.add_argument("--snapshot", type=str, required=True, help="record 生成的 jsonl")
    sb.add_argument("--report-out", type=str, default="")
    sb.add_argument("--threshold", type=float, default=0.5)
    sb.add_argument("--n-bins", type=int, default=10)
    sb.set_defaults(func=cmd_backfill)

    args = ap.parse_args()
    if args.cmd == "record" and not str(getattr(args, "snapshot_out", "") or "").strip():
        ad = str(args.anchor_date).strip()[:10]
        args.snapshot_out = str(ROOT / "data" / "forward4_snapshots" / f"p_up_{ad}.jsonl")
    if args.cmd == "backfill" and not str(getattr(args, "report_out", "") or "").strip():
        args.report_out = str(
            ROOT / "data" / "forward4_snapshots" / f"eval_{Path(args.snapshot).stem}.json"
        )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
