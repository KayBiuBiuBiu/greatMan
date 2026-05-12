"""ml_forward4 时间划分与校准烟测。"""

from __future__ import annotations

from ml_forward4_prob_tools import (
    apply_platt,
    fit_platt_scaler,
    time_series_date_splits,
)


def test_time_series_splits() -> None:
    days = [f"2024-01-{i:02d}" for i in range(1, 31)]
    days += [f"2024-02-{i:02d}" for i in range(1, 29)]
    tr, cal, te = time_series_date_splits(days, test_trading_days=5, cal_trading_days=4)
    assert len(te) == 5
    assert len(cal) == 4
    assert len(tr) == len(set(days)) - 9
    assert not (tr & te) and not (cal & te) and not (tr & cal)


def test_platt_roundtrip() -> None:
    probs = [0.2, 0.25, 0.4, 0.55, 0.7, 0.8, 0.35, 0.45, 0.6, 0.72]
    y = [0, 0, 1, 0, 1, 1, 0, 1, 1, 0]
    cal = fit_platt_scaler(probs, y)
    out = [apply_platt(p, cal) for p in probs]
    assert all(0.0 <= x <= 1.0 for x in out)
