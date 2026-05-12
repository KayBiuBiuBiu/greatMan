#!/usr/bin/env python3
"""训练「T+N 交易日后收涨」模型：高斯 NB，可选时间序列划分、AUC、Platt/保序校准、XGBoost 与融合。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kline_store import init_schema, open_store_connection
from ml_forward4 import (
    FORWARD4_MODEL_KIND,
    FORWARD_UP_HORIZON_TRADING_DAYS,
    iter_labeled_samples_secid_with_anchor,
    list_stock_secids,
    resolve_kline_db_path,
)
from ml_forward4_prob_tools import (
    apply_probability_calibration,
    dump_eval_report,
    eval_metrics_dict,
    fit_isotonic_scaler,
    fit_platt_scaler,
    mask_by_dates,
    nb_raw_prob,
    time_series_date_splits,
)
from ml_train import eval_train_metrics, fit_gaussian_nb
from run_alert import merge_full_config


def _strip_runtime_keys(m: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in m.items() if not str(k).startswith("_")}


def _collect_samples(
    conn: Any,
    secids_use: list[str],
    *,
    min_bars: int,
) -> tuple[list[dict[str, float]], list[int], list[str], list[str]]:
    xs: list[dict[str, float]] = []
    ys: list[int] = []
    ads: list[str] = []
    sids: list[str] = []
    for i, sid in enumerate(secids_use, start=1):
        if i % 500 == 0:
            print(f"[进度] {i}/{len(secids_use)} 已采样本 {len(xs)}", flush=True)
        for fv, y, ad in iter_labeled_samples_secid_with_anchor(
            conn, sid, min_bars=int(min_bars)
        ):
            xs.append(fv)
            ys.append(y)
            ads.append(ad)
            sids.append(sid)
    return xs, ys, ads, sids


def _rows_for_dates(
    xs: list[dict[str, float]],
    ys: list[int],
    ads: list[str],
    allowed: set[str],
) -> tuple[list[dict[str, float]], list[int]]:
    m = mask_by_dates(ads, allowed)
    return [x for x, ok in zip(xs, m) if ok], [y for y, ok in zip(ys, m) if ok]


def _probs_for(model: dict[str, Any], xs: list[dict[str, float]]) -> list[float]:
    out: list[float] = []
    for x in xs:
        p = nb_raw_prob(model, x)
        out.append(float(p) if p is not None else 0.5)
    return out


def _train_xgb(
    xs: list[dict[str, float]],
    ys: list[int],
    feature_names: list[str],
) -> Any:
    try:
        from xgboost import XGBClassifier
    except ImportError as e:
        raise SystemExit("请安装 xgboost：pip install xgboost") from e
    import numpy as np

    X = np.array([[float(row.get(f, 0.0)) for f in feature_names] for row in xs], dtype=np.float64)
    y = np.array(ys, dtype=np.int32)
    clf = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=42,
        n_jobs=-1,
        eval_metric="logloss",
    )
    clf.fit(X, y)
    return clf


def main() -> int:
    ap = argparse.ArgumentParser(
        description="训练 T+N 日收涨 NB（日 K 库 daily_klines），可选 OOS 评估与校准、XGB"
    )
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--model-out",
        type=Path,
        default=ROOT / "data" / "ml_forward4_nb.json",
    )
    ap.add_argument(
        "--min-bars",
        type=int,
        default=120,
        help="单票最少日 K（需能 enrich + 留出 T+N）",
    )
    ap.add_argument(
        "--min-samples",
        type=int,
        default=2000,
        help="全市场合并后最少样本数",
    )
    ap.add_argument(
        "--max-secids",
        type=int,
        default=0,
        help="最多扫描 secid 数，0 不限制",
    )
    ap.add_argument("--threshold", type=float, default=0.50, help="训练集阈值指标")
    ap.add_argument("--report-out", type=Path, default=None)
    ap.add_argument(
        "--test-trading-days",
        type=int,
        default=0,
        help="时间序列测试集：保留最近 N 个交易日为 OOS（0=关闭，仅用全样本训练并打 in-sample 指标）",
    )
    ap.add_argument(
        "--cal-trading-days",
        type=int,
        default=30,
        help="校准集：紧邻测试集之前的 M 个交易日（仅当 --calibrate 非 none 且 test>0）",
    )
    ap.add_argument(
        "--calibrate",
        choices=["none", "platt", "isotonic"],
        default="none",
        help="在校准集上拟合 Platt 或保序回归（NB 仅在更早的训练集上拟合）",
    )
    ap.add_argument(
        "--train-xgb",
        action="store_true",
        help="训练 XGBoost 并写出 joblib（与 NB 融合需配 --ensemble-xgb>0）",
    )
    ap.add_argument(
        "--ensemble-nb",
        type=float,
        default=0.3,
        help="融合权重 NB（有 XGB 时默认 0.3，略偏树模型）",
    )
    ap.add_argument(
        "--ensemble-xgb",
        type=float,
        default=0.7,
        help="融合权重 XGB（默认 0.7）",
    )
    ap.add_argument(
        "--eval-report-out",
        type=Path,
        default=None,
        help="写出 JSON：含 OOS AUC/Brier/可靠性分箱（校准前后）",
    )
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    cfg = merge_full_config(raw)
    db_path = resolve_kline_db_path(cfg, ROOT)
    if not db_path.is_file():
        print(f"日 K 库不存在: {db_path}", file=sys.stderr)
        return 1

    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        secids = list_stock_secids(conn)
    finally:
        conn.close()

    cap = int(args.max_secids) if int(args.max_secids) > 0 else len(secids)
    secids_use = secids[:cap]
    print(
        f"[范围] secid {len(secids_use)} 个（日 K 库中有数据的标的，全库共 {len(secids)}；"
        f"非沪深上市家数，扩库需先同步更多股票日线）",
        flush=True,
    )

    conn = open_store_connection(db_path)
    try:
        init_schema(conn)
        xs, ys, ads, _sids = _collect_samples(conn, secids_use, min_bars=int(args.min_bars))
    finally:
        conn.close()

    if len(xs) < int(args.min_samples):
        print(
            f"样本不足：{len(xs)} < --min-samples {args.min_samples}",
            file=sys.stderr,
        )
        return 1
    if len(set(ys)) < 2:
        print("标签单一，无法训练。", file=sys.stderr)
        return 1

    test_days = int(args.test_trading_days)
    cal_days = int(args.cal_trading_days)
    cal_method = str(args.calibrate)

    oos_report: dict[str, Any] = {}

    cal_blob: dict[str, Any] | None = None

    if test_days > 0:
        train_dates, cal_dates, test_dates = time_series_date_splits(
            ads, test_trading_days=test_days, cal_trading_days=cal_days
        )
        xs_tr, ys_tr = _rows_for_dates(xs, ys, ads, train_dates)
        xs_cal, ys_cal = _rows_for_dates(xs, ys, ads, cal_dates)
        xs_te, ys_te = _rows_for_dates(xs, ys, ads, test_dates)
        if len(xs_tr) < 500 or len(xs_te) < 100:
            print(
                f"划分后样本过少：train={len(xs_tr)} cal={len(xs_cal)} test={len(xs_te)}",
                file=sys.stderr,
            )
            return 1
        if cal_method != "none" and len(xs_cal) < 200:
            print(
                f"[警告] 校准集仅 {len(xs_cal)} 条，保序/Platt 可能不稳；可调小 --test-trading-days 或 --cal-trading-days",
                flush=True,
            )

        if cal_method == "none":
            xs_nb_fit = xs_tr + xs_cal
            ys_nb_fit = ys_tr + ys_cal
        else:
            xs_nb_fit, ys_nb_fit = xs_tr, ys_tr

        model = fit_gaussian_nb(xs_nb_fit, ys_nb_fit)
        p_cal_raw = _probs_for(model, xs_cal) if xs_cal else []
        if cal_method == "platt" and xs_cal:
            cal_blob = fit_platt_scaler(p_cal_raw, ys_cal)
        elif cal_method == "isotonic" and xs_cal:
            cal_blob = fit_isotonic_scaler(p_cal_raw, ys_cal)

        p_te_raw = _probs_for(model, xs_te)
        p_te_cal = [
            apply_probability_calibration(p, cal_blob) if cal_blob else p
            for p in p_te_raw
        ]

        oos_report["split"] = {
            "test_trading_days": test_days,
            "cal_trading_days": cal_days if cal_method != "none" else 0,
            "n_train": len(xs_nb_fit),
            "n_cal": len(xs_cal),
            "n_test": len(xs_te),
        }
        oos_report["test_nb_raw"] = eval_metrics_dict(ys_te, p_te_raw)
        oos_report["test_nb_calibrated"] = (
            eval_metrics_dict(ys_te, p_te_cal) if cal_blob else None
        )
        # 便于 jq / 外部审阅的别名（与 test_* 指向同一评估结果）
        oos_report["nb_raw"] = oos_report["test_nb_raw"]
        oos_report["nb_calibrated"] = oos_report["test_nb_calibrated"]

        xgb_path_saved: str | None = None
        xgb_cal_blob: dict[str, Any] | None = None
        if args.train_xgb:
            clf = _train_xgb(xs_nb_fit, ys_nb_fit, list(model["features"]))
            import joblib

            out_base = args.model_out
            if not out_base.is_absolute():
                out_base = (ROOT / out_base).resolve()
            xgb_out = out_base.with_name(out_base.stem + "_xgb.joblib")
            joblib.dump(clf, xgb_out)
            xgb_path_saved = xgb_out.name
            fo = list(model["features"])
            import numpy as np

            if xs_cal and len(xs_cal) >= 100:
                Xcal = np.array(
                    [[float(row.get(f, 0.0)) for f in fo] for row in xs_cal],
                    dtype=np.float64,
                )
                p_xgb_on_cal = [
                    float(clf.predict_proba(Xcal[i : i + 1])[0, 1]) for i in range(len(xs_cal))
                ]
                xgb_cal_blob = fit_isotonic_scaler(p_xgb_on_cal, ys_cal)

            Xte = np.array(
                [[float(row.get(f, 0.0)) for f in fo] for row in xs_te],
                dtype=np.float64,
            )
            p_xgb = [float(clf.predict_proba(Xte[i : i + 1])[0, 1]) for i in range(len(xs_te))]
            p_xgb_cal = [
                apply_probability_calibration(float(px), xgb_cal_blob) if xgb_cal_blob else float(px)
                for px in p_xgb
            ]
            sn = float(args.ensemble_nb) + float(args.ensemble_xgb)
            wnb = float(args.ensemble_nb) / sn if sn > 0 else 0.5
            wxb = float(args.ensemble_xgb) / sn if sn > 0 else 0.5
            p_nb_for_blend_cal = [float(x) for x in p_te_cal] if cal_blob else [float(x) for x in p_te_raw]
            p_blend_cal = [
                wnb * float(pn) + wxb * float(pxc) for pn, pxc in zip(p_nb_for_blend_cal, p_xgb_cal)
            ]
            p_blend_raw = [wnb * float(pr) + wxb * float(px) for pr, px in zip(p_te_raw, p_xgb)]
            oos_report["test_xgb"] = eval_metrics_dict(ys_te, p_xgb)
            oos_report["test_xgb_calibrated"] = (
                eval_metrics_dict(ys_te, p_xgb_cal) if xgb_cal_blob else None
            )
            oos_report["test_ensemble"] = eval_metrics_dict(ys_te, p_blend_cal)
            oos_report["test_ensemble_raw"] = eval_metrics_dict(ys_te, p_blend_raw)
            oos_report["test_ensemble_calibrated"] = eval_metrics_dict(ys_te, p_blend_cal)
            oos_report["xgb_raw"] = oos_report["test_xgb"]
            oos_report["xgb_calibrated"] = oos_report["test_xgb_calibrated"]
            oos_report["ensemble_raw"] = oos_report["test_ensemble_raw"]
            oos_report["ensemble_calibrated"] = oos_report["test_ensemble_calibrated"]
            model["xgb_classifier_relpath"] = xgb_path_saved
            model["ensemble_weights"] = {"nb": wnb, "xgb": wxb}
            if xgb_cal_blob:
                model["xgb_probability_calibration"] = xgb_cal_blob
    else:
        model = fit_gaussian_nb(xs, ys)
        cal_blob = None
        if args.train_xgb:
            clf = _train_xgb(xs, ys, list(model["features"]))
            import joblib

            out_base = args.model_out
            if not out_base.is_absolute():
                out_base = (ROOT / out_base).resolve()
            xgb_out = out_base.with_name(out_base.stem + "_xgb.joblib")
            joblib.dump(clf, xgb_out)
            model["xgb_classifier_relpath"] = xgb_out.name
            sn = float(args.ensemble_nb) + float(args.ensemble_xgb)
            model["ensemble_weights"] = {
                "nb": float(args.ensemble_nb) / sn if sn > 0 else 0.5,
                "xgb": float(args.ensemble_xgb) / sn if sn > 0 else 0.5,
            }

    model["model_kind"] = FORWARD4_MODEL_KIND
    h = int(FORWARD_UP_HORIZON_TRADING_DAYS)
    model["label_meaning"] = {
        "0": f"close_T_plus_{h}_le_close_T",
        "1": f"close_T_plus_{h}_gt_close_T",
    }
    model["horizon_trading_days"] = h
    model["feature_set"] = "enrich_ohlcv_6"
    model["kline_db"] = str(db_path)
    th = max(0.0, min(1.0, float(args.threshold)))
    if test_days > 0:
        model["train_metrics"] = eval_train_metrics(model, xs_nb_fit, ys_nb_fit, threshold=th)
    else:
        model["train_metrics"] = eval_train_metrics(model, xs, ys, threshold=th)
    model["train_secids_scanned"] = len(secids_use)

    if cal_blob:
        model["probability_calibration"] = cal_blob

    if oos_report:
        model["oos_eval"] = oos_report

    out = args.model_out
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    to_save = _strip_runtime_keys(model)
    out.write_text(json.dumps(to_save, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mtr = model["train_metrics"]
    print(f"✅ 模型已写出: {out}")
    print(
        f"样本(拟合集)={model['n_samples']} 涨占比={model['class_priors']['1']:.2%} "
        f"acc={mtr['accuracy']:.2%} prec={mtr['precision']:.2%} rec={mtr['recall']:.2%}",
        flush=True,
    )
    if oos_report:
        tr = oos_report.get("test_nb_raw") or {}
        tc = oos_report.get("test_nb_calibrated")
        print(
            f"[OOS] NB raw  AUC={tr.get('auc')} Brier={tr.get('brier')}",
            flush=True,
        )
        if tc:
            print(
                f"[OOS] NB+cal AUC={tc.get('auc')} Brier={tc.get('brier')}",
                flush=True,
            )
        tx = oos_report.get("test_xgb")
        if tx:
            print(
                f"[OOS] XGB raw  AUC={tx.get('auc')} Brier={tx.get('brier')}",
                flush=True,
            )
        txc = oos_report.get("test_xgb_calibrated")
        if txc:
            print(
                f"[OOS] XGB+cal AUC={txc.get('auc')} Brier={txc.get('brier')}",
                flush=True,
            )
        ter = oos_report.get("test_ensemble_raw")
        if ter:
            print(
                f"[OOS] Ensemble raw (NB+XGB) AUC={ter.get('auc')} Brier={ter.get('brier')}",
                flush=True,
            )
        te = oos_report.get("test_ensemble_calibrated") or oos_report.get("test_ensemble")
        if te:
            print(
                f"[OOS] Ensemble cal AUC={te.get('auc')} Brier={te.get('brier')}",
                flush=True,
            )

    if args.eval_report_out:
        rp = args.eval_report_out
        if not rp.is_absolute():
            rp = (ROOT / rp).resolve()
        dump_eval_report(rp, oos_report if oos_report else {"note": "no OOS (--test-trading-days 0)"})

    if args.report_out:
        rp = args.report_out
        if not rp.is_absolute():
            rp = (ROOT / rp).resolve()
        rp.write_text(
            json.dumps(
                {
                    "model_path": str(out),
                    "n_samples": model["n_samples"],
                    "class_priors": model["class_priors"],
                    "metrics": mtr,
                    "oos": oos_report if oos_report else None,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"📝 报告: {rp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
