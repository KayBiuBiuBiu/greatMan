"""技术特征 K-means 聚类选股（cluster_pick_quality_rows）。"""

from __future__ import annotations

import pytest

from quant_core.selector import cluster_pick_quality_rows, technical_features_from_df


def _tf(low: bool) -> dict:
    base = {
        "volatility_20d": 0.01 if low else 0.08,
        "momentum_20d": -0.02 if low else 0.12,
        "momentum_5d": -0.01 if low else 0.03,
        "volume_ratio_5_20": 0.9 if low else 1.8,
        "range_pct_20d": 0.04 if low else 0.15,
    }
    return base


def test_cluster_pick_disabled():
    rows = [{"code": "1", "score": 8.0, "tech_features": _tf(True)}]
    out, st = cluster_pick_quality_rows(rows, qs={"cluster_pool": {"enabled": False}})
    assert out == rows
    assert st["mode"] == "off"


def test_cluster_pick_one_per_cluster():
    pytest.importorskip("sklearn.cluster", reason="需要 scikit-learn")
    rows = [
        {"code": "000001", "score": 8.0, "tech_features": _tf(True)},
        {"code": "000002", "score": 7.5, "tech_features": _tf(True)},
        {"code": "600000", "score": 8.5, "tech_features": _tf(False)},
        {"code": "600001", "score": 7.0, "tech_features": _tf(False)},
    ]
    qs = {
        "score_min_quality": 6.5,
        "cluster_pool": {
            "enabled": True,
            "n_clusters": 2,
            "picks_per_cluster": 1,
            "max_stocks": 10,
        },
    }
    out, st = cluster_pick_quality_rows(rows, qs=qs, cfg={})
    assert st["mode"] == "kmeans"
    assert st["n_clusters_used"] == 2
    codes = {r["code"] for r in out}
    assert codes == {"000001", "600000"}
    assert all("kmeans_cluster" in r for r in out)
    assert all("tech_features" not in r for r in out)


def test_cluster_degraded_without_features():
    rows = [{"code": "1", "score": 8.0}]
    qs = {"cluster_pool": {"enabled": True, "n_clusters": 4}}
    out, st = cluster_pick_quality_rows(rows, qs=qs)
    assert st["mode"] == "degraded_too_few_features"
    assert out == rows


def test_technical_features_from_df_none_on_short():
    import pandas as pd

    df = pd.DataFrame({"close": [1.0] * 10, "high": [1.1] * 10, "low": [0.9] * 10, "volume": [1e6] * 10})
    assert technical_features_from_df(df) is None
