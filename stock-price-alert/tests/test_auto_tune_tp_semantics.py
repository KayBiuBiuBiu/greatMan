"""auto_tune_accuracy：止盈 hit 语义随回测命中率自动切换（可选）。"""

from __future__ import annotations

from auto_tune_accuracy import _risk_stop_take_profit_semantics_changes


def test_tp_semantics_disabled_by_default() -> None:
    cfg: dict = {"alert_log": {"risk_stop_take_eval": {"take_profit_hit_for_correctness": 1}}}
    report = {
        "by_alert_type": {
            "risk_stop_take": {"n": 100, "n_hit_scored": 100, "hit_rate": 0.0},
        }
    }
    assert _risk_stop_take_profit_semantics_changes(cfg, report["by_alert_type"]) == []


def test_tp_semantics_switch_to_legacy_when_hr_low() -> None:
    cfg: dict = {
        "auto_tune": {
            "take_profit_semantics_auto": True,
            "take_profit_semantics_min_samples": 20,
            "take_profit_hr_switch_to_legacy": 0.15,
        },
        "alert_log": {"risk_stop_take_eval": {"take_profit_hit_for_correctness": 1}},
    }
    by_type = {
        "risk_stop_take": {"n": 50, "n_hit_scored": 50, "hit_rate": 0.0},
    }
    ch = _risk_stop_take_profit_semantics_changes(cfg, by_type)
    assert len(ch) == 1
    assert ch[0].new == 0
    assert cfg["alert_log"]["risk_stop_take_eval"]["take_profit_hit_for_correctness"] == 0.0


def test_tp_semantics_switch_to_correctness_when_hr_high() -> None:
    cfg: dict = {
        "auto_tune": {
            "take_profit_semantics_auto": True,
            "take_profit_semantics_min_samples": 10,
            "take_profit_hr_switch_to_correctness": 0.70,
        },
        "alert_log": {"risk_stop_take_eval": {"take_profit_hit_for_correctness": 0}},
    }
    by_type = {
        "risk_stop_take": {"n": 30, "n_hit_scored": 30, "hit_rate": 0.95},
    }
    ch = _risk_stop_take_profit_semantics_changes(cfg, by_type)
    assert len(ch) == 1
    assert ch[0].new == 1
