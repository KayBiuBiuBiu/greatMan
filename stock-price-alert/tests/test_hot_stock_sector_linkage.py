"""热股榜 × 热门板块联动：双火标记、加分、热股榜分区。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest


def _configure_tmp_cache(tmp_path: Path) -> None:
    import quote_tushare as qt

    qt.configure_tushare_from_sources(
        {
            "tushare": {
                "enabled": False,
                "financial_cache_db_path": str(tmp_path / "f.db"),
            }
        }
    )


def test_dual_hot_factor_and_comment(tmp_path: Path) -> None:
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    cfg = {
        "display": {"simplify_factor_text": True, "show_hot_stock_in_factor": True},
        "quant_selector": {"enable_hot_stock_factors": True},
    }
    line = ra._format_stock_factor_summary("600519", cfg, dual_hot=True)
    assert line is not None
    assert "🔥🔥" in line
    comment = ra._format_stock_factor_comment("600519", cfg, dual_hot=True)
    assert comment is not None
    assert "双热点共振" in comment


def test_factor_bonus_dual_hot_extra(tmp_path: Path, monkeypatch) -> None:
    import quote_tushare as qt
    import run_alert as ra
    from quant_core.selector import _factor_bonus, _selector_quant_cfg

    _configure_tmp_cache(tmp_path)
    monkeypatch.setattr(qt, "is_hot_stock", lambda code, **kw: code == "600519")
    monkeypatch.setattr(
        ra, "stock_is_dual_hot_resonance", lambda code, cfg, **kw: code == "600519"
    )
    cfg = {
        "quant_selector": {
            "enable_hot_stock_factors": True,
            "factor_weights": {
                "hot_stock_bonus": 1.0,
                "hot_stock_extra_bonus": 1.0,
                "max_bonus": 5.0,
            },
        }
    }
    qs = _selector_quant_cfg(cfg)
    weights = qs.get("factor_weights") or {}
    bonus = _factor_bonus(
        "600519",
        qs,
        weights,
        cfg=cfg,
        financial_factors=None,
        margin_factors=None,
        top_inst_factors=None,
    )
    assert bonus >= 2.0


def test_fetch_hot_stocks_ranked_from_cache(tmp_path: Path) -> None:
    import quote_tushare as qt

    _configure_tmp_cache(tmp_path)
    iso = date.today().isoformat()
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=iso,
        data={
            "codes": ["600519", "000001"],
            "ranks": {"600519": 2, "000001": 1},
            "trade_date": iso,
        },
    )
    ranked = qt.fetch_hot_stocks_ranked(cache_only=True, top_n=10)
    assert ranked[0] == ("000001", 1)
    assert ("600519", 2) in ranked


def test_emit_hot_stock_list_section_disabled(tmp_path: Path, monkeypatch) -> None:
    import run_alert as ra

    lines: list[str] = []
    monkeypatch.setattr(ra, "_emit_main_line", lambda s, **kw: lines.append(s))
    ra._emit_hot_stock_list_section({"display": {"show_hot_stock_list": False}})
    assert not lines


def test_emit_hot_stock_list_section_enabled(tmp_path: Path, monkeypatch) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    iso = date.today().isoformat()
    qt._write_json_table_row(
        "hot_stock_cache",
        key_col="trade_date",
        key_val=iso,
        data={"codes": ["600519"], "ranks": {"600519": 1}, "trade_date": iso},
    )
    lines: list[str] = []
    monkeypatch.setattr(ra, "_emit_main_line", lambda s, **kw: lines.append(s))
    monkeypatch.setattr(
        qt,
        "fetch_hot_stocks_ranked",
        lambda **kw: [("600519", 1)],
    )
    monkeypatch.setattr(
        ra,
        "fetch_quote_metrics",
        lambda code, mkt, **kw: {"price": 10.5, "change_pct": 2.3},
    )
    monkeypatch.setattr(ra, "get_stock_name", lambda c: "茅台")
    ra._emit_hot_stock_list_section(
        {"display": {"show_hot_stock_list": True, "hot_stock_list_top_n": 5}}
    )
    assert any("【热股榜机会】" in x for x in lines)
    assert any("热股#1" in x and "600519" in x for x in lines)


def test_stock_fire_marker_details_count(tmp_path: Path, monkeypatch) -> None:
    import quote_tushare as qt
    import run_alert as ra

    _configure_tmp_cache(tmp_path)
    monkeypatch.setattr(qt, "is_hot_stock", lambda code, **kw: True)
    monkeypatch.setattr(
        qt, "hot_concept_factor_label", lambda code, **kw: "🔥概念"
    )
    monkeypatch.setattr(
        ra, "stock_is_dual_hot_resonance", lambda code, cfg, **kw: True
    )
    cfg = {
        "display": {
            "show_hot_stock_in_factor": True,
            "show_hot_concept_in_factor": True,
        },
        "quant_selector": {
            "enable_hot_stock_factors": True,
            "enable_hot_concept_factors": True,
        },
    }
    count, parts = ra.stock_fire_marker_details("600519", cfg)
    assert count == 4
    assert "热股榜" in parts
    assert "热门概念" in parts
    assert "双热点共振" in parts


def test_maybe_notify_hot_fire_wecom_sends(tmp_path: Path, monkeypatch) -> None:
    import run_alert as ra

    sent: list[tuple[str, str]] = []

    def _fake_send(subject: str, body: str, *, app_cfg=None) -> bool:
        sent.append((subject, body))
        return True

    monkeypatch.setattr(ra, "stock_fire_marker_details", lambda *a, **k: (3, ["热股榜", "双热点共振"]))
    monkeypatch.setattr(ra, "channel_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(ra, "send_wecom_only_alert", _fake_send)
    monkeypatch.setattr(ra, "_emit_watch_line", lambda *a, **k: None)

    class _Args:
        no_notify = False

    cfg = {
        "notifications": {
            "hot_fire_wecom_alert": {"enabled": True, "min_fires": 2},
            "wecom_webhook": {"enabled": True, "webhook_url": "http://x"},
        }
    }
    state: dict = {}
    ra._maybe_notify_hot_fire_wecom(
        code="301217",
        cfg=cfg,
        args=_Args(),
        state=state,
        rk="sz.301217",
        bucket="持仓",
        cooldown_min=5.0,
        now_ts=1000.0,
        disp_name="铜冠铜箔",
        now_price=185.6,
        chg_pct=4.17,
    )
    assert len(sent) == 1
    assert "3🔥" in sent[0][0]
    assert "3🔥" in sent[0][1]
    assert "热股榜" in sent[0][1]
    assert state["hot_fire_sz.301217"] == 1000.0


def test_maybe_notify_hot_fire_skips_below_min(tmp_path: Path, monkeypatch) -> None:
    import run_alert as ra

    monkeypatch.setattr(ra, "stock_fire_marker_details", lambda *a, **k: (1, ["热股榜"]))
    monkeypatch.setattr(
        ra,
        "send_wecom_only_alert",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    class _Args:
        no_notify = False

    ra._maybe_notify_hot_fire_wecom(
        code="600519",
        cfg={"notifications": {"hot_fire_wecom_alert": {"min_fires": 2}}},
        args=_Args(),
        state={},
        rk="sh.600519",
        bucket="优质",
        cooldown_min=5.0,
        now_ts=1.0,
        disp_name="茅台",
    )
