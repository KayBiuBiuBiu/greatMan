"""
Forward4 概率工具：时间序列划分、AUC / Brier / 可靠性分箱、Platt 与保序校准、NB+XGB 融合推理。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

_EPS = 1e-9


def sorted_unique_trade_dates(anchor_dates: Iterable[str]) -> list[str]:
    return sorted({str(d)[:10] for d in anchor_dates if d and len(str(d)[:10]) == 10})


def time_series_date_splits(
    anchor_dates: list[str],
    *,
    test_trading_days: int,
    cal_trading_days: int,
) -> tuple[set[str], set[str], set[str]]:
    """
    按锚定日做时间序列划分（全局交易日历为所有样本中出现过的日期排序）。
    返回 (train_dates, cal_dates, test_dates)；cal 紧邻 test 之前，长度为 cal_trading_days（可为 0）。
    """
    uniq = sorted_unique_trade_dates(anchor_dates)
    need_tail = int(test_trading_days) + int(cal_trading_days)
    if len(uniq) < need_tail + 5:
        raise ValueError(
            f"交易日不足：unique={len(uniq)}，需要至少 test+cal+5 = {need_tail + 5}"
        )
    test_dates = set(uniq[-int(test_trading_days) :])
    if int(cal_trading_days) <= 0:
        cal_dates: set[str] = set()
        train_dates = set(uniq[: -int(test_trading_days)])
    else:
        cal_dates = set(uniq[-need_tail : -int(test_trading_days)])
        train_dates = set(uniq[: -need_tail])
    return train_dates, cal_dates, test_dates


def mask_by_dates(anchor_dates: list[str], allowed: set[str]) -> list[bool]:
    return [str(d)[:10] in allowed for d in anchor_dates]


def compute_auc_brier(y_true: list[int], probs: list[float]) -> dict[str, float | None]:
    yt = np.array(y_true, dtype=np.int32)
    pr = np.array(probs, dtype=np.float64)
    out: dict[str, float | None] = {"auc": None, "brier": None}
    if len(yt) < 10 or len(set(yt.tolist())) < 2:
        return out
    try:
        out["auc"] = float(roc_auc_score(yt, pr))
    except ValueError:
        out["auc"] = None
    try:
        out["brier"] = float(brier_score_loss(yt, pr))
    except ValueError:
        out["brier"] = None
    return out


def reliability_bins(
    y_true: list[int],
    probs: list[float],
    *,
    n_bins: int = 10,
) -> list[dict[str, float]]:
    """等宽概率分箱：每箱样本数、均预测、实际正例率。"""
    pr = np.clip(np.array(probs, dtype=np.float64), 0.0, 1.0)
    yt = np.array(y_true, dtype=np.int32)
    bins: list[dict[str, float]] = []
    for i in range(int(n_bins)):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        if i == n_bins - 1:
            m = (pr >= lo) & (pr <= hi + 1e-12)
        else:
            m = (pr >= lo) & (pr < hi)
        cnt = int(m.sum())
        if cnt == 0:
            bins.append(
                {
                    "bin_lo": lo,
                    "bin_hi": hi,
                    "n": 0,
                    "mean_pred": float("nan"),
                    "empirical_rate": float("nan"),
                }
            )
            continue
        bins.append(
            {
                "bin_lo": lo,
                "bin_hi": hi,
                "n": cnt,
                "mean_pred": float(pr[m].mean()),
                "empirical_rate": float(yt[m].mean()),
            }
        )
    return bins


def fit_platt_scaler(probs: list[float], y_true: list[int]) -> dict[str, Any]:
    """Logistic on logit(p)；存储系数供 JSON。"""
    p = np.clip(np.array(probs, dtype=np.float64), _EPS, 1.0 - _EPS)
    logit = np.log(p / (1.0 - p)).reshape(-1, 1)
    y = np.array(y_true, dtype=np.int32)
    lr = LogisticRegression(max_iter=500, solver="lbfgs")
    lr.fit(logit, y)
    return {
        "method": "platt",
        "coef": lr.coef_.tolist(),
        "intercept": lr.intercept_.tolist(),
    }


def apply_platt(p: float, cal: dict[str, Any]) -> float:
    p0 = float(np.clip(p, _EPS, 1.0 - _EPS))
    logit = math.log(p0 / (1.0 - p0))
    coef = float(cal["coef"][0][0])
    icept = float(cal["intercept"][0])
    z = coef * logit + icept
    return float(1.0 / (1.0 + math.exp(-z)))


def fit_isotonic_scaler(probs: list[float], y_true: list[int]) -> dict[str, Any]:
    p = np.clip(np.array(probs, dtype=np.float64), 0.0, 1.0)
    y = np.array(y_true, dtype=np.float64)
    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(p, y)
    xs = ir.X_thresholds_.astype(float).tolist()
    ys = ir.y_thresholds_.astype(float).tolist()
    return {"method": "isotonic", "x_thresholds": xs, "y_thresholds": ys}


def apply_isotonic(p: float, cal: dict[str, Any]) -> float:
    xs = cal["x_thresholds"]
    ys = cal["y_thresholds"]
    if not xs:
        return float(p)
    return float(np.interp(float(p), np.array(xs), np.array(ys)))


def apply_probability_calibration(p: float | None, cal: dict[str, Any] | None) -> float | None:
    if p is None or cal is None:
        return p
    m = str(cal.get("method") or "")
    if m == "platt":
        return apply_platt(p, cal)
    if m == "isotonic":
        return apply_isotonic(p, cal)
    return p


def nb_raw_prob(model: dict[str, Any], feats: dict[str, float]) -> float | None:
    """与 ml_infer.predict_bearish_probability 一致：P(class 1)。"""
    from ml_infer import predict_bearish_probability

    return predict_bearish_probability(model, feats)


def feature_vector_row(feats: dict[str, float], feature_order: list[str]) -> np.ndarray:
    return np.array([float(feats.get(k, 0.0)) for k in feature_order], dtype=np.float64).reshape(
        1, -1
    )


_xgb_cache: dict[str, Any] = {}


def _load_xgb_classifier(path: Path) -> Any:
    key = str(path.resolve())
    if key in _xgb_cache:
        return _xgb_cache[key]
    import joblib

    clf = joblib.load(path)
    _xgb_cache[key] = clf
    return clf


def blended_forward4_probability(
    model: dict[str, Any],
    feats: dict[str, float],
    *,
    model_json_path: Path | None = None,
) -> float | None:
    """
    NB（可选校准）+ 可选 XGBoost 加权。model 为完整 JSON dict；xgb 路径相对 model 文件目录。
    """
    p_nb = nb_raw_prob(model, feats)
    if p_nb is None:
        return None
    cal = model.get("probability_calibration")
    if isinstance(cal, dict) and cal.get("method"):
        p_nb = apply_probability_calibration(p_nb, cal)
        if p_nb is None:
            return None

    rel = model.get("xgb_classifier_relpath")
    if not rel or not str(rel).strip():
        return float(np.clip(p_nb, 0.0, 1.0))

    base = model_json_path.parent if model_json_path is not None else Path.cwd()
    xgb_path = base / str(rel).strip()
    if not xgb_path.is_file():
        return float(np.clip(p_nb, 0.0, 1.0))

    fo = model.get("features")
    if not isinstance(fo, list) or not fo:
        return float(np.clip(p_nb, 0.0, 1.0))
    try:
        clf = _load_xgb_classifier(xgb_path)
        X = feature_vector_row(feats, [str(x) for x in fo])
        if hasattr(clf, "predict_proba"):
            p_x = float(clf.predict_proba(X)[0, 1])
        else:
            return float(np.clip(p_nb, 0.0, 1.0))
    except Exception:
        return float(np.clip(p_nb, 0.0, 1.0))

    xcal = model.get("xgb_probability_calibration")
    if isinstance(xcal, dict) and xcal.get("method"):
        p_x2 = apply_probability_calibration(p_x, xcal)
        if p_x2 is not None:
            p_x = float(p_x2)

    ens = model.get("ensemble_weights") or {}
    try:
        w_nb = float(ens.get("nb", 0.5))
        w_x = float(ens.get("xgb", 0.5))
    except (TypeError, ValueError):
        w_nb, w_x = 0.5, 0.5
    s = w_nb + w_x
    if s <= 0:
        w_nb, w_x = 0.5, 0.5
        s = 1.0
    w_nb, w_x = w_nb / s, w_x / s
    out = w_nb * float(p_nb) + w_x * p_x
    return float(np.clip(out, 0.0, 1.0))


def eval_metrics_dict(
    y_true: list[int],
    probs: list[float],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    m = compute_auc_brier(y_true, probs)
    return {
        "auc": m["auc"],
        "brier": m["brier"],
        "reliability_bins": reliability_bins(y_true, probs, n_bins=n_bins),
    }


def dump_eval_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
