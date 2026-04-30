from __future__ import annotations

from ml_infer import build_feature_vector, predict_bearish_probability


def test_predict_bearish_probability_monotonic() -> None:
    model = {
        "features": ["pnl_pct", "weak_pillars_n", "is_trend_slip"],
        "class_priors": {"0": 0.5, "1": 0.5},
        "stats": {
            "0": {
                "pnl_pct": {"mean": 2.0, "var": 1.0},
                "weak_pillars_n": {"mean": 0.5, "var": 0.5},
                "is_trend_slip": {"mean": 1.0, "var": 0.1},
            },
            "1": {
                "pnl_pct": {"mean": -3.0, "var": 1.0},
                "weak_pillars_n": {"mean": 2.5, "var": 0.5},
                "is_trend_slip": {"mean": 1.0, "var": 0.1},
            },
        },
    }
    weak_case = build_feature_vector(
        alert_type="trend_slip",
        anchor_price=10.0,
        pnl_pct=-4.0,
        weak_pillars={"stock": True, "index": True, "sector": True},
    )
    strong_case = build_feature_vector(
        alert_type="trend_slip",
        anchor_price=10.0,
        pnl_pct=1.0,
        weak_pillars={"stock": False, "index": False, "sector": False},
    )
    p_weak = predict_bearish_probability(model, weak_case)
    p_strong = predict_bearish_probability(model, strong_case)
    assert p_weak is not None and p_strong is not None
    assert p_weak > p_strong
    assert 0.0 <= p_weak <= 1.0
