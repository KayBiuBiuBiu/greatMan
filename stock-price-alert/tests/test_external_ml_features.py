"""external_ml_features / build_feature_vector 集成开关。"""

from __future__ import annotations

from pathlib import Path

import external_ml_features as emf
from ml_infer import build_feature_vector


def test_defaults_and_keys():
    assert set(emf.external_flow_feature_defaults().keys()) == set(
        emf.EXTERNAL_FLOW_FEATURE_KEYS
    )


def test_stub_disabled_returns_defaults():
    cfg = {"ml_filter": {"external_flow_features_enabled": False}}
    z = emf.extra_flow_features_stub(
        cfg=cfg, code="600000", anchor_trade_date="2026-04-30", root=None
    )
    assert all(v == 0.0 for v in z.values())


def test_build_vector_disabled_no_extra_keys():
    cfg = {"ml_filter": {"external_flow_features_enabled": False}}
    fv = build_feature_vector(
        alert_type="trend_slip",
        anchor_price=10.0,
        pnl_pct=-1.0,
        weak_pillars={"a": True},
        cfg=cfg,
        code6="600000",
        anchor_trade_date="2026-04-30",
    )
    for k in emf.EXTERNAL_FLOW_FEATURE_KEYS:
        assert k not in fv


def test_build_vector_enabled_patches_network(monkeypatch, tmp_path: Path):
    cfg = {
        "ml_filter": {
            "external_flow_features_enabled": True,
            "external_flow_days": 10,
        }
    }

    monkeypatch.setattr(emf, "_cached_fund_flow_aggs", lambda *a: (1.23, 4.56))
    monkeypatch.setattr(
        emf, "_north_chg_ratio", lambda *a, **k: 0.42  # noqa: ARG005
    )
    monkeypatch.setattr(emf, "_cached_lhb_dates", lambda c: frozenset({"2026-04-30"}))
    monkeypatch.setattr(emf, "_cached_lhb_buy_detail", lambda *a: 50_000.0)

    fv = build_feature_vector(
        alert_type="trend_slip",
        anchor_price=10.0,
        pnl_pct=-1.0,
        cfg=cfg,
        root=tmp_path,
        code6="600000",
        anchor_trade_date="2026-04-30",
    )
    assert fv["ext_fund_main_net_pct_mean"] == 1.23
    assert fv["ext_fund_super_net_pct_mean"] == 4.56
    assert fv["ext_north_mv_chg_ratio"] == 0.42
    assert fv["ext_on_lhb"] == 1.0
    assert fv["ext_lhb_net_buy_wan"] == 5.0


def test_clear_caches_runs():
    emf.clear_external_flow_caches()
