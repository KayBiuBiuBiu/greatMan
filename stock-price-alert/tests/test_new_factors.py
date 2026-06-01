from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


def _configure_tmp_cache(tmp_path) -> None:
    import quote_tushare as qt

    qt.configure_tushare_from_sources(
        {
            "tushare": {
                "enabled": False,
                "financial_cache_db_path": str(tmp_path / "financial_factors.db"),
            }
        }
    )


def test_moneyflow_individual_cache_roundtrip(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def moneyflow(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20260520",
                        "buy_elg_amount": 1000.0,
                        "sell_elg_amount": 200.0,
                        "buy_lg_amount": 500.0,
                        "sell_lg_amount": 100.0,
                    },
                    {
                        "trade_date": "20260521",
                        "buy_elg_amount": 800.0,
                        "sell_elg_amount": 300.0,
                        "buy_lg_amount": 400.0,
                        "sell_lg_amount": 200.0,
                    },
                ]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    out = qt.fetch_moneyflow_individual("600519", days=5)
    assert out["net_main_5d"] is not None
    assert out["net_main_1d"] is not None
    assert out["net_main_5d_yi"] is not None

    cached = qt.fetch_moneyflow_individual("600519", cache_only=True)
    assert cached["net_main_5d"] == out["net_main_5d"]


def test_moneyflow_industry_aggregate_from_stocks(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)
    qt._write_json_table_row(
        "stock_moneyflow_cache",
        key_col="code",
        key_val="600519",
        data={"net_main_5d": 2e8, "net_main_1d": 5e7, "net_main_5d_yi": 2.0, "net_main_1d_yi": 0.5},
    )
    qt._write_json_table_row(
        "stock_moneyflow_cache",
        key_col="code",
        key_val="000858",
        data={"net_main_5d": 1e8, "net_main_1d": 2e7, "net_main_5d_yi": 1.0, "net_main_1d_yi": 0.2},
    )
    sw = {"600519": "801080.SI", "000858": "801080.SI"}
    n = qt._aggregate_industry_moneyflow_from_stocks(["600519", "000858"], sw)
    assert n == 1
    out = qt.fetch_moneyflow_industry("801080.SI", cache_only=True)
    assert out.get("net_main_5d") == pytest.approx(3e8)
    assert out.get("source") == "aggregated_sw"


def test_hot_stocks_and_broker_recommend(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def ths_hot(self, **kwargs):
            assert kwargs.get("market") == "热股"
            return pd.DataFrame(
                [
                    {"rank": 1, "ts_code": "600519.SH", "market": "热股"},
                    {"rank": 2, "ts_code": "000001.SZ", "market": "热股"},
                    {"rank": 3, "ts_code": "01810.HK", "market": "热股"},
                    {"rank": 4, "ts_code": "886065.TI", "market": "热股"},
                ]
            )

        def broker_recommend(self, **kwargs):
            return pd.DataFrame(
                [
                    {"ts_code": "600519.SH", "broker": "A"},
                    {"ts_code": "600519.SH", "broker": "B"},
                    {"ts_code": "000001.SZ", "broker": "C"},
                ]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    td = date.today().strftime("%Y%m%d")
    hot = qt.fetch_hot_stocks(trade_date=td, top_n=50)
    assert hot == ["600519", "000001"]

    month = date.today().strftime("%Y%m")
    br = qt.fetch_broker_recommend(month=month, min_count=2)
    assert br.get("600519") == 2
    assert "000001" not in br

    assert qt.is_hot_stock("600519", cache_only=True, trade_date=td)
    assert qt.is_hot_stock("000001", cache_only=True, trade_date=td)
    assert qt.is_hot_stock("999999", cache_only=True, trade_date=td) is False
    assert qt.get_broker_recommend_count("600519", cache_only=True, month=month) == 2

    meta = qt.read_hot_stock_cache_meta()
    assert meta.get("count", 0) >= 2


def test_ths_hot_fallback_is_new_n(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def ths_hot(self, **kwargs):
            is_new = kwargs.get("is_new")
            if is_new == "Y":
                return pd.DataFrame()
            return pd.DataFrame(
                [
                    {
                        "rank": 1,
                        "ts_code": "600519.SH",
                        "market": "热股",
                        "rank_time": "2026-05-27 11:00:00",
                    }
                ]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    td = date.today().strftime("%Y%m%d")
    hot = qt.fetch_hot_stocks(trade_date=td, force_refresh=True, top_n=10)
    assert hot == ["600519"]
    meta = qt.read_hot_stock_cache_meta()
    assert meta.get("is_new") == "N" or meta.get("is_new") == "Y"


def test_hot_concepts_ths_index_and_cache(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def ths_index(self, **kwargs):
            return pd.DataFrame(
                [
                    {"ts_code": "885001.TI", "name": "概念A", "type": "概念", "pct_change": 5.0},
                    {"ts_code": "885002.TI", "name": "概念B", "type": "概念", "pct_change": 2.0},
                ]
            )

        def dc_index(self, **kwargs):
            return pd.DataFrame(
                [{"ts_code": "BK0001.DC", "name": "概念A", "pct_change": 5.0}]
            )

        def dc_member(self, **kwargs):
            return pd.DataFrame([{"con_code": "600519.SH"}])

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    td = date.today().strftime("%Y%m%d")
    codes = qt.fetch_hot_concepts(trade_date=td, top_n=1)
    assert codes == ["885001.TI"]
    stats = qt.refresh_hot_concept_stocks_cache(trade_date=td, top_n=1)
    assert stats["concepts"] == 1
    assert stats["stocks"] == 1
    assert qt.hot_concept_factor_label("600519", cache_only=True, trade_date=td) == "🔥概念"
    assert qt.is_hot_concept_stock("000001", cache_only=True, trade_date=td) is False


def test_concept_index_and_members(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def dc_index(self, **kwargs):
            return pd.DataFrame(
                [
                    {"ts_code": "BK0001.DC", "name": "概念A", "pct_change": 5.0},
                    {"ts_code": "BK0002.DC", "name": "概念B", "pct_change": 2.0},
                ]
            )

        def dc_member(self, **kwargs):
            return pd.DataFrame(
                [{"con_code": "600519.SH"}, {"con_code": "000001.SZ"}]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    concepts = qt.fetch_concept_index(trade_date="20260521")
    assert concepts[0]["ts_code"] == "BK0001.DC"
    members = qt.fetch_concept_members("BK0001.DC", trade_date="20260521")
    assert members == ["600519", "000001"]
    assert qt.fetch_concept_members("BK0001.DC", trade_date="20260521", cache_only=True) == members


def test_update_special_factors_batch(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def moneyflow(self, **kwargs):
            return pd.DataFrame(
                [{"trade_date": "20260521", "buy_elg_amount": 100.0, "sell_elg_amount": 0.0}]
            )

        def moneyflow_ths(self, **kwargs):
            return pd.DataFrame(
                [{"trade_date": "20260521", "buy_elg_amount": 1000.0, "sell_elg_amount": 0.0}]
            )

        def ths_hot(self, **kwargs):
            return pd.DataFrame([{"rank": 1, "ts_code": "600519.SH"}])

        def broker_recommend(self, **kwargs):
            return pd.DataFrame([{"ts_code": "600519.SH", "broker": "X"}])

        def dc_index(self, **kwargs):
            return pd.DataFrame([{"ts_code": "BK0001.DC", "name": "热概念", "pct_change": 3.0}])

        def dc_member(self, **kwargs):
            return pd.DataFrame([{"con_code": "600519.SH"}])

        def ths_index(self, **kwargs):
            return pd.DataFrame(
                [{"ts_code": "885001.TI", "name": "热概念", "type": "概念", "pct_change": 3.0}]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())
    stats = qt.update_tushare_special_factors_for_candidates(
        ["600519"],
        code_to_sw={"600519": "801080.SI"},
        concept_top_n=1,
    )
    assert stats["stock_moneyflow"] >= 1
    assert stats["industry_moneyflow"] >= 1
    assert stats["hot_stocks"] >= 1
    assert stats["hot_concept_stocks"] >= 1


def test_get_real_score_special_factor_bonus(tmp_path) -> None:
    import quote_tushare as qt
    from quant_core.selector import get_real_score

    _configure_tmp_cache(tmp_path)
    qt._write_json_table_row(
        "stock_moneyflow_cache",
        key_col="code",
        key_val="600519",
        data={"net_main_5d": 3e8, "net_main_1d": 1e8, "net_main_5d_yi": 3.0, "net_main_1d_yi": 1.0},
    )
    qt._write_json_table_row(
        "broker_recommend_cache",
        key_col="month",
        key_val="202605",
        data={"counts": {"600519": 5}, "month": "202605"},
    )
    iso = date.today().isoformat()
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=iso,
        data={"codes": ["600519"], "trade_date": iso},
    )

    df = pd.DataFrame(
        {
            "close": [10.0 + i * 0.1 for i in range(80)],
            "high": [10.5 + i * 0.1 for i in range(80)],
            "low": [9.5 + i * 0.1 for i in range(80)],
            "volume": [1000.0 + i * 10 for i in range(80)],
        }
    )
    cfg = {
        "quant_selector": {
            "enable_moneyflow_factors": True,
            "enable_hot_stock_factors": True,
            "enable_broker_recommend_factors": True,
            "enable_industry_moneyflow_factors": False,
            "factor_weights": {
                "trend": 3.0,
                "box_position": 2.0,
                "volatility": 1.5,
                "volume_ratio": 1.5,
                "moneyflow_individual_threshold1": 5e7,
                "moneyflow_individual_threshold2": 2e8,
                "moneyflow_individual_bonus1": 1.0,
                "moneyflow_individual_bonus2": 2.0,
                "hot_stock_bonus": 1.0,
                "broker_recommend_bonus1": 1.0,
                "broker_recommend_bonus2": 2.0,
                "broker_recommend_count1": 2,
                "broker_recommend_count2": 5,
                "max_bonus": 3.0,
            },
        }
    }
    base = get_real_score("600519", df=df, cfg={"quant_selector": {}})
    boosted = get_real_score("600519", df=df, cfg=cfg)
    assert boosted >= base
    assert boosted <= 10.0


def test_format_stock_factor_summary_special_lines(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_json_table_row(
        "stock_moneyflow_cache",
        key_col="code",
        key_val="600519",
        data={"net_main_5d_yi": 1.2, "net_main_5d": 1.2e8},
    )
    qt._write_json_table_row(
        "industry_moneyflow_cache",
        key_col="industry_code",
        key_val="801080.SI",
        data={"net_main_5d_yi": 8.5, "net_main_5d": 8.5e8},
    )
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=date.today().isoformat(),
        data={"codes": ["600519"], "trade_date": date.today().isoformat()},
    )
    qt._write_json_table_row(
        "broker_recommend_cache",
        key_col="month",
        key_val=date.today().strftime("%Y%m"),
        data={"counts": {"600519": 3}},
    )
    monkeypatch.setattr(
        qt,
        "load_stock_to_sw_map_for_factors",
        lambda root=None: {"600519": "801080.SI"},
    )
    monkeypatch.setattr(qt, "is_hot_stock", lambda code, **kw: code == "600519")
    monkeypatch.setattr(qt, "get_broker_recommend_count", lambda code, **kw: 3)
    iso = date.today().isoformat()
    qt._write_hot_concept_stock_row(
        iso, "600519", tier="rocket", concept_codes=["885099.TI"]
    )
    monkeypatch.setattr(
        qt,
        "hot_concept_factor_label",
        lambda code, **kw: "🚀概念" if code == "600519" else None,
    )

    cfg = {
        "display": {
            "show_moneyflow_in_factor": True,
            "show_industry_moneyflow_in_factor": True,
            "show_hot_stock_in_factor": True,
            "show_hot_concept_in_factor": True,
            "show_broker_recommend_in_factor": True,
        },
        "quant_selector": {
            "enable_moneyflow_factors": True,
            "enable_industry_moneyflow_factors": True,
            "enable_hot_stock_factors": True,
            "enable_hot_concept_factors": True,
            "enable_broker_recommend_factors": True,
        },
    }
    line = ra._format_stock_factor_summary("600519", cfg)
    assert line is not None
    assert "主力净流" in line
    assert "行业净流" in line
    assert "🔥热门" in line
    assert "🚀概念" in line
    assert "📄券商推 3次" in line
