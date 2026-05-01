#!/usr/bin/env python3
"""训练轻量 bearish 分类器（高斯朴素贝叶斯）并导出 JSON 模型。"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alert_log_store import resolve_alert_db_path
from kline_store import init_schema, open_store_connection
from ml_infer import build_feature_vector
from run_alert import merge_full_config


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _parse_extra(extra_json: str | None) -> dict[str, Any]:
    if not extra_json:
        return {}
    try:
        raw = json.loads(extra_json)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _split_since(days: int | None, since: str | None) -> str | None:
    if since:
        return since[:10]
    if days is None:
        return None
    return (date.today() - timedelta(days=max(1, int(days)))).isoformat()


def load_dataset(
    db_path: Path,
    *,
    since: str | None,
    min_label_rows: int,
    allow_insufficient: bool = False,
    cfg: dict[str, Any] | None = None,
    root: Path | None = None,
) -> tuple[list[dict[str, float]], list[int]]:
    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        q = """
            SELECT alert_type, anchor_price, extra_json, hit, anchor_trade_date, code
            FROM alert_events
            WHERE hit IS NOT NULL
              AND alert_type IN ('trend_slip', 'drawdown')
        """
        params: list[Any] = []
        if since:
            q += " AND anchor_trade_date >= ?"
            params.append(since[:10])
        q += " ORDER BY anchor_trade_date ASC, id ASC"
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()

    xs: list[dict[str, float]] = []
    ys: list[int] = []
    for r in rows:
        hit_raw = r["hit"]
        if hit_raw not in (0, 1):
            continue
        ex = _parse_extra(r["extra_json"])
        fv = build_feature_vector(
            alert_type=str(r["alert_type"] or ""),
            anchor_price=_safe_float(r["anchor_price"], 0.0),
            pnl_pct=_safe_float(ex.get("pnl_pct"), 0.0),
            weak_pillars=ex.get("weak_pillars")
            if isinstance(ex.get("weak_pillars"), dict)
            else None,
            dd_level=int(_safe_float(ex.get("dd_level"), 0.0)),
            cfg=cfg,
            root=root if root is not None else ROOT,
            code6=str(r["code"] or "").strip(),
            anchor_trade_date=str(r["anchor_trade_date"] or "")[:10],
        )
        xs.append(fv)
        ys.append(int(hit_raw))
    if len(xs) < int(min_label_rows):
        msg = f"样本不足：当前可训练样本 {len(xs)} < min_samples {min_label_rows}"
        if allow_insufficient:
            return [], []
        raise SystemExit(msg)
    if len(set(ys)) < 2:
        msg = "标签单一（全 0 或全 1），无法训练分类器"
        if allow_insufficient:
            return [], []
        raise SystemExit(msg)
    return xs, ys


def fit_gaussian_nb(xs: list[dict[str, float]], ys: list[int]) -> dict[str, Any]:
    features = sorted(xs[0].keys())
    by_cls_vals: dict[int, dict[str, list[float]]] = {
        0: defaultdict(list),
        1: defaultdict(list),
    }
    n = len(ys)
    n1 = sum(1 for y in ys if y == 1)
    n0 = n - n1
    for row, y in zip(xs, ys):
        for f in features:
            by_cls_vals[y][f].append(_safe_float(row.get(f), 0.0))

    stats: dict[str, dict[str, dict[str, float]]] = {"0": {}, "1": {}}
    for cls in (0, 1):
        for f in features:
            arr = by_cls_vals[cls][f]
            if not arr:
                mu = 0.0
                var = 1.0
            else:
                mu = sum(arr) / len(arr)
                var = sum((x - mu) ** 2 for x in arr) / max(1, len(arr) - 1)
                var = max(1e-6, float(var))
            stats[str(cls)][f] = {"mean": float(mu), "var": float(var)}

    return {
        "version": 1,
        "created_iso": datetime.now().isoformat(timespec="seconds"),
        "model_type": "gaussian_nb",
        "label_meaning": {"0": "not_bearish_hit", "1": "bearish_hit"},
        "n_samples": n,
        "class_balance": {"0": n0, "1": n1},
        "features": features,
        "class_priors": {"0": n0 / n, "1": n1 / n},
        "stats": stats,
    }


def _predict_prob(model: dict[str, Any], feats: dict[str, float]) -> float:
    features = list(model["features"])
    priors = model["class_priors"]
    stats = model["stats"]

    def _lp(cls: str) -> float:
        p0 = max(1e-12, _safe_float(priors.get(cls), 1e-12))
        s = math.log(p0)
        for f in features:
            sf = stats[cls][f]
            mu = _safe_float(sf["mean"], 0.0)
            var = max(1e-8, _safe_float(sf["var"], 1e-4))
            x = _safe_float(feats.get(f), 0.0)
            s += -0.5 * math.log(2.0 * math.pi * var) - ((x - mu) ** 2) / (2.0 * var)
        return s

    l0 = _lp("0")
    l1 = _lp("1")
    m = max(l0, l1)
    p0 = math.exp(l0 - m)
    p1 = math.exp(l1 - m)
    return p1 / max(1e-12, p0 + p1)


def eval_train_metrics(
    model: dict[str, Any],
    xs: list[dict[str, float]],
    ys: list[int],
    *,
    threshold: float,
) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for x, y in zip(xs, ys):
        p = _predict_prob(model, x)
        pred = 1 if p >= threshold else 0
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1
    n = max(1, len(ys))
    acc = (tp + tn) / n
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    return {
        "threshold": threshold,
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def _synthetic_nb_dataset(cfg: dict[str, Any]) -> tuple[list[dict[str, float]], list[int]]:
    """无 AkShare 请求的合成样本（仅用于联调）：先算基础列，再按需拼外部资金流列。"""
    from copy import deepcopy

    from external_ml_features import EXTERNAL_FLOW_FEATURE_KEYS

    raw_mf = cfg.get("ml_filter") if isinstance(cfg.get("ml_filter"), dict) else {}
    want_ext = bool(raw_mf.get("external_flow_features_enabled"))
    cfg_b = deepcopy(cfg)
    mf_b = cfg_b.setdefault("ml_filter", {})
    mf_b["external_flow_features_enabled"] = False

    codes = ["600000", "000001", "300001", "600519", "002008"]
    anchors = ["2025-03-10", "2025-06-15", "2025-09-20", "2026-01-05", "2026-03-18"]
    xs: list[dict[str, float]] = []
    ys: list[int] = []
    for i in range(36):
        wp = {
            "stock": bool(i % 2),
            "index": bool((i // 2) % 2),
            "sector": bool((i // 3) % 2),
        }
        fv = build_feature_vector(
            alert_type="trend_slip",
            anchor_price=10.0 + (i % 9) * 0.15,
            pnl_pct=-4.0 if i % 4 == 0 else 0.5 + (i % 3),
            weak_pillars=wp,
            dd_level=0,
            cfg=cfg_b,
            root=ROOT,
            code6=codes[i % len(codes)],
            anchor_trade_date=anchors[i % len(anchors)],
        )
        if want_ext:
            for j, key in enumerate(EXTERNAL_FLOW_FEATURE_KEYS):
                fv[key] = float(((i + j) % 11) - 5) * 0.05
        y = 1 if fv["weak_pillars_n"] >= 2.0 and fv["pnl_pct"] < -1.0 else 0
        if i % 9 == 0:
            y = 1 - y
        xs.append(fv)
        ys.append(y)
    return xs, ys


def main() -> int:
    ap = argparse.ArgumentParser(description="训练 bearish 命中概率模型（Gaussian NB）")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--since", type=str, default=None, help="起始日 YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=180, help="统计窗口天数（默认 180）")
    ap.add_argument(
        "--min-samples",
        type=int,
        default=18,
        help="最少训练样本数（小样本可低到 6，但需 0/1 两类都有）",
    )
    ap.add_argument(
        "--model-out",
        type=Path,
        default=ROOT / "data" / "ml_bearish_nb.json",
    )
    ap.add_argument("--report-out", type=Path, default=None)
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="训练指标统计阈值（默认 0.60）",
    )
    ap.add_argument(
        "--demo-synth-nb",
        action="store_true",
        help="alert_events 无打标样本时：用合成特征（含外部资金流维）训练一份可写出的 NB，仅联调",
    )
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)

    if args.demo_synth_nb:
        xs, ys = _synthetic_nb_dataset(cfg)
        if len(xs) < int(args.min_samples):
            print(f"合成样本过少: {len(xs)}", file=sys.stderr)
            return 1
        if len(set(ys)) < 2:
            print("合成样本标签单一，无法训练。", file=sys.stderr)
            return 1
        since_day = None
        db_path_s = "(demo_synth_nb)"
        model = fit_gaussian_nb(xs, ys)
    else:
        db_path = resolve_alert_db_path(cfg, ROOT)
        if db_path is None:
            print("alert_log 未启用，无法定位 alert_events 数据库。", file=sys.stderr)
            return 1
        since_day = _split_since(args.days, args.since)
        xs, ys = load_dataset(
            db_path,
            since=since_day,
            min_label_rows=int(args.min_samples),
            cfg=cfg,
            root=ROOT,
        )
        model = fit_gaussian_nb(xs, ys)
        db_path_s = str(db_path)
    metrics = eval_train_metrics(
        model,
        xs,
        ys,
        threshold=max(0.0, min(1.0, float(args.threshold))),
    )

    model["train_metrics"] = metrics
    model["train_since"] = since_day
    model["db_path"] = db_path_s
    out = args.model_out
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 模型已写出: {out}")
    print(
        f"样本={model['n_samples']} 命中占比={model['class_priors']['1']:.2%} "
        f"acc={metrics['accuracy']:.2%} prec={metrics['precision']:.2%} rec={metrics['recall']:.2%}"
    )
    if args.report_out:
        rp = args.report_out
        if not rp.is_absolute():
            rp = (ROOT / rp).resolve()
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(
            json.dumps(
                {
                    "model_path": str(out),
                    "n_samples": model["n_samples"],
                    "class_priors": model["class_priors"],
                    "metrics": metrics,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"📝 训练报告已写出: {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
