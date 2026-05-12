"""ml_forward4 选股门槛按情绪解析。"""

from __future__ import annotations

import pytest

from ml_forward4_select_resolve import (
    effective_select_thresholds,
    resolve_ml_forward4_for_daily_select,
)


def test_resolve_adaptive_off_returns_copy_no_tier() -> None:
    cfg = {
        "ml_forward4": {
            "enabled": True,
            "select_gate_enabled": True,
            "select_min_up_prob_quality": 0.42,
            "select_adaptive_by_mood": {"enabled": False},
        }
    }
    m, tier = resolve_ml_forward4_for_daily_select(cfg)
    assert tier is None
    assert m is not None
    assert m["select_min_up_prob_quality"] == 0.42


def test_resolve_weak_bear_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import macro_risk as mr

    monkeypatch.setattr(mr, "get_market_mood_three_tier", lambda dynamic_cfg=None: "weak_bear")
    cfg = {
        "macro_risk": {"ma_period": 20},
        "ml_forward4": {
            "enabled": True,
            "select_gate_enabled": True,
            "select_min_up_prob_quality": 0.42,
            "select_min_up_prob_watch": 0.36,
            "select_adaptive_by_mood": {
                "enabled": True,
                "weak_bear": {
                    "select_min_up_prob_quality": 0.52,
                    "select_min_up_prob_watch": 0.44,
                },
                "strong_bull": {},
                "range": {},
            },
        },
    }
    m, tier = resolve_ml_forward4_for_daily_select(cfg)
    assert tier == "weak_bear"
    assert m is not None
    assert m["select_min_up_prob_quality"] == 0.52
    assert m["select_min_up_prob_watch"] == 0.44


def test_resolve_range_empty_uses_base(monkeypatch: pytest.MonkeyPatch) -> None:
    import macro_risk as mr

    monkeypatch.setattr(mr, "get_market_mood_three_tier", lambda dynamic_cfg=None: "range")
    cfg = {
        "ml_forward4": {
            "enabled": True,
            "select_min_up_prob_quality": 0.42,
            "select_min_up_prob_watch": 0.36,
            "select_adaptive_by_mood": {
                "enabled": True,
                "strong_bull": {"select_min_up_prob_quality": 0.35},
                "range": {},
                "weak_bear": {"select_min_up_prob_quality": 0.55},
            },
        }
    }
    m, tier = resolve_ml_forward4_for_daily_select(cfg)
    assert tier == "range"
    assert m["select_min_up_prob_quality"] == 0.42
    assert m["select_min_up_prob_watch"] == 0.36


def test_effective_select_thresholds() -> None:
    eff = effective_select_thresholds(
        {"select_min_up_prob_quality": 0.4, "select_strict_no_prob": True}
    )
    assert eff["select_min_up_prob_quality"] == 0.4
    assert eff["select_min_up_prob_watch"] is None
    assert eff["select_strict_no_prob"] is True
