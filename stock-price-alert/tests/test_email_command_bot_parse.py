from __future__ import annotations

from email_command_bot import _parse_runtime_commands


def test_parse_sell_command_variants() -> None:
    cmds = _parse_runtime_commands("回复", "600711编号卖出\n另一个：卖出 000537")
    assert "sell 600711" in cmds
    assert "sell 000537" in cmds


def test_parse_buy_with_position_and_cost() -> None:
    cmds = _parse_runtime_commands("交易回执", "买入600711 300 10.25")
    assert any(c.startswith("hold 600711 300 ") for c in cmds)


def test_parse_buy_watch_only_when_no_position_fields() -> None:
    cmds = _parse_runtime_commands("买入指令", "001258编号买入")
    assert "hold 001258" in cmds
