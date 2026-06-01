"""盘中 rt_sw_k 热门申万一级：实时排序、缓存、降级日K。"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quote_tushare import fetch_all_sectors_realtime, fetch_sector_realtime, list_sw_l1_ts_codes
from run_alert import (
    _hot_sectors_from_realtime_df,
    _resolve_hot_sw_l1_set,
    _resolve_hot_sw_l1_set_realtime,
)


def test_list_sw_l1_ts_codes_from_json(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "sw_l1_names.json").write_text(
        '{"801010.SI":"农林牧渔","801890.SI":"机械设备"}',
        encoding="utf-8",
    )
    codes = list_sw_l1_ts_codes(tmp_path)
    assert codes == ["801010.SI", "801890.SI"]


def test_fetch_sector_realtime_parses_pct_change(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame(
        [
            {
                "ts_code": "801010.SI",
                "name": "农林牧渔",
                "trade_time": "2026-01-29 11:20:15",
                "close": 2931.136,
                "pct_change": 0.55,
                "vol": 2594579310.0,
            }
        ]
    )
    pro = MagicMock()
    pro.rt_sw_k.return_value = df
    monkeypatch.setattr("quote_tushare._get_pro", lambda: pro)
    monkeypatch.setattr("quote_tushare._CFG", {"enabled": True, "token": "x", "sw_enabled": True})
    monkeypatch.setattr("quote_tushare._resolved_token", lambda: "x")

    snap = fetch_sector_realtime("801010.SI")
    assert snap is not None
    assert snap["pct_chg"] == pytest.approx(0.55)
    assert snap["pct_change"] == pytest.approx(0.55)
    assert snap["trade_date"] == "2026-01-29"
    assert snap["name"] == "农林牧渔"
    pro.rt_sw_k.assert_called_once_with(ts_code="801010.SI")


def test_fetch_all_sectors_realtime_bulk_filters_l1_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "sw_l1_names.json").write_text(
        '{"801010.SI":"农林牧渔","801890.SI":"机械设备"}',
        encoding="utf-8",
    )
    df = pd.DataFrame(
        [
            {
                "ts_code": "801010.SI",
                "name": "农林牧渔",
                "trade_time": "2026-01-29 11:20:15",
                "close": 2931.0,
                "pct_change": 0.55,
                "vol": 1e6,
            },
            {
                "ts_code": "801012.SI",
                "name": "农产品加工",
                "trade_time": "2026-01-29 11:20:15",
                "close": 2544.0,
                "pct_change": 0.72,
                "vol": 1e6,
            },
        ]
    )
    pro = MagicMock()
    pro.rt_sw_k.return_value = df
    monkeypatch.setattr("quote_tushare._get_pro", lambda: pro)
    monkeypatch.setattr("quote_tushare._CFG", {"enabled": True, "token": "x", "sw_enabled": True})
    monkeypatch.setattr("quote_tushare._resolved_token", lambda: "x")

    out = fetch_all_sectors_realtime(root=tmp_path)
    assert len(out) == 1
    assert out.iloc[0]["ts_code"] == "801010.SI"
    pro.rt_sw_k.assert_called_once_with()


def test_hot_sectors_from_realtime_df_top_fraction() -> None:
    df = pd.DataFrame(
        [
            {"ts_code": "801010.SI", "pct_chg": 5.0},
            {"ts_code": "801020.SI", "pct_chg": 3.0},
            {"ts_code": "801030.SI", "pct_chg": 1.0},
            {"ts_code": "801040.SI", "pct_chg": -1.0},
        ]
    )
    hot = _hot_sectors_from_realtime_df(df, top_fraction=0.5)
    assert hot == frozenset({"801010.SI", "801020.SI"})


def test_hot_sectors_from_realtime_df_accepts_pct_change_column() -> None:
    df = pd.DataFrame(
        [
            {"ts_code": "801010.SI", "pct_change": 2.0},
            {"ts_code": "801020.SI", "pct_change": 1.0},
        ]
    )
    hot = _hot_sectors_from_realtime_df(df, top_fraction=1.0)
    assert hot == frozenset({"801010.SI", "801020.SI"})


def test_resolve_hot_sw_l1_realtime_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame(
        [{"ts_code": "801010.SI", "pct_chg": 4.0}, {"ts_code": "801020.SI", "pct_chg": 1.0}]
    )
    monkeypatch.setattr(
        "quote_tushare.fetch_all_sectors_realtime",
        lambda **k: df,
    )
    cfg = {"display": {"hot_sector_top_fraction": 0.5, "hot_sector_realtime_refresh_sec": 120}}
    state: dict = {}
    hot1 = _resolve_hot_sw_l1_set_realtime(cfg, root=Path("."), state=state)
    assert hot1 == frozenset({"801010.SI"})
    assert "fetched_at" in state["__hot_sector_cache__"]

    calls = {"n": 0}

    def _boom(**_k: object) -> pd.DataFrame:
        calls["n"] += 1
        raise RuntimeError("should not call")

    monkeypatch.setattr("quote_tushare.fetch_all_sectors_realtime", _boom)
    hot2 = _resolve_hot_sw_l1_set_realtime(cfg, root=Path("."), state=state)
    assert hot2 == hot1
    assert calls["n"] == 0


def test_resolve_hot_sw_l1_realtime_falls_back_to_daily_kline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kline_store import init_schema, open_store_connection, upsert_bars

    monkeypatch.setattr(
        "quote_tushare.fetch_all_sectors_realtime",
        lambda **k: pd.DataFrame(),
    )

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
            "hot_sector_use_realtime": True,
            "hot_sector_lookback_days": 5,
        },
    }
    state: dict = {}
    hot = _resolve_hot_sw_l1_set(cfg, root=tmp_path, state=state, picks_path=picks)
    assert hot
    assert state["__hot_sw_l1_daily__"]["rank_mode"] == "absolute"


def test_realtime_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    df = pd.DataFrame([{"ts_code": "801010.SI", "pct_chg": 2.0}])
    call_n = {"v": 0}

    def _fetch(**_k: object) -> pd.DataFrame:
        call_n["v"] += 1
        return df

    monkeypatch.setattr("quote_tushare.fetch_all_sectors_realtime", _fetch)
    cfg = {
        "display": {
            "hot_sector_top_fraction": 1.0,
            "hot_sector_realtime_refresh_sec": 15,
        }
    }
    state: dict = {}
    _resolve_hot_sw_l1_set_realtime(cfg, root=Path("."), state=state)
    assert call_n["v"] == 1
    state["__hot_sector_cache__"]["fetched_at"] = time.time() - 20.0
    _resolve_hot_sw_l1_set_realtime(cfg, root=Path("."), state=state)
    assert call_n["v"] == 2
