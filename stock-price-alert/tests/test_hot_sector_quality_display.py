"""热门板块优质股：申万一级超额前 30% 筛选。"""

from __future__ import annotations

from pathlib import Path

import pytest

from run_alert import (
    _build_hot_sector_quality_items,
    _daily_picks_quality_rows_in_order,
    _hot_sw_l1_top_fraction,
)


def test_hot_sw_l1_top_fraction_thirty_percent() -> None:
    excess = {
        "801010.SI": 0.05,
        "801020.SI": 0.03,
        "801030.SI": 0.01,
        "801040.SI": -0.01,
        "801050.SI": -0.02,
        "801060.SI": -0.03,
        "801070.SI": -0.04,
        "801080.SI": -0.05,
        "801090.SI": -0.06,
        "801100.SI": -0.07,
    }
    hot = _hot_sw_l1_top_fraction(excess, top_fraction=0.3)
    assert len(hot) == 3
    assert hot == frozenset({"801010.SI", "801020.SI", "801030.SI"})


def test_daily_picks_quality_rows_in_order(tmp_path: Path) -> None:
    p = tmp_path / "daily_picks.json"
    p.write_text(
        """
{
  "优质股": [
    {"code": "000001", "sw_l1": "801010.SI", "score": 8.0},
    {"code": "600000", "sw_l1": "801020.SI", "score": 7.5}
  ],
  "优质标的": [
    {"code": "000002", "sw_l1": "801010.SI", "score": 7.0}
  ]
}
""",
        encoding="utf-8",
    )
    rows = _daily_picks_quality_rows_in_order(p)
    assert [r["code"] for r in rows] == ["000001", "600000", "000002"]


def test_build_hot_sector_quality_items_respects_order_and_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        """
{
  "优质股": [
    {"code": "000001", "name": "A", "sw_l1": "801010.SI", "score": 8.0},
    {"code": "600000", "name": "B", "sw_l1": "801020.SI", "score": 7.5},
    {"code": "000002", "name": "C", "sw_l1": "801010.SI", "score": 7.0},
    {"code": "600519", "name": "D", "sw_l1": "801030.SI", "score": 6.5}
  ]
}
""",
        encoding="utf-8",
    )
    cfg = {
        "display": {
            "hot_sector_quality_enabled": True,
            "hot_sector_max_stocks": 2,
        }
    }
    state: dict = {}
    monkeypatch.setattr(
        "run_alert._resolve_hot_sw_l1_set",
        lambda *a, **k: frozenset({"801010.SI", "801020.SI", "801030.SI"}),
    )

    def _pack(code: str) -> dict:
        return {
            "tagged": False,
            "q": {"code": code},
            "rule": {"code": code},
            "sort_score": 1.0,
        }

    items = [_pack("000001"), _pack("600000"), _pack("000002"), _pack("600519")]
    hot = _build_hot_sector_quality_items(
        items,
        picks_path=picks,
        cfg=cfg,
        root=tmp_path,
        state=state,
        console_qcodes={"000001", "600000", "000002", "600519"},
        af_new_for_sec=set(),
    )
    assert [x["q"]["code"] for x in hot] == ["000001", "600000"]


def test_build_hot_sector_disabled(tmp_path: Path) -> None:
    picks = tmp_path / "daily_picks.json"
    picks.write_text('{"优质股": []}', encoding="utf-8")
    cfg = {"display": {"hot_sector_quality_enabled": False}}
    hot = _build_hot_sector_quality_items(
        [],
        picks_path=picks,
        cfg=cfg,
        root=tmp_path,
        state={},
        console_qcodes=set(),
        af_new_for_sec=set(),
    )
    assert hot == []


def test_resolve_hot_sw_l1_absolute_fallback_when_no_benchmark(tmp_path: Path) -> None:
    from kline_store import init_schema, open_store_connection, upsert_bars
    from run_alert import _resolve_hot_sw_l1_set

    db = tmp_path / "data" / "daily_klines.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store_connection(db)
    init_schema(conn)
    rows = [
        ("2026-05-15", 100.0, 101.0, 99.0, 100.0, 1e6),
        ("2026-05-16", 100.0, 102.0, 99.5, 101.0, 1e6),
        ("2026-05-19", 101.0, 103.0, 100.0, 102.0, 1e6),
        ("2026-05-20", 102.0, 105.0, 101.0, 104.0, 1e6),
        ("2026-05-21", 104.0, 106.0, 103.0, 105.0, 1e6),
        ("2026-05-22", 105.0, 110.0, 104.0, 108.0, 1e6),
    ]
    upsert_bars(conn, "801010.SI", rows)
    low_rows = [
        ("2026-05-15", 50.0, 51.0, 49.0, 50.0, 1e6),
        ("2026-05-16", 50.0, 51.0, 49.5, 50.5, 1e6),
        ("2026-05-19", 50.5, 51.0, 50.0, 50.2, 1e6),
        ("2026-05-20", 50.2, 51.0, 50.0, 50.4, 1e6),
        ("2026-05-21", 50.4, 51.0, 50.2, 50.6, 1e6),
        ("2026-05-22", 50.6, 51.0, 50.4, 50.8, 1e6),
    ]
    upsert_bars(conn, "801020.SI", low_rows)
    conn.close()

    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        '{"优质股":[{"code":"000001","sw_l1":"801010.SI"}]}', encoding="utf-8"
    )
    cfg = {
        "kline_store": {"enabled": True, "db_path": "data/daily_klines.db"},
        "display": {
            "hot_sector_quality_enabled": True,
            "hot_sector_lookback_days": 5,
            "hot_sector_use_realtime": False,
        },
    }
    state: dict = {}
    hot = _resolve_hot_sw_l1_set(cfg, root=tmp_path, state=state, picks_path=picks)
    assert "801010.SI" in hot
    assert state["__hot_sw_l1_daily__"]["rank_mode"] == "absolute"


def test_resolve_hot_sw_l1_ignores_stale_empty_cache(tmp_path: Path) -> None:
    from kline_store import init_schema, open_store_connection, upsert_bars
    from run_alert import _resolve_hot_sw_l1_set

    db = tmp_path / "data" / "daily_klines.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = open_store_connection(db)
    init_schema(conn)
    rows = [
        ("2026-05-15", 100.0, 101.0, 99.0, 100.0, 1e6),
        ("2026-05-16", 100.0, 102.0, 99.5, 101.0, 1e6),
        ("2026-05-19", 101.0, 103.0, 100.0, 102.0, 1e6),
        ("2026-05-20", 102.0, 105.0, 101.0, 104.0, 1e6),
        ("2026-05-21", 104.0, 106.0, 103.0, 105.0, 1e6),
        ("2026-05-22", 105.0, 110.0, 104.0, 108.0, 1e6),
    ]
    upsert_bars(conn, "801010.SI", rows)
    upsert_bars(conn, "801020.SI", rows)
    conn.close()

    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        '{"优质股":[{"code":"000001","sw_l1":"801010.SI"}]}', encoding="utf-8"
    )
    cfg = {
        "kline_store": {"enabled": True, "db_path": "data/daily_klines.db"},
        "display": {
            "hot_sector_quality_enabled": True,
            "hot_sector_lookback_days": 5,
            "hot_sector_use_realtime": False,
        },
    }
    state: dict = {
        "__hot_sw_l1_daily__": {
            "date": "2026-05-24",
            "codes": [],
            "lookback_days": 5,
            "top_fraction": 0.3,
        }
    }
    hot = _resolve_hot_sw_l1_set(cfg, root=tmp_path, state=state, picks_path=picks)
    assert hot
    assert state["__hot_sw_l1_daily__"]["rank_mode"] == "absolute"
