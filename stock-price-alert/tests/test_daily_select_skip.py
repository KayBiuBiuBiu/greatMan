from pathlib import Path

from run_alert import _daily_picks_generated_day, _daily_select_done_today


def test_daily_picks_generated_day_reads_iso_date(tmp_path: Path) -> None:
    p = tmp_path / "daily_picks.json"
    p.write_text('{"generated_at": "2026-05-26T08:01:22", "优质股": []}', encoding="utf-8")

    assert _daily_picks_generated_day(p) == "2026-05-26"


def test_daily_select_done_today_from_state(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")

    assert _daily_select_done_today(
        config_path=cfg,
        state={"__daily_select_done__": "2026-05-26"},
        today="2026-05-26",
    )


def test_daily_select_done_today_from_daily_picks(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    (tmp_path / "daily_picks.json").write_text(
        '{"generated_at": "2026-05-26 08:01:22", "优质股": []}',
        encoding="utf-8",
    )

    assert _daily_select_done_today(config_path=cfg, state={}, today="2026-05-26")


def test_daily_select_done_today_from_history_snapshot(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    hist = tmp_path / "data" / "picks_history"
    hist.mkdir(parents=True)
    (hist / "2026-05-26.json").write_text('{"优质股": []}', encoding="utf-8")

    assert _daily_select_done_today(config_path=cfg, state={}, today="2026-05-26")


def test_daily_select_done_today_false_when_stale(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    (tmp_path / "daily_picks.json").write_text(
        '{"generated_at": "2026-05-25T08:01:22", "优质股": []}',
        encoding="utf-8",
    )

    assert not _daily_select_done_today(config_path=cfg, state={}, today="2026-05-26")
