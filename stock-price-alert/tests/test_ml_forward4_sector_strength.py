"""板块强度修正（本地 K 线超额）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from kline_store import init_schema, open_store_connection, upsert_bars
from ml_forward4_sector_strength import (
    build_excess_frac_by_stock_code,
    index_secid_from_ts_code,
    local_n_day_return_fraction,
    precompute_sector_excess_vs_sh,
    sector_strength_adjust_gate_thresholds,
)


def test_index_secid_from_ts_code() -> None:
    assert index_secid_from_ts_code("000001.SH") == "1.000001"
    assert index_secid_from_ts_code("399006.SZ").startswith("0.")


def test_sector_strength_adjust_outperform() -> None:
    mf4 = {
        "sector_strength": {
            "enabled": True,
            "outperform_threshold": 0.02,
            "quality_adjust": -0.02,
            "watch_adjust": -0.02,
        },
        "select_min_up_prob_quality": 0.5,
        "select_min_up_prob_watch": 0.4,
    }
    t = sector_strength_adjust_gate_thresholds(mf4, 0.05)
    assert t is not None
    q, w = t
    assert q == pytest.approx(0.48)
    assert w == pytest.approx(0.38)


def test_sector_strength_adjust_underperform() -> None:
    mf4 = {
        "sector_strength": {
            "enabled": True,
            "outperform_threshold": 0.02,
            "quality_adjust": -0.02,
            "watch_adjust": -0.02,
        },
        "select_min_up_prob_quality": 0.5,
        "select_min_up_prob_watch": 0.4,
    }
    t = sector_strength_adjust_gate_thresholds(mf4, -0.03)
    assert t is not None
    q, w = t
    assert q == pytest.approx(0.52)
    assert w == pytest.approx(0.42)


def test_sector_strength_neutral_no_change() -> None:
    mf4 = {
        "sector_strength": {"enabled": True, "outperform_threshold": 0.02},
        "select_min_up_prob_quality": 0.5,
        "select_min_up_prob_watch": 0.4,
    }
    assert sector_strength_adjust_gate_thresholds(mf4, 0.01) is None


def test_build_excess_by_stock_code() -> None:
    m = build_excess_frac_by_stock_code(
        ["000001", "000002"],
        {"000001": "801010.SI", "000002": "801020.SI"},
        {"801010.SI": 0.03, "801020.SI": -0.01},
    )
    assert m["000001"] == pytest.approx(0.03)
    assert m["000002"] == pytest.approx(-0.01)


def _seed_linear_db(path: Path) -> None:
    from datetime import date, timedelta

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store_connection(path)
    try:
        init_schema(conn)
        rows_idx = []
        rows_sw = []
        t0 = date(2024, 1, 2)
        for i in range(40):
            d = (t0 + timedelta(days=i)).isoformat()
            c_idx = 3000.0 + i * 1.0
            c_sw = 1000.0 + i * 3.0
            rows_idx.append((d, c_idx, c_idx, c_idx, c_idx, 1e6))
            rows_sw.append((d, c_sw, c_sw, c_sw, c_sw, 1e6))
        upsert_bars(conn, "1.000001", rows_idx)
        upsert_bars(conn, "801010.SI", rows_sw)
    finally:
        conn.close()


def test_local_n_day_return_and_precompute(tmp_path: Path) -> None:
    db = tmp_path / "k.db"
    _seed_linear_db(db)
    ri = local_n_day_return_fraction(db, "1.000001", 5)
    rs = local_n_day_return_fraction(db, "801010.SI", 5)
    assert ri is not None and rs is not None
    assert rs > ri
    ex, br = precompute_sector_excess_vs_sh(
        {},
        db,
        {"801010.SI"},
        lookback_days=5,
        index_ts_code="000001.SH",
    )
    assert br is not None
    assert "801010.SI" in ex
    assert ex["801010.SI"] == pytest.approx(rs - br)
