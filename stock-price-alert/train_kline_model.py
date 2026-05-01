#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于全量日 K（SQLite 单表）训练「未来 N 交易日大跌」二分类模型。

默认使用与趋势预警更贴近的特征集（TREND_FEATURE_COLUMNS）+ 可选 StandardScaler；
也可用 --feature-set legacy 训练旧版 6 列特征。

用法:
  python train_kline_model.py --db data/baostock_full.db --sample-codes 100 --model models/kline_rf_test.pkl
  python train_kline_model.py --db data/baostock_full.db --model models/kline_rf_full.pkl
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_kline_features import (
    FEATURE_COLUMNS,
    TREND_FEATURE_COLUMNS,
    add_forward_down_label,
    build_trend_frame_with_label,
)


def main() -> int:
    import pandas as pd
    import sqlite3

    try:
        import joblib
    except ImportError:
        print("需要 joblib：pip install joblib", file=sys.stderr)
        return 1
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import classification_report
        from sklearn.metrics import roc_auc_score
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        print("需要 scikit-learn：pip install scikit-learn", file=sys.stderr)
        return 1

    try:
        from tqdm import tqdm
    except ImportError:

        def tqdm(x, **kwargs):
            return x

    ap = argparse.ArgumentParser(description="日 K 合并库 -> 随机森林 / XGBoost")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "baostock_full.db")
    ap.add_argument("--table", type=str, default="daily_klines")
    ap.add_argument(
        "--model",
        type=Path,
        default=ROOT / "models" / "kline_rf_full.pkl",
        help="输出 joblib bundle（model + features + 可选 scaler）",
    )
    ap.add_argument(
        "--feature-set",
        choices=("trend", "legacy"),
        default="trend",
        help="trend=均线/放量/MACD/上影等 9 列；legacy=旧版 6 列连续特征",
    )
    ap.add_argument("--test-size", type=float, default=0.2)
    ap.add_argument("--sample-codes", type=int, default=0, help="只处理前 N 只股票，0 为全量")
    ap.add_argument("--forward-days", type=int, default=5)
    ap.add_argument(
        "--label-threshold-pct",
        type=float,
        default=-3.0,
        help="未来收益低于该%%为阳性标签",
    )
    ap.add_argument(
        "--min-rows-per-code",
        type=int,
        default=0,
        help="每票最少行数；0 表示按特征集自动（trend=60, legacy=50）",
    )
    ap.add_argument("--min-clean-rows", type=int, default=10)
    ap.add_argument("--algo", choices=("rf", "xgb"), default="rf")
    ap.add_argument("--n-estimators", type=int, default=100)
    ap.add_argument("--max-depth", type=int, default=10)
    ap.add_argument("--random-state", type=int, default=42)
    ap.add_argument(
        "--no-scaler",
        action="store_true",
        help="不对特征做 StandardScaler（树模型通常不需要）",
    )
    args = ap.parse_args()

    tbl = str(args.table).strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", tbl):
        print("表名只允许字母数字下划线", file=sys.stderr)
        return 1

    trend_mode = str(args.feature_set).strip().lower() == "trend"
    features = list(TREND_FEATURE_COLUMNS if trend_mode else FEATURE_COLUMNS)
    min_rows = int(args.min_rows_per_code) or (60 if trend_mode else 50)

    db_path = args.db.resolve()
    if not db_path.is_file():
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        print("请先运行 merge_hist_csv_to_sqlite.py 合并 CSV。", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        ok = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
            (tbl,),
        ).fetchone()
        if not ok:
            print(f'错误: 数据库中不存在表 "{tbl}"', file=sys.stderr)
            try:
                rel_db = db_path.relative_to(ROOT)
            except ValueError:
                rel_db = db_path
            print(
                "请先将 data/historical/*.csv 合并进该库，例如:\n"
                f"  python merge_hist_csv_to_sqlite.py --db-path {rel_db} "
                f"--table {tbl} --replace",
                file=sys.stderr,
            )
            return 1
        codes = pd.read_sql_query(
            f'SELECT DISTINCT code FROM "{tbl}" ORDER BY code', conn
        )["code"].astype(str).tolist()
    finally:
        conn.close()

    if args.sample_codes and args.sample_codes > 0:
        codes = codes[: int(args.sample_codes)]
    print(f"标的数: {len(codes)} 表={tbl} 特征集={args.feature_set} min_rows={min_rows}")

    frames: list[pd.DataFrame] = []

    for code in tqdm(codes, desc="处理股票"):
        c6 = str(code).strip().zfill(6)
        conn = sqlite3.connect(str(db_path))
        try:
            df = pd.read_sql_query(
                f'''
                SELECT trade_date, open, high, low, close, volume
                FROM "{tbl}"
                WHERE code = ?
                ORDER BY trade_date ASC
                ''',
                conn,
                params=(c6,),
            )
        finally:
            conn.close()
        if df is None or len(df) < min_rows:
            continue
        if trend_mode:
            tagged = build_trend_frame_with_label(
                df,
                forward_days=int(args.forward_days),
                threshold_pct=float(args.label_threshold_pct),
            )
        else:
            tagged = add_forward_down_label(
                df,
                forward_days=int(args.forward_days),
                threshold_pct=float(args.label_threshold_pct),
            )
        block = tagged[features + ["trade_date", "label"]].dropna()
        if len(block) < int(args.min_clean_rows):
            continue
        frames.append(block)

    if not frames:
        print("无有效样本，请检查表名/列名或降低 min_rows。", file=sys.stderr)
        return 1

    full = pd.concat(frames, ignore_index=True)
    full = full.sort_values("trade_date")
    cut = int(len(full) * (1.0 - float(args.test_size)))
    cut = max(1, min(cut, len(full) - 1))
    train_df = full.iloc[:cut]
    test_df = full.iloc[cut:]
    X_train = train_df[features]
    y_train = train_df["label"].astype(int)
    X_test = test_df[features]
    y_test = test_df["label"].astype(int)

    print(
        f"总样本 {len(full)} 时间切分 train={len(X_train)} test={len(X_test)} "
        f"正例占比 train={y_train.mean():.3f} test={y_test.mean():.3f}"
    )

    if y_train.nunique() < 2:
        print("训练集标签单一，无法训练。", file=sys.stderr)
        return 1

    rs = int(args.random_state)
    use_scaler = not bool(args.no_scaler)
    scaler = StandardScaler() if use_scaler else None
    if use_scaler:
        X_train_f = scaler.fit_transform(X_train)
        X_test_f = scaler.transform(X_test)
    else:
        X_train_f = X_train.to_numpy()
        X_test_f = X_test.to_numpy()

    if args.algo == "xgb":
        try:
            from xgboost import XGBClassifier

            clf = XGBClassifier(
                n_estimators=int(args.n_estimators),
                max_depth=int(args.max_depth),
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=rs,
                n_jobs=-1,
                tree_method="hist",
            )
        except ImportError:
            print("未安装 xgboost，请 pip install xgboost 或改用 --algo rf", file=sys.stderr)
            return 1
    else:
        clf = RandomForestClassifier(
            n_estimators=int(args.n_estimators),
            max_depth=int(args.max_depth),
            random_state=rs,
            n_jobs=-1,
        )

    clf.fit(X_train_f, y_train)
    y_pred = clf.predict(X_test_f)
    print("\n分类报告:")
    print(classification_report(y_test, y_pred, digits=3))
    if y_test.nunique() >= 2:
        try:
            y_prob = clf.predict_proba(X_test_f)[:, 1]
            auc = roc_auc_score(y_test, y_prob)
            print(f"AUC: {auc:.4f}")
        except Exception as exc:
            print(f"AUC 跳过: {exc}", file=sys.stderr)

    args.model.parent.mkdir(parents=True, exist_ok=True)
    bundle: dict = {
        "model": clf,
        "features": features,
        "feature_set": str(args.feature_set),
        "min_bars": min_rows,
        "forward_days": int(args.forward_days),
        "label_threshold_pct": float(args.label_threshold_pct),
        "algo": str(args.algo),
        "db_hint": str(db_path),
        "table": tbl,
        "use_scaler": use_scaler,
    }
    if use_scaler and scaler is not None:
        bundle["scaler"] = scaler
    joblib.dump(bundle, args.model)
    print(f"已保存: {args.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
