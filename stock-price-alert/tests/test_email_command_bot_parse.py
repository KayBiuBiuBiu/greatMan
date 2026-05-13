from __future__ import annotations

from email_command_bot import _parse_config_commands, _parse_runtime_commands


def test_parse_sell_command_variants() -> None:
    cmds = _parse_runtime_commands("回复", "600711编号卖出\n另一个：卖出 000537")
    assert "pause 600711" in cmds
    assert "pause 000537" in cmds


def test_parse_sell_partial_with_qty() -> None:
    cmds = _parse_runtime_commands("", "卖出600711 500股\nsell 000537 200")
    assert "sell 600711 500" in cmds
    assert "sell 000537 200" in cmds
    assert "sell 600711" not in cmds


def test_parse_buy_with_position_and_cost() -> None:
    cmds = _parse_runtime_commands("交易回执", "买入600711 300 10.25")
    assert any(c.startswith("buy 600711 300 ") for c in cmds)


def test_parse_clearout_maps_to_sell_close() -> None:
    cmds = _parse_runtime_commands("", "清仓600711\n请执行 close 000537")
    assert "sell 600711" in cmds
    assert "sell 000537" in cmds


def test_parse_buy_watch_only_when_no_position_fields() -> None:
    cmds = _parse_runtime_commands("买入指令", "001258编号买入")
    assert "hold 001258" in cmds


def test_parse_config_tp_hit_correctness() -> None:
    assert _parse_config_commands("set", "take_profit_hit_for_correctness 1") == [
        "set take_profit_hit_for_correctness 1"
    ]
    assert _parse_config_commands("", "tp_hit_correctness 0") == [
        "set take_profit_hit_for_correctness 0"
    ]
    assert _parse_config_commands("止盈", "止盈命中：卖对") == [
        "set take_profit_hit_for_correctness 1"
    ]
    assert _parse_config_commands("", "止盈命中 卖飞") == [
        "set take_profit_hit_for_correctness 0"
    ]
