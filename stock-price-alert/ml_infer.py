"""轻量 ML 推理：基于高斯朴素贝叶斯输出 bearish 概率。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

_MODEL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def resolve_model_path(cfg: dict[str, Any], root: Path) -> Path:
    mf = cfg.get("ml_filter") or {}
    rel = str(mf.get("model_path") or "data/ml_bearish_nb.json").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def load_model_cached(model_path: Path) -> dict[str, Any] | None:
    key = str(model_path)
    try:
        mt = model_path.stat().st_mtime
    except OSError:
        return None
    cached = _MODEL_CACHE.get(key)
    if cached and cached[0] == mt:
        return cached[1]
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(model, dict):
        return None
    _MODEL_CACHE[key] = (mt, model)
    return model


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def build_feature_vector(
    *,
    alert_type: str,
    anchor_price: float,
    pnl_pct: float | None = None,
    weak_pillars: dict[str, bool] | None = None,
    dd_level: int | None = None,
    cfg: dict[str, Any] | None = None,
    root: Path | None = None,
    code6: str | None = None,
    anchor_trade_date: str | None = None,
) -> dict[str, float]:
    wp = weak_pillars if isinstance(weak_pillars, dict) else {}
    weak_n = float(sum(1 for v in wp.values() if bool(v)))
    base: dict[str, float] = {
        "anchor_price": max(0.0, _safe_float(anchor_price, 0.0)),
        "pnl_pct": _safe_float(pnl_pct, 0.0),
        "weak_pillars_n": weak_n,
        "dd_level": _safe_float(dd_level, 0.0),
        "is_trend_slip": 1.0 if str(alert_type) == "trend_slip" else 0.0,
        "is_drawdown": 1.0 if str(alert_type) == "drawdown" else 0.0,
    }
    mf = cfg.get("ml_filter") if isinstance(cfg, dict) else None
    if (
        isinstance(mf, dict)
        and bool(mf.get("external_flow_features_enabled"))
        and cfg is not None
        and isinstance(code6, str)
        and code6.strip()
        and isinstance(anchor_trade_date, str)
        and anchor_trade_date.strip()
    ):
        from external_ml_features import compute_external_flow_features

        base.update(
            compute_external_flow_features(
                cfg=cfg,
                code=code6.strip(),
                anchor_trade_date=anchor_trade_date.strip()[:10],
                root=root,
            )
        )
    return base


def predict_bearish_probability(
    model: dict[str, Any],
    feats: dict[str, float],
) -> float | None:
    try:
        features = list(model["features"])
        priors = model["class_priors"]
        stats = model["stats"]
    except Exception:
        return None
    if "0" not in priors or "1" not in priors:
        return None

    s0 = stats.get("0") or {}
    s1 = stats.get("1") or {}

    def _impute_x(f: str) -> float:
        """训练维度在推理向量中缺失时（如未开 external_flow），用两类均值中点，避免全填 0 扭曲分布。"""
        if f in feats:
            return _safe_float(feats.get(f), 0.0)
        m0 = _safe_float((s0.get(f) or {}).get("mean"), 0.0)
        m1 = _safe_float((s1.get(f) or {}).get("mean"), 0.0)
        return 0.5 * (m0 + m1)

    def _eff_var(fname: str, mu: float, var_raw: float) -> float:
        """
        小样训练时方差常被估得过小；实盘特征略出训练簇则两类似然同时崩、概率塌成常数（如下跌概率恒≈0）。
        对方差做温和下限，使价格等尺度特征仍具区分度。
        """
        v = max(1e-12, _safe_float(var_raw, 1e-8))
        if fname == "anchor_price":
            return max(v, 400.0, (max(abs(mu), 5.0) * 0.45) ** 2)
        scale = max(abs(mu), 0.25)
        floor = max(1e-3, (scale * 0.08) ** 2)
        return max(v, floor)

    def _logp(cls: str) -> float:
        p0 = max(1e-12, _safe_float(priors.get(cls), 1e-12))
        s = math.log(p0)
        cls_stats = stats.get(cls) or {}
        for f in features:
            sf = cls_stats.get(f) or {}
            mu = _safe_float(sf.get("mean"), 0.0)
            var = _eff_var(f, mu, _safe_float(sf.get("var"), 1e-4))
            x = _impute_x(f)
            s += -0.5 * math.log(2.0 * math.pi * var) - ((x - mu) ** 2) / (2.0 * var)
        return s

    lp0 = _logp("0")
    lp1 = _logp("1")
    m = max(lp0, lp1)
    p0 = math.exp(lp0 - m)
    p1 = math.exp(lp1 - m)
    den = p0 + p1
    if den <= 0:
        return None
    return p1 / den
