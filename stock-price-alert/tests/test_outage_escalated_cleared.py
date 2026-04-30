"""全失败恢复时 escalated 标记应被清理。"""

from __future__ import annotations

from run_alert import apply_poll_outage_state_mutations


def test_recovery_clears_full_outage_escalated_sent() -> None:
    state = {
        "__full_outage_streak__": 2,
        "__full_outage_escalated_sent__": True,
        "__trend_suppress_rounds__": 1,
    }
    dh = {"suppress_trend_rounds_after_full_outage": 3}
    apply_poll_outage_state_mutations(state, full_outage=False, dh_cfg=dh)
    assert state["__full_outage_streak__"] == 0
    assert "__full_outage_escalated_sent__" not in state
    assert state["__trend_suppress_rounds__"] == 0
