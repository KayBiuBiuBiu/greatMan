"""全失败轮次与趋势抑制状态机（与 run_alert.apply_poll_outage_state_mutations 对齐）。"""

from __future__ import annotations

from run_alert import apply_poll_outage_state_mutations


def test_full_outage_increments_streak_and_sets_suppress() -> None:
    state: dict = {}
    dh = {"suppress_trend_rounds_after_full_outage": 3}
    apply_poll_outage_state_mutations(state, full_outage=True, dh_cfg=dh)
    assert state["__full_outage_streak__"] == 1
    assert state["__trend_suppress_rounds__"] == 3
    apply_poll_outage_state_mutations(state, full_outage=True, dh_cfg=dh)
    assert state["__full_outage_streak__"] == 2
    assert state["__trend_suppress_rounds__"] == 3


def test_success_round_decrements_suppress_and_clears_streak() -> None:
    state = {
        "__full_outage_streak__": 2,
        "__trend_suppress_rounds__": 3,
        "__full_outage_escalated_sent__": True,
    }
    dh = {"suppress_trend_rounds_after_full_outage": 3}
    old = apply_poll_outage_state_mutations(state, full_outage=False, dh_cfg=dh)
    assert old == 2
    assert state["__full_outage_streak__"] == 0
    assert state["__trend_suppress_rounds__"] == 2
    assert "__full_outage_escalated_sent__" not in state


def test_suppress_zero_leaves_counter_unset_on_first_outage() -> None:
    state = {}
    dh = {"suppress_trend_rounds_after_full_outage": 0}
    apply_poll_outage_state_mutations(state, full_outage=True, dh_cfg=dh)
    assert state["__full_outage_streak__"] == 1
    assert "__trend_suppress_rounds__" not in state
