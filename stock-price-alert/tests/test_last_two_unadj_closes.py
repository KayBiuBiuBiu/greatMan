"""quote_tushare.last_two_unadj_closes_on_or_before 日期过滤。"""

from __future__ import annotations

from quote_tushare import last_two_unadj_closes_on_or_before


def test_last_two_unadj_respects_day_iso(monkeypatch) -> None:
    rows = [
        ("2026-05-08", 1.0, 1.0, 1.0, 10.0, 1e6),
        ("2026-05-09", 1.0, 1.0, 1.0, 11.0, 1e6),
        ("2026-05-12", 1.0, 1.0, 1.0, 12.5, 1e6),
    ]

    def fake_fetch(secid: str, *, lmt: int):
        _ = secid, lmt
        return rows

    monkeypatch.setattr(
        "quote_tushare.try_fetch_daily_rows_for_secid",
        fake_fetch,
    )
    c0, c1 = last_two_unadj_closes_on_or_before("1.600000", "2026-05-09")
    assert c0 == 11.0
    assert c1 == 10.0

    c_only, prev = last_two_unadj_closes_on_or_before("1.600000", "2026-05-08")
    assert c_only == 10.0
    assert prev is None


def test_last_two_unadj_empty_when_all_after_day(monkeypatch) -> None:
    def fake_fetch(secid: str, *, lmt: int):
        _ = secid, lmt
        return [("2026-06-01", 1.0, 1.0, 1.0, 9.0, 1.0)]

    monkeypatch.setattr(
        "quote_tushare.try_fetch_daily_rows_for_secid",
        fake_fetch,
    )
    assert last_two_unadj_closes_on_or_before("1.600000", "2026-05-01") == (
        None,
        None,
    )
