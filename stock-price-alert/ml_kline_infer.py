# -*- coding: utf-8 -*-
"""加载 train_kline_model 导出的 bundle，从 SQLite 日 K 推断「未来下跌」正类概率。"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_MODEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _safe_table(name: str) -> str | None:
    s = str(name).strip()
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
        return s
    return None


def resolve_kline_model_path(cfg: dict[str, Any], root: Path) -> Path:
    mf = cfg.get("ml_filter") or {}
    rel = str(mf.get("kline_rf_model_path") or "models/kline_rf.pkl").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def resolve_kline_db_path(cfg: dict[str, Any], root: Path) -> Path:
    mf = cfg.get("ml_filter") or {}
    rel = str(mf.get("kline_rf_db_path") or "data/baostock_full.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def load_kline_rf_bundle(model_path: Path) -> dict[str, Any] | None:
    key = str(model_path)
    try:
        mt = model_path.stat().st_mtime
    except OSError:
        return None
    hit = _MODEL_CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        import joblib
    except ImportError:
        return None
    try:
        raw = joblib.load(model_path)
    except Exception:
        return None
    if not isinstance(raw, dict) or "model" not in raw:
        return None
    _MODEL_CACHE[key] = (mt, raw)
    return raw


def _positive_class_proba(clf: Any, X: Any) -> float | None:
    try:
        proba = clf.predict_proba(X)[0]
        classes = list(getattr(clf, "classes_", []))
    except Exception:
        return None
    if 1 in classes:
        return float(proba[classes.index(1)])
    if len(proba) >= 2:
        return float(proba[1])
    return float(proba[0]) if len(proba) else None


def _feature_rows_for_infer(df, bundle: dict[str, Any]):
    """返回 (enriched_df, feat_list)；列顺序与训练时 bundle['features'] 一致。"""
    from ml_kline_features import (
        FEATURE_COLUMNS,
        TREND_FEATURE_COLUMNS,
        compute_trend_aligned_features,
        enrich_ohlcv,
    )

    raw = (
        bundle.get("features")
        or bundle.get("feature_cols")
        or bundle.get("feature_columns")
        or []
    )
    feat_list = [str(x) for x in raw if str(x).strip()]
    fset = str(bundle.get("feature_set") or "").strip().lower()

    legacy_set = set(FEATURE_COLUMNS)
    trend_set = set(TREND_FEATURE_COLUMNS)
    if not feat_list:
        feat_list = list(FEATURE_COLUMNS if fset == "legacy" else TREND_FEATURE_COLUMNS)

    if fset == "legacy" or (set(feat_list) == legacy_set and len(feat_list) == len(FEATURE_COLUMNS)):
        enriched = enrich_ohlcv(df)
        feat_list = list(FEATURE_COLUMNS)
    elif set(feat_list) == trend_set and len(feat_list) == len(TREND_FEATURE_COLUMNS):
        enriched = compute_trend_aligned_features(df)
        feat_list = list(raw)
    else:
        enriched = compute_trend_aligned_features(df)
        feat_list = list(TREND_FEATURE_COLUMNS)

    missing = [f for f in feat_list if f not in enriched.columns]
    if missing:
        return None, []
    return enriched, feat_list


def predict_decline_probability(
    *,
    db_path: Path,
    table: str,
    code6: str,
    anchor_trade_date: str,
    bundle: dict[str, Any],
) -> float | None:
    """取 anchor_trade_date 及之前日 K，用最后一根可用完整特征 bar 推断 P(label=1)。"""
    import pandas as pd

    tbl = _safe_table(table)
    if tbl is None or not db_path.is_file():
        return None
    c6 = str(code6).strip().zfill(6)
    if len(c6) != 6 or not c6.isdigit():
        return None
    ad = str(anchor_trade_date).strip()[:10]
    if len(ad) != 10:
        return None

    clf = bundle.get("model")
    if clf is None:
        return None

    q = f'''
        SELECT trade_date, open, high, low, close, volume
        FROM "{tbl}"
        WHERE code = ? AND trade_date <= ?
        ORDER BY trade_date ASC
    '''
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            df = pd.read_sql_query(q, conn, params=(c6, ad))
        finally:
            conn.close()
    except Exception:
        return None

    if df is None or len(df) < int(bundle.get("min_bars", 50)):
        return None

    enriched, feat_list = _feature_rows_for_infer(df, bundle)
    if enriched is None or not feat_list:
        return None

    tail = enriched[feat_list].dropna()
    if tail.empty:
        return None
    row = tail.iloc[-1:][feat_list]
    X = row.to_numpy()
    use_scaler = bool(bundle.get("use_scaler", False)) and bundle.get("scaler") is not None
    if use_scaler:
        try:
            X = bundle["scaler"].transform(row)
        except Exception:
            return None
    return _positive_class_proba(clf, X)
