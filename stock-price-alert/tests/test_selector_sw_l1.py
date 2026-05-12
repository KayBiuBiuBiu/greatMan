"""申万一级优质股池去重（diversify_quality_by_sw_l1）。"""

from __future__ import annotations

from unittest.mock import patch

from quant_core.selector import diversify_quality_by_sw_l1


def _row(code: str, score: float, sw: str) -> dict:
    return {"code": code, "name": code, "score": score, "sw_l1": sw, "reason": "x"}


def test_sw_l1_disabled_uses_top_n():
    rows = [_row("000001", 9.0, "801010.SI"), _row("000002", 8.0, "801010.SI")]
    qs = {"sw_l1_pool": {"enabled": False}}
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=1)
    assert stats["mode"] == "legacy_top_n"
    assert len(out) == 1


def test_sw_l1_one_per_industry():
    rows = [
        _row("000001", 8.0, "801010.SI"),
        _row("000002", 9.0, "801010.SI"),
        _row("600000", 7.5, "801020.SI"),
    ]
    qs = {
        "score_min_quality": 7.0,
        "sw_l1_pool": {"enabled": True, "picks_per_industry": 1, "max_stocks": 10},
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20)
    assert stats["mode"] == "sw_l1_diversified"
    codes = {r["code"] for r in out}
    assert codes == {"000002", "600000"}


def test_sw_l1_skip_industry_below_min_score():
    rows = [
        _row("000001", 6.5, "801010.SI"),
        _row("600000", 8.0, "801020.SI"),
    ]
    qs = {
        "score_min_quality": 7.0,
        "sw_l1_pool": {"enabled": True, "min_score": 7.0, "max_stocks": 10},
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20)
    assert len(out) == 1
    assert out[0]["code"] == "600000"
    assert stats["skipped_industries_below_min"] >= 1


def test_sw_l1_global_cap_trims_lowest():
    rows = [
        _row("000001", 9.0, "801010.SI"),
        _row("000002", 8.0, "801020.SI"),
        _row("000003", 7.0, "801030.SI"),
    ]
    qs = {
        "score_min_quality": 6.0,
        "sw_l1_pool": {"enabled": True, "max_stocks": 2, "min_score": 6.0},
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20)
    assert len(out) == 2
    assert stats["trimmed_lowest"] == 1
    assert [r["code"] for r in out] == ["000001", "000002"]


@patch("quant_core.selector._rank_sw_l1_strength_tiers")
def test_strength_top_tier_two_picks(mock_rank):
    mock_rank.return_value = (
        {"801010.SI": "top", "801020.SI": "mid"},
        {"degraded": False, "preview": []},
    )
    rows = [
        _row("000001", 8.0, "801010.SI"),
        _row("000002", 7.5, "801010.SI"),
        _row("600000", 8.2, "801020.SI"),
    ]
    qs = {
        "score_min_quality": 7.0,
        "sw_l1_pool": {
            "enabled": True,
            "strength_tiers_enabled": True,
            "top_third_picks": 2,
            "mid_third_picks": 1,
            "max_stocks": 10,
        },
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20, cfg={})
    assert stats["strength_active"] is True
    assert stats["mode"] == "sw_l1_diversified_strength"
    codes = [r["code"] for r in out]
    assert set(codes) == {"000001", "000002", "600000"}
    assert all(r.get("sw_l1_strength_tier") for r in out)


@patch("quant_core.selector._rank_sw_l1_strength_tiers")
def test_strength_bottom_tier_requires_higher_score(mock_rank):
    mock_rank.return_value = (
        {"801010.SI": "bottom"},
        {"degraded": False, "preview": []},
    )
    rows = [
        _row("000001", 7.2, "801010.SI"),
        _row("000002", 7.6, "801010.SI"),
    ]
    qs = {
        "score_min_quality": 7.0,
        "sw_l1_pool": {
            "enabled": True,
            "strength_tiers_enabled": True,
            "bottom_third_max_picks": 1,
            "bottom_tier_min_score_delta": 0.5,
            "max_stocks": 10,
        },
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20, cfg={})
    assert len(out) == 1
    assert out[0]["code"] == "000002"


@patch("quant_core.selector._rank_sw_l1_strength_tiers")
def test_strength_degraded_falls_back_uniform(mock_rank):
    mock_rank.return_value = ({}, {"degraded": True, "preview": []})
    rows = [
        _row("000001", 9.0, "801010.SI"),
        _row("000002", 8.5, "801010.SI"),
    ]
    qs = {
        "score_min_quality": 7.0,
        "sw_l1_pool": {
            "enabled": True,
            "strength_tiers_enabled": True,
            "picks_per_industry": 1,
            "max_stocks": 10,
        },
    }
    out, stats = diversify_quality_by_sw_l1(rows, qs=qs, top_n_per_strategy=20, cfg={})
    assert stats["strength_active"] is False
    assert stats["mode"] == "sw_l1_diversified"
    assert len(out) == 1
    assert out[0]["code"] == "000001"
