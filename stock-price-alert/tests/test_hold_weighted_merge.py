"""持仓合并：_upsert_hold_in_cfg 与 _merge_duplicate_watch_rows 加权逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from run_alert import (
    _merge_duplicate_watch_rows,
    _upsert_hold_in_cfg,
    dedupe_watchlist_in_cfg,
)


def test_merge_duplicate_watch_rows_sums_shares_weighted_cost() -> None:
    a = {
        "code": "600711",
        "hold_shares": 8600,
        "cost_price": 13.2864,
        "tags": "持仓",
        "note": "n1",
    }
    b = {
        "code": "600711",
        "hold_shares": 12300,
        "cost_price": 13.2073,
        "tags": "持仓",
        "note": "n2",
    }
    m = _merge_duplicate_watch_rows(a, b)
    assert m["hold_shares"] == 20900
    want = (8600 * 13.2864 + 12300 * 13.2073) / 20900.0
    assert abs(float(m["cost_price"]) - want) < 1e-6


def test_upsert_hold_twice_accumulates(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg = {"watchlist": []}
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ok, _ = _upsert_hold_in_cfg(
        cfg,
        code="600711",
        hold_shares=8600,
        cost_price=13.2864,
        config_path=cfg_path,
        ledger_kind="buy",
    )
    assert ok
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ok2, _ = _upsert_hold_in_cfg(
        cfg,
        code="600711",
        hold_shares=12300,
        cost_price=13.2073,
        config_path=cfg_path,
        ledger_kind="buy",
    )
    assert ok2
    cfg2 = json.loads(cfg_path.read_text(encoding="utf-8"))
    wl = cfg2["watchlist"]
    assert len(wl) == 1
    row = wl[0]
    assert int(row["hold_shares"]) == 20900
    want = (8600 * 13.2864 + 12300 * 13.2073) / 20900.0
    assert abs(float(row["cost_price"]) - want) < 1e-5


def test_upsert_merge_when_old_cost_was_zero(tmp_path: Path) -> None:
    """旧成本为 0 时仍应累加股数（均价按公式稀释），避免第二次整笔覆盖。"""
    cfg_path = tmp_path / "config.json"
    cfg = {
        "watchlist": [
            {
                "enabled": True,
                "code": "600711",
                "name": "测",
                "market": "sh",
                "hold_shares": 8600,
                "cost_price": 0.0,
                "tags": "持仓",
                "alert_mode": "breach",
                "note": "",
                "industry": "",
            }
        ]
    }
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    ok, _ = _upsert_hold_in_cfg(
        cfg,
        code="600711",
        hold_shares=12300,
        cost_price=13.2,
        config_path=cfg_path,
        ledger_kind="buy",
    )
    assert ok
    row = json.loads(cfg_path.read_text(encoding="utf-8"))["watchlist"][0]
    assert int(row["hold_shares"]) == 8600 + 12300
    assert abs(float(row["cost_price"]) - (12300 * 13.2 / 20900.0)) < 1e-5


def test_dedupe_watchlist_merges_duplicates_weighted() -> None:
    cfg = {
        "watchlist": [
            {
                "enabled": True,
                "code": "600711",
                "hold_shares": 8600,
                "cost_price": 13.2864,
                "tags": "持仓",
            },
            {
                "enabled": True,
                "code": "600711",
                "hold_shares": 12300,
                "cost_price": 13.2073,
                "tags": "持仓",
            },
        ]
    }
    n = dedupe_watchlist_in_cfg(cfg)
    assert n == 1
    assert len(cfg["watchlist"]) == 2 - n
    row = cfg["watchlist"][0]
    assert int(row["hold_shares"]) == 20900
