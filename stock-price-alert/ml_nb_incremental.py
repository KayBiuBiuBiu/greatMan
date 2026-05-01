#!/usr/bin/env python3
"""
用最近 N 日已打标样本快速重训 GaussianNB，并写回与 ml_infer 兼容的 JSON 模型。

说明：当前实现为「滑动窗口全量小样本重训」（非 partial_fit 状态机），
      适合每日收盘后轻量刷新；输出格式与 ml_train 一致。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alert_log_store import resolve_alert_db_path
from ml_train import eval_train_metrics, load_dataset
from run_alert import merge_full_config


def _sklearn_nb_to_json(clf: Any, feature_names: list[str]) -> dict[str, Any]:
    """sklearn GaussianNB → ml_train 同款 JSON。"""
    classes = [int(c) for c in clf.classes_.tolist()]
    if 0 not in classes or 1 not in classes:
        raise ValueError("需要同时包含 0/1 两类样本")
    n = int(clf.class_count_.sum())
    n1 = int(clf.class_count_[list(clf.classes_).index(1)])
    n0 = n - n1
    stats: dict[str, dict[str, dict[str, float]]] = {"0": {}, "1": {}}
    for j, f in enumerate(feature_names):
        for cls in (0, 1):
            ci = list(clf.classes_).index(cls)
            mu = float(clf.theta_[ci, j])
            var = max(1e-6, float(clf.var_[ci, j]))
            stats[str(cls)][f] = {"mean": mu, "var": var}
    return {
        "version": 1,
        "created_iso": datetime.now().isoformat(timespec="seconds"),
        "model_type": "gaussian_nb",
        "label_meaning": {"0": "not_bearish_hit", "1": "bearish_hit"},
        "n_samples": n,
        "class_balance": {"0": n0, "1": n1},
        "features": feature_names,
        "class_priors": {"0": n0 / max(1, n), "1": n1 / max(1, n)},
        "stats": stats,
    }


def main() -> int:
    try:
        from sklearn.naive_bayes import GaussianNB
    except ImportError:
        print("需要 scikit-learn：pip install scikit-learn", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description="NB 模型滑动窗口快速重训（写 JSON）")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument(
        "--min-samples",
        type=int,
        default=12,
        help="最少样本数（可与 ops_automation.incremental_nb_min_samples 对齐，可低至 6）",
    )
    ap.add_argument("--threshold", type=float, default=0.60)
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    db_path = resolve_alert_db_path(cfg, ROOT)
    if db_path is None:
        print("alert_log 未启用。", file=sys.stderr)
        return 1
    since = (date.today() - timedelta(days=max(1, int(args.days)))).isoformat()
    xs, ys = load_dataset(
        db_path,
        since=since,
        min_label_rows=int(args.min_samples),
        allow_insufficient=True,
        cfg=cfg,
        root=ROOT,
    )
    if not xs:
        print(
            f"跳过：窗口内已打标样本不足（since={since[:10]}，min_samples={args.min_samples}）。",
            file=sys.stderr,
        )
        return 0
    feats = sorted(xs[0].keys())
    X = np.array([[float(row[f]) for f in feats] for row in xs], dtype=np.float64)
    y = np.array(ys, dtype=np.int64)
    clf = GaussianNB()
    clf.fit(X, y)
    model = _sklearn_nb_to_json(clf, feats)
    metrics = eval_train_metrics(
        model,
        xs,
        ys,
        threshold=max(0.0, min(1.0, float(args.threshold))),
    )
    mf = cfg.get("ml_filter") or {}
    out = Path(str(mf.get("model_path") or "data/ml_bearish_nb.json").strip())
    if not out.is_absolute():
        out = ROOT / out
    bak = out.with_suffix(out.suffix + ".bak")
    if out.is_file():
        shutil.copy2(out, bak)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model_out": str(out), "metrics": metrics}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
