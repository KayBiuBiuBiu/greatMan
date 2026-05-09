"""RealtimeQuoteHub 日内增量特征（O(1) 快照）。"""

from __future__ import annotations

from collections import deque
from unittest.mock import patch


def test_get_intraday_snapshot_mid_range() -> None:
    from realtime_hub import RealtimeQuoteHub

    h = RealtimeQuoteHub(poll_interval_sec=60.0, ut="test_ut", push_stream_enabled=False)
    h._merge_quote(
        "600000",
        "sh",
        {"price": 10.0, "change_pct": 0.0, "pre_close": 10.0},
    )
    h._merge_quote(
        "600000",
        "sh",
        {"price": 11.0, "change_pct": 10.0, "pre_close": 10.0},
    )
    s = h.get_intraday_snapshot("600000", "sh", price=10.5)
    assert abs(float(s["intraday_position"]) - 0.5) < 1e-5
    assert float(s["high_price"]) >= 11.0
    assert float(s["low_price"]) <= 10.0


def test_merge_quote_http_path_updates_agg() -> None:
    from realtime_hub import RealtimeQuoteHub

    h = RealtimeQuoteHub(poll_interval_sec=60.0, ut="test_ut", push_stream_enabled=False)
    h._merge_quote(
        "000001",
        "sz",
        {
            "price": 100.0,
            "change_pct": 0.0,
            "pre_close": 100.0,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
        },
    )
    m = h.get_metrics("000001", "sz")
    assert m is not None
    assert float(m.get("intraday_position") or -1) >= 0.0
    assert float(m.get("intraday_position") or 2) <= 1.0


def test_afternoon_strength_diff_value() -> None:
    from realtime_hub import RealtimeQuoteHub

    h = RealtimeQuoteHub(poll_interval_sec=60.0, ut="u", push_stream_enabled=False)
    h._merge_quote(
        "600000",
        "sh",
        {"price": 10.0, "change_pct": 0.0, "pre_close": 10.0},
    )
    key = ("600000", "sh")
    h._day_agg[key]["morning_ret"] = 0.5
    s = h.get_intraday_snapshot(
        "600000", "sh", price=10.2, change_pct=2.0
    )
    assert abs(float(s["afternoon_strength_diff"]) - 1.5) < 1e-4


def test_pullback_from_high_pts() -> None:
    from realtime_hub import RealtimeQuoteHub

    h = RealtimeQuoteHub(poll_interval_sec=60.0, ut="u", push_stream_enabled=False)
    h._merge_quote(
        "600000",
        "sh",
        {"price": 9.5, "change_pct": -5.0, "pre_close": 10.0},
    )
    key = ("600000", "sh")
    h._day_agg[key]["high_price"] = 10.5
    h._day_agg[key]["low_price"] = 9.5
    s = h.get_intraday_snapshot("600000", "sh", price=9.5, change_pct=-5.0)
    # (10.5 - 9.5) / 10 * 100 = 10.0（相对昨收的百分点落差）
    assert abs(float(s["pullback_from_high_pts"]) - 10.0) < 1e-4


def test_tail_vs_body_diff_with_monotonic() -> None:
    from realtime_hub import RealtimeQuoteHub

    h = RealtimeQuoteHub(poll_interval_sec=60.0, ut="u", push_stream_enabled=False)
    h._merge_quote(
        "600000",
        "sh",
        {"price": 10.0, "change_pct": 0.0, "pre_close": 10.0},
    )
    key = ("600000", "sh")
    h._price_hist[key] = deque([(0.0, 10.0), (400.0, 11.0)], maxlen=4000)
    with patch("realtime_hub.time.monotonic", return_value=2100.0):
        s = h.get_intraday_snapshot(
            "600000", "sh", price=11.5, change_pct=15.0
        )
    assert s["tail_vs_body_diff"] is not None
    r_tail = (11.5 - 11.0) / 11.0 * 100.0
    r_body = (11.0 - 10.0) / 10.0 * 100.0
    assert abs(float(s["tail_vs_body_diff"]) - (r_tail - r_body)) < 1e-4
