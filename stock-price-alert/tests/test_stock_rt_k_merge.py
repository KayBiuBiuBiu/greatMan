"""quote_tushare 个股 rt_k 与历史行合并。"""

from __future__ import annotations

import quote_tushare as qt


def _rows_20(last_day: str = "2026-01-20"):
    out: list[tuple[str, float, float, float, float, float]] = []
    for i in range(20):
        d = f"2026-01-{i + 1:02d}"
        out.append((d, 1.0, 1.0, 1.0, float(i + 1), 100.0))
    out[-1] = (last_day, 1.0, 1.0, 1.0, 20.0, 100.0)
    return out


def test_merge_stock_rows_rt_k_replace_same_day(monkeypatch):
    monkeypatch.setattr(qt, "stock_rt_k_enabled", lambda: True)
    monkeypatch.setattr(qt, "stock_rt_k_fallback_enabled", lambda: False)
    monkeypatch.setattr(
        qt,
        "fetch_stock_rt_k",
        lambda tc: {
            "trade_date": "2026-01-20",
            "open": 2.0,
            "high": 3.0,
            "low": 1.5,
            "close": 2.5,
            "vol": 999.0,
        },
    )
    rows = _rows_20("2026-01-20")
    out = qt.merge_stock_rows_with_rt_k("1.600000", rows, ut=None)
    assert out[-1][0] == "2026-01-20"
    assert out[-1][4] == 2.5
    assert out[-1][5] == 999.0


def test_merge_stock_rows_rt_k_append_new_day(monkeypatch):
    monkeypatch.setattr(qt, "stock_rt_k_enabled", lambda: True)
    monkeypatch.setattr(qt, "stock_rt_k_fallback_enabled", lambda: False)
    monkeypatch.setattr(
        qt,
        "fetch_stock_rt_k",
        lambda tc: {
            "trade_date": "2026-01-21",
            "open": 2.0,
            "high": 3.0,
            "low": 1.5,
            "close": 2.5,
            "vol": 888.0,
        },
    )
    rows = _rows_20("2026-01-20")
    out = qt.merge_stock_rows_with_rt_k("1.600000", rows, ut=None)
    assert len(out) == 21
    assert out[-1][0] == "2026-01-21"
    assert out[-1][4] == 2.5


def test_merge_stock_rows_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(qt, "stock_rt_k_enabled", lambda: False)
    monkeypatch.setattr(
        qt,
        "fetch_stock_rt_k",
        lambda tc: (_ for _ in ()).throw(AssertionError("no fetch")),
    )
    rows = _rows_20()
    out = qt.merge_stock_rows_with_rt_k("1.600000", rows, ut=None)
    assert out == rows


def test_merge_stock_rows_skips_bk_secid(monkeypatch):
    monkeypatch.setattr(qt, "stock_rt_k_enabled", lambda: True)
    monkeypatch.setattr(
        qt,
        "fetch_stock_rt_k",
        lambda tc: (_ for _ in ()).throw(AssertionError("no fetch")),
    )
    rows = _rows_20()
    out = qt.merge_stock_rows_with_rt_k("90.BK0474", rows, ut=None)
    assert out == rows
