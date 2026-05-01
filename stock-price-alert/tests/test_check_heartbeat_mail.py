"""check_heartbeat_mail 辅助函数。"""

from __future__ import annotations

from datetime import datetime

from check_heartbeat_mail import _default_max_age_sec, _parse_ts_iso


def test_default_max_age_sec_from_interval():
    assert _default_max_age_sec(180) == max(300.0, 180 * 2 + 120)
    assert _default_max_age_sec(0) == 900.0


def test_parse_ts_iso():
    dt = _parse_ts_iso({"ts_iso": "2026-04-30T15:20:01"})
    assert dt == datetime(2026, 4, 30, 15, 20, 1)
