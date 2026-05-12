from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from afternoon_selector import (
    afternoon_new_codes_for_pm,
    afternoon_anchor_matches_today,
    load_afternoon_opportunity_metrics_by_code,
    quality_codes_for_pm_display,
)


def test_quality_codes_for_pm_display_disabled_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    p.write_text(
        json.dumps(
            {
                "anchor_date": datetime.now().date().isoformat(),
                "quality_display_codes": ["600000"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    now = datetime(2026, 5, 11, 14, 0)
    assert quality_codes_for_pm_display(p, now=now, cfg={"afternoon_refresh": {}}) is None
    assert (
        quality_codes_for_pm_display(
            p, now=now, cfg={"afternoon_refresh": {"enabled": False}}
        )
        is None
    )


def test_quality_codes_for_pm_display_before_1300_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    d = datetime(2026, 5, 11, 12, 30)
    p.write_text(
        json.dumps(
            {
                "anchor_date": d.date().isoformat(),
                "quality_display_codes": ["600000"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert (
        quality_codes_for_pm_display(
            p, now=d, cfg={"afternoon_refresh": {"enabled": True}}
        )
        is None
    )


def test_quality_codes_for_pm_display_ok(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    d = datetime(2026, 5, 11, 14, 5)
    p.write_text(
        json.dumps(
            {
                "anchor_date": d.date().isoformat(),
                "quality_display_codes": ["600000", "000001"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    s = quality_codes_for_pm_display(
        p,
        now=d,
        cfg={
            "afternoon_refresh": {
                "enabled": True,
                "pm_use_afternoon_quality_pool": True,
            }
        },
    )
    assert s == {"600000", "000001"}


def test_afternoon_new_codes_for_pm(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    d = datetime(2026, 5, 11, 14, 0)
    p.write_text(
        json.dumps(
            {
                "anchor_date": d.date().isoformat(),
                "afternoon_new_codes": ["000001", "600519"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    s = afternoon_new_codes_for_pm(
        p, now=d, cfg={"afternoon_refresh": {"enabled": True}}
    )
    assert s == {"000001", "600519"}


def test_opportunity_codes_alias(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    d = datetime(2026, 5, 11, 14, 0)
    p.write_text(
        json.dumps(
            {
                "anchor_date": d.date().isoformat(),
                "opportunity_codes": ["000001"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    s = afternoon_new_codes_for_pm(
        p, now=d, cfg={"afternoon_refresh": {"enabled": True}}
    )
    assert s == {"000001"}


def test_load_afternoon_opportunity_metrics_by_code(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    d = datetime.now().date().isoformat()
    p.write_text(
        json.dumps(
            {
                "anchor_date": d,
                "afternoon_new_codes": ["600000"],
                "items": [
                    {
                        "code": "600000",
                        "chg_pct": 3.0,
                        "intraday_position": 0.5,
                        "vol_ratio_proxy": 1.8,
                        "role": "afternoon_opportunity",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    m = load_afternoon_opportunity_metrics_by_code(p)
    assert "600000" in m
    assert m["600000"]["vol_ratio_proxy"] == 1.8


def test_afternoon_anchor_matches_today(tmp_path: Path) -> None:
    p = tmp_path / "afternoon_picks.json"
    p.write_text(
        json.dumps({"anchor_date": datetime.now().date().isoformat()}),
        encoding="utf-8",
    )
    assert afternoon_anchor_matches_today(p) is True
    p.write_text(json.dumps({"anchor_date": "1999-01-01"}), encoding="utf-8")
    assert afternoon_anchor_matches_today(p) is False
