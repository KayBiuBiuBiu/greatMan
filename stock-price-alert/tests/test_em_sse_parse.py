"""东财 SSE 行解析。"""

from __future__ import annotations

from eastmoney_sse_quotes import _em_row_to_metrics, parse_sse_quote_line


def test_parse_sse_quote_line_ok() -> None:
    line = (
        'data: {"rc":0,"rt":4,"svr":1,"lt":1,"full":1,"dlmkts":"","data":'
        '{"f43":11.49,"f57":"000001","f58":"平安银行","f170":-0.26,"f13":0}}'
    )
    d = parse_sse_quote_line(line)
    assert d is not None
    assert d["f57"] == "000001"
    m = _em_row_to_metrics(d, fallback_market="sz")
    assert m is not None
    assert m["code"] == "000001"
    assert m["market"] == "sz"
    assert m["price"] == 11.49
    assert m["change_pct"] == -0.26


def test_parse_sse_quote_line_rc_fail() -> None:
    line = 'data: {"rc":102,"data":null}'
    assert parse_sse_quote_line(line) is None
