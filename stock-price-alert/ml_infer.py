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
) -> dict[str, float]:
    wp = weak_pillars if isinstance(weak_pillars, dict) else {}
    weak_n = float(sum(1 for v in wp.values() if bool(v)))
    return {
        "anchor_price": max(0.0, _safe_float(anchor_price, 0.0)),
        "pnl_pct": _safe_float(pnl_pct, 0.0),
        "weak_pillars_n": weak_n,
        "dd_level": _safe_float(dd_level, 0.0),
        "is_trend_slip": 1.0 if str(alert_type) == "trend_slip" else 0.0,
        "is_drawdown": 1.0 if str(alert_type) == "drawdown" else 0.0,
    }


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

    def _logp(cls: str) -> float:
        p0 = max(1e-12, _safe_float(priors.get(cls), 1e-12))
        s = math.log(p0)
        cls_stats = stats.get(cls) or {}
        for f in features:
            sf = cls_stats.get(f) or {}
            mu = _safe_float(sf.get("mean"), 0.0)
            var = max(1e-8, _safe_float(sf.get("var"), 1e-4))
            x = _safe_float(feats.get(f), 0.0)
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
