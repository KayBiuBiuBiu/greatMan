"""ml_forward4 选股降档门槛（优质→观察、观察→淘汰）。"""

from __future__ import annotations

from quant_core.selector import _apply_ml_forward4_select_gate


def _base_cfg() -> dict:
    return {
        "ml_forward4": {
            "enabled": True,
            "select_gate_enabled": True,
            "select_min_up_prob_quality": 0.5,
            "select_min_up_prob_watch": 0.4,
            "select_strict_no_prob": False,
        }
    }


def test_gate_quality_to_watch_when_below_threshold() -> None:
    cfg = _base_cfg()
    row = {
        "code": "000001",
        "name": "测试",
        "score": 8.0,
        "reason": "因子与回测双重达标",
        "ml_forward4_up_prob": 0.35,
    }
    b, r = _apply_ml_forward4_select_gate(cfg, "优质股", row)
    assert b == "观察股"
    assert r.get("ml_forward4_gate") == "quality_to_watch"
    assert "优质降观察" in str(r.get("reason"))


def test_gate_quality_unchanged_when_above_threshold() -> None:
    cfg = _base_cfg()
    row = {
        "code": "000001",
        "name": "测试",
        "score": 8.0,
        "reason": "因子与回测双重达标",
        "ml_forward4_up_prob": 0.55,
    }
    b, r = _apply_ml_forward4_select_gate(cfg, "优质股", row)
    assert b == "优质股"
    assert "ml_forward4_gate" not in r


def test_gate_watch_to_reject_when_below_threshold() -> None:
    cfg = _base_cfg()
    row = {
        "code": "000002",
        "name": "测试二",
        "score": 6.0,
        "sw_l1": "",
        "backtest": {},
        "reason": "基本达标，建议继续跟踪",
        "ml_forward4_up_prob": 0.35,
    }
    b, r = _apply_ml_forward4_select_gate(cfg, "观察股", row)
    assert b == "淘汰股"
    assert r.get("ml_forward4_gate") == "watch_to_reject"
    assert "观察降淘汰" in str(r.get("reason"))
    assert r.get("backtest") == {}


def test_gate_disabled_noop() -> None:
    cfg = _base_cfg()
    cfg["ml_forward4"]["select_gate_enabled"] = False
    row = {"reason": "x", "ml_forward4_up_prob": 0.1}
    b, r = _apply_ml_forward4_select_gate(cfg, "优质股", row)
    assert b == "优质股"


def test_strict_no_prob_demotes_quality() -> None:
    cfg = _base_cfg()
    cfg["ml_forward4"]["select_strict_no_prob"] = True
    row = {
        "code": "1",
        "name": "n",
        "score": 8.0,
        "reason": "因子与回测双重达标",
    }
    b, r = _apply_ml_forward4_select_gate(cfg, "优质股", row)
    assert b == "观察股"
    assert r.get("ml_forward4_gate") == "quality_to_watch"


def test_reject_bucket_unchanged() -> None:
    cfg = _base_cfg()
    rej = {"code": "9", "name": "x", "score": 3.0, "reason": "弱"}
    b, r = _apply_ml_forward4_select_gate(cfg, "淘汰股", rej)
    assert b == "淘汰股"
    assert r == rej
