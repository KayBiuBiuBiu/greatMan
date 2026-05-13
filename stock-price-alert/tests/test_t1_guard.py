"""t1_guard：策略买卖提示与终端 buy/add、sell/reduce 收束。"""

from __future__ import annotations

from datetime import date

import pytest

from t1_guard import (
    ack_cli_position_buy_add,
    ack_cli_position_sell_reduce,
    commit_strategy_emit,
    plan_strategy_t1,
    shanghai_today,
)


def _fake_state() -> dict:
    return {"t1_by_code": {}}


def test_buy_signal_repeats_same_day_until_cli_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("t1_guard.shanghai_today", lambda: date(2026, 5, 13))
    code = "600711"
    sig = "【买入信号】测试"
    st = _fake_state()
    commit_strategy_emit(code, "buy", st)
    p1 = plan_strategy_t1(code, sig, st)
    assert p1.show_line is True
    assert p1.suppressed_duplicate_buy is False
    ack_cli_position_buy_add(code, st)
    p2 = plan_strategy_t1(code, sig, st)
    assert p2.show_line is False
    assert p2.suppressed_duplicate_buy is True


def test_sell_signal_repeats_until_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("t1_guard.shanghai_today", lambda: date(2026, 5, 13))
    code = "000537"
    sig = "【卖出信号】测试"
    st = _fake_state()
    commit_strategy_emit(code, "sell", st)
    p1 = plan_strategy_t1(code, sig, st)
    assert p1.show_line is True
    ack_cli_position_sell_reduce(code, st)
    p2 = plan_strategy_t1(code, sig, st)
    assert p2.show_line is False


def test_buy_ack_cleared_when_signal_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("t1_guard.shanghai_today", lambda: date(2026, 5, 13))
    code = "600000"
    st = _fake_state()
    commit_strategy_emit(code, "buy", st)
    ack_cli_position_buy_add(code, st)
    ent = st["t1_by_code"][code]
    assert "cli_buy_add_ack_date" in ent
    ent.pop("cli_buy_add_ack_date", None)
    p = plan_strategy_t1(code, "【买入信号】x", st)
    assert p.show_line is True
