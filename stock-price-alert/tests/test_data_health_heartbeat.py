"""data_health 心跳写入。"""

from __future__ import annotations

import json
from pathlib import Path

import data_health as dh


def test_maybe_write_data_heartbeat_creates_json(tmp_path: Path):
    hb = tmp_path / "pulse.json"
    dh.configure_data_health(
        {
            "data_health": {
                "heartbeat_path": str(hb.name),
                "heartbeat_interval_sec": 3600.0,
            }
        }
    )
    dh.maybe_write_data_heartbeat(
        root=tmp_path,
        watch_count=3,
        attempted=10,
        fails=1,
        trading_session=False,
    )
    assert hb.is_file()
    data = json.loads(hb.read_text(encoding="utf-8"))
    assert data["watch_count"] == 3
    assert data["round_attempted"] == 10
    assert data["round_fails"] == 1


def test_maybe_write_data_heartbeat_respects_interval(tmp_path: Path, monkeypatch):
    hb = tmp_path / "pulse2.json"
    dh.configure_data_health(
        {
            "data_health": {
                "heartbeat_path": str(hb.name),
                "heartbeat_interval_sec": 100.0,
            }
        }
    )
    t = [100.0, 105.0, 280.0]

    def mono():
        return t.pop(0)

    monkeypatch.setattr(dh.time, "monotonic", mono)
    dh.maybe_write_data_heartbeat(
        root=tmp_path, watch_count=1, attempted=5, fails=0, trading_session=True
    )
    first = hb.read_text(encoding="utf-8")
    dh.maybe_write_data_heartbeat(
        root=tmp_path, watch_count=9, attempted=5, fails=5, trading_session=True
    )
    assert hb.read_text(encoding="utf-8") == first
    dh.maybe_write_data_heartbeat(
        root=tmp_path, watch_count=2, attempted=5, fails=0, trading_session=False
    )
    data = json.loads(hb.read_text(encoding="utf-8"))
    assert data["watch_count"] == 2
