from __future__ import annotations

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


def test_stock_financial_cache_roundtrip(tmp_path) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "600519",
        "financial",
        {"roe_ttm": 0.21, "revenue_yoy": 0.13},
        cache_date="2026-05-26",
    )

    assert qt.fetch_financial_factors("600519", cache_only=True)["roe_ttm"] == 0.21


def test_fetch_financial_factors_uses_cache_when_cache_only(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "000001",
        "margin",
        {"margin_balance": 120000000.0, "margin_change_pct_5d": 0.05},
        cache_date="2026-05-25",
    )
    monkeypatch.setattr(qt, "_get_pro", lambda: pytest.fail("cache_only should not request Tushare"))

    data = qt.fetch_margin_factor("000001", cache_only=True)

    assert data["margin_change_pct_5d"] == 0.05


def test_fetch_functions_return_expected_shapes(tmp_path, monkeypatch) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)

    class FakePro:
        def daily_basic(self, **kwargs):
            return pd.DataFrame(
                [{"ts_code": "600519.SH", "trade_date": "20260525", "pe_ttm": 18.5, "pb": 2.3}]
            )

        def fina_indicator(self, **kwargs):
            return pd.DataFrame(
                [{"ts_code": "600519.SH", "end_date": "20251231", "roe_dt": 12.0, "debt_to_assets": 45.0}]
            )

        def income(self, **kwargs):
            return pd.DataFrame(
                [
                    {"end_date": "20240331", "revenue": 100.0, "n_income_attr_p": 20.0},
                    {"end_date": "20240630", "revenue": 100.0, "n_income_attr_p": 20.0},
                    {"end_date": "20240930", "revenue": 100.0, "n_income_attr_p": 20.0},
                    {"end_date": "20241231", "revenue": 100.0, "n_income_attr_p": 20.0},
                    {"end_date": "20250331", "revenue": 115.0, "n_income_attr_p": 24.0},
                ]
            )

        def margin_detail(self, **kwargs):
            return pd.DataFrame(
                [
                    {"trade_date": f"202605{d:02d}", "ts_code": "600519.SH", "rzye": 1.0e8 + d * 1e6}
                    for d in range(20, 27)
                ]
            )

        def top_inst(self, **kwargs):
            return pd.DataFrame(
                [
                    {"exalter": "机构专用", "buy_amount": 2_000_000.0, "sell_amount": 500_000.0},
                    {"exalter": "其他席位", "buy_amount": 9_000_000.0, "sell_amount": 0.0},
                ]
            )

    monkeypatch.setattr(qt, "_get_pro", lambda: FakePro())

    fin = qt.fetch_financial_factors("600519")
    margin = qt.fetch_margin_factor("600519")
    top = qt.fetch_top_inst_factor("600519")

    assert fin["pe_ttm"] == 18.5
    assert fin["roe_ttm"] == pytest.approx(0.12)
    assert fin["revenue_yoy"] == pytest.approx(0.15)
    assert margin["margin_change_pct_5d"] is not None
    assert top == {"inst_buy_net": 1_500_000.0, "inst_buy_count": 1}


def test_get_real_score_applies_cached_factor_bonus(tmp_path) -> None:
    import quote_tushare as qt
    from quant_core.selector import get_real_score

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache("600519", "financial", {"roe_ttm": 0.12, "revenue_yoy": 0.2})
    qt._write_stock_factor_cache("600519", "margin", {"margin_change_pct_5d": 0.05})

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
            "enable_financial_factors": True,
            "enable_margin_factors": True,
            "enable_top_inst_factors": False,
            "factor_weights": {
                "trend": 3.0,
                "box_position": 2.0,
                "volatility": 1.5,
                "volume_ratio": 1.5,
                "roe_min": 0.08,
                "revenue_yoy_min": 0.10,
                "margin_change_pct_threshold": 0.03,
                "max_bonus": 3.0,
            },
        }
    }

    score_without = get_real_score("600519", df=df, cfg={"quant_selector": {}})
    score_with = get_real_score("600519", df=df, cfg=cfg)

    assert score_with >= score_without
    assert score_with <= 10.0


def test_factor_summary_uses_plain_chinese_and_cleans_units(tmp_path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "600519",
        "financial",
        {
            "roe_ttm": 0.635,
            "revenue_yoy": 0.127,
            "profit_yoy": 1.906,
            "pe_ttm": 84.2,
            "pb": 1.4,
        },
    )
    qt._write_stock_factor_cache(
        "600519",
        "margin",
        {"margin_balance": 141368312.0, "margin_change_pct_5d": 156.985},
    )
    qt._write_stock_factor_cache(
        "600519",
        "top_inst",
        {"inst_buy_net": 2_300_000.0, "inst_buy_count": 2},
    )
    cfg = {
        "display": {"simplify_factor_text": True},
        "quant_selector": {
            "enable_financial_factors": True,
            "enable_margin_factors": True,
            "enable_top_inst_factors": True,
        },
    }

    line = ra._format_stock_factor_summary("600519", cfg)

    assert line is not None
    assert "净资产收益率 63.5%（异常高）" in line
    assert "营收同比 +12.7%" in line
    assert "净利润同比 +190.6%" in line
    assert "市盈率 84.2" in line
    assert "市净率 1.4" in line
    assert "融资余额 1.41亿" in line
    assert "融资余额5日变化 大幅波动" in line
    assert "ROE" not in line
    assert "141368312万" not in line


def test_factor_summary_labels_negative_roe_and_abnormal_margin(tmp_path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "000001",
        "financial",
        {
            "roe_ttm": -0.949,
            "revenue_yoy": 0.10,
            "profit_yoy": -1.228,
            "pe_ttm": 12.3,
            "pb": 0.8,
        },
    )
    qt._write_stock_factor_cache(
        "000001",
        "margin",
        {"margin_balance": 1413683120000000.0, "margin_change_pct_5d": 1.2},
    )
    cfg = {
        "display": {"simplify_factor_text": True},
        "quant_selector": {
            "enable_financial_factors": True,
            "enable_margin_factors": True,
            "enable_top_inst_factors": False,
        },
    }

    line = ra._format_stock_factor_summary("000001", cfg)

    assert line is not None
    assert "净资产收益率 -94.9%（严重亏损）" in line
    assert "异常高" not in line
    assert "净利润同比 -122.8%（暴降）" in line
    assert "融资余额" not in line


def test_margin_cache_rejects_exchange_level_dirty_balance(tmp_path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "000967",
        "margin",
        {"margin_balance": 1.417203136742e12, "margin_change_pct_5d": 156.46},
    )
    m = qt.fetch_margin_factor("000967", cache_only=True)
    assert m.get("margin_balance") is None
    assert m.get("margin_change_pct_5d") is None

    cfg = {
        "display": {"simplify_factor_text": True},
        "quant_selector": {
            "enable_financial_factors": False,
            "enable_margin_factors": True,
        },
    }
    line = ra._format_stock_factor_summary("000967", cfg)
    assert line is None or "融资" not in line


def test_buy_filter_blocks_when_basic_quality_cache_fails(tmp_path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "600519",
        "financial",
        {"roe_ttm": 0.06, "pe_ttm": 45.0},
    )
    pack = {"q": {"code": "600519"}, "rule": {"code": "600519"}}
    cfg = {
        "strategy_buy_filter": {
            "enabled": True,
            "min_volume_ratio": 0,
            "block_weak_bear": False,
            "require_basic_quality": True,
            "basic_quality_roe_min": 0.10,
            "basic_quality_pe_max": 30.0,
            "sector_buy_cross_check": {"enabled": False},
        }
    }

    reason = ra._strategy_buy_realtime_blocked(pack, cfg)

    assert reason is not None
    assert "基本面未达标" in reason
    assert "净资产收益率" in reason
    assert "市盈率" in reason


def test_position_suggestion_warns_on_margin_retreat(tmp_path) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    qt._write_stock_factor_cache(
        "600519",
        "margin",
        {"margin_balance": 1_000_000_000.0, "margin_change_pct_5d": -0.25},
    )
    pack = {"q": {"code": "600519"}, "rule": {"code": "600519"}}
    cfg = {
        "position_suggestion": {
            "enabled": True,
            "rules": {
                "sell": {
                    "profit_break_ma5": False,
                    "loss_below_ma20_and_ma60": False,
                    "market_weak_bear_sell": False,
                    "margin_retreat_enabled": True,
                    "margin_retreat_threshold": -0.20,
                },
                "add": {},
            },
        }
    }

    act, why = ra._get_position_suggestion(pack, cfg, pnl_pct=0.0, bearish_prob=None)

    assert act == "卖出"
    assert "融资盘撤退" in why
    assert "25.0%" in why


def test_get_factor_comment_priority_and_fallback() -> None:
    import run_alert as ra

    assert (
        ra._get_factor_comment({"roe_ttm": -0.21})
        == "⚠️ 严重亏损，风险极高，建议卖出"
    )
    assert (
        ra._get_factor_comment({"roe_ttm": -0.05})
        == "⚠️ 亏损状态，谨慎参与"
    )
    assert (
        ra._get_factor_comment({"revenue_yoy": 0.25, "profit_yoy": -0.2})
        == "📉 增收不增利，警惕利润陷阱"
    )
    assert (
        ra._get_factor_comment({"revenue_yoy": 0.25, "profit_yoy": 1.2})
        == "🔥 业绩爆发，可重点关注"
    )
    assert (
        ra._get_factor_comment({"inst_buy_net": 6_000_000.0, "inst_buy_count": 1})
        == "🏦 机构净买入，有资金关注"
    )
    assert (
        ra._get_factor_comment({"margin_change_pct_5d": 1.2})
        == "📊 融资余额大幅波动，短线不确定"
    )
    assert ra._get_factor_comment({}) == "📊 基本面中性，结合技术面决策"
