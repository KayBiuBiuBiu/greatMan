"""run_alert._quote_day_change_pct：展示与着色用涨跌幅推断。"""

from run_alert import _quote_day_change_pct


def test_quote_day_change_from_change_pct() -> None:
    c, d = _quote_day_change_pct({"price": 10.0, "pre_close": 9.0, "change_pct": 1.5})
    assert c == 1.5 and d == 1.5


def test_quote_day_change_inferred_when_pct_missing() -> None:
    c, d = _quote_day_change_pct({"price": 11.0, "pre_close": 10.0, "change_pct": None})
    assert c is not None and abs(c - 10.0) < 1e-6
    assert abs(d - 10.0) < 1e-6


def test_quote_day_change_empty_when_no_data() -> None:
    c, d = _quote_day_change_pct({"price": 0.0, "pre_close": 0.0})
    assert c is None and d == 0.0
