"""【热股榜精选】分区：热股榜 ∩ daily_picks score 排序。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest


def test_build_hot_stock_quality_items_sort_by_score(tmp_path: Path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    qt.configure_tushare_from_sources(
        {
            "tushare": {
                "enabled": False,
                "financial_cache_db_path": str(tmp_path / "f.db"),
            }
        }
    )
    iso = date.today().isoformat()
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=iso,
        data={
            "codes": ["600519", "000001", "600000"],
            "ranks": {"600519": 3, "000001": 1, "600000": 2},
            "trade_date": iso,
        },
    )

    picks = tmp_path / "daily_picks.json"
    picks.write_text(
        """
{
  "优质股": [
    {"code": "600519", "score": 9.5, "sw_l1": "801080.SI"},
    {"code": "000001", "score": 7.0, "sw_l1": "801780.SI"}
  ],
  "观察股": [
    {"code": "600000", "score": 8.0, "sw_l1": "801010.SI"}
  ]
}
""",
        encoding="utf-8",
    )

    items = [
        {
            "tagged": False,
            "q": {"code": "600519", "price": 10.0, "change_pct": 1.0},
            "rule": {"code": "600519", "market": "sh"},
            "rk": "r1",
            "sort_score": 1.0,
        },
        {
            "tagged": False,
            "q": {"code": "000001", "price": 5.0, "change_pct": -0.5},
            "rule": {"code": "000001", "market": "sz"},
            "rk": "r2",
            "sort_score": 0.5,
        },
        {
            "tagged": False,
            "q": {"code": "600000", "price": 3.0, "change_pct": 0.2},
            "rule": {"code": "600000", "market": "sh"},
            "rk": "r3",
            "sort_score": 0.3,
        },
        {
            "tagged": False,
            "q": {"code": "999999", "price": 1.0, "change_pct": 0.0},
            "rule": {"code": "999999", "market": "sh"},
            "rk": "r9",
            "sort_score": 99.0,
        },
    ]

    cfg = {
        "display": {
            "show_hot_stock_quality": True,
            "hot_stock_display_count": 2,
            "hot_stock_top_n": 50,
            "quality_stock_filters": {"enabled": False},
        }
    }
    scored = ra._daily_picks_scored_rows_by_code(picks)
    hot_items = ra._build_hot_stock_quality_items(
        items, picks_path=picks, cfg=cfg, scored_rows_by_code=scored
    )
    codes = [ra._pack_stock_code(x) for x in hot_items]
    assert codes == ["600519", "600000"]
    assert hot_items[0].get("_hot_stock_rank") == 3


def test_build_hot_stock_quality_skips_no_score(tmp_path: Path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    qt.configure_tushare_from_sources(
        {
            "tushare": {
                "enabled": False,
                "financial_cache_db_path": str(tmp_path / "f.db"),
            }
        }
    )
    iso = date.today().isoformat()
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=iso,
        data={"codes": ["600519"], "ranks": {"600519": 1}, "trade_date": iso},
    )
    picks = tmp_path / "daily_picks.json"
    picks.write_text('{"优质股": []}', encoding="utf-8")
    items = [
        {
            "tagged": False,
            "q": {"code": "600519", "price": 10.0},
            "rule": {"code": "600519"},
            "rk": "r1",
            "sort_score": 1.0,
        }
    ]
    cfg = {"display": {"show_hot_stock_quality": True, "quality_stock_filters": {"enabled": False}}}
    assert (
        ra._build_hot_stock_quality_items(items, picks_path=picks, cfg=cfg) == []
    )
