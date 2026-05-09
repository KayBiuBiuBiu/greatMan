"""异步分钟 K 缓存读写与配置合并。"""

from __future__ import annotations

import json
from pathlib import Path

from async_minute_kline import (
    clear_async_minute_kline_cache,
    get_async_minute_kline_for_code,
    stop_async_minute_kline_worker,
    update_async_minute_kline_context,
)


def test_get_cached_miss_and_hit() -> None:
    clear_async_minute_kline_cache()
    assert get_async_minute_kline_for_code("600000") is None
    from async_minute_kline import _lock, _minute_kline_cache

    with _lock:
        _minute_kline_cache["600000"] = {"bar_count": 1, "last_close": 10.0}
    snap = get_async_minute_kline_for_code("600000")
    assert snap is not None
    assert snap["bar_count"] == 1
    snap["bar_count"] = 99
    with _lock:
        assert _minute_kline_cache["600000"]["bar_count"] == 1
    clear_async_minute_kline_cache()
    stop_async_minute_kline_worker()


def test_update_context_from_watch() -> None:
    cfg = {
        "performance": {"async_minute_kline": {"refresh_sec": 60, "max_bars": 100}},
        "sources": {"eastmoney_ut": "fa5fd1943c7b386f172d6893dbfba10b"},
    }
    watch = [
        {"enabled": True, "code": "600000", "market": "sh"},
        {"enabled": True, "code": "600000", "market": "sh"},
        {"enabled": True, "code": "1", "market": "sz"},
    ]
    update_async_minute_kline_context(watch, cfg)
    from async_minute_kline import _lock, _targets, _refresh_sec, _max_bars

    with _lock:
        assert ("600000", "sh") in _targets
        assert _targets.count(("600000", "sh")) == 1
        assert ("000001", "sz") in _targets
        assert _refresh_sec == 60.0
        assert _max_bars == 100


def test_merge_full_config_async_minute_defaults() -> None:
    from run_alert import merge_full_config

    cfg = merge_full_config(json.loads(Path("config.example.json").read_text(encoding="utf-8")))
    am = (cfg.get("performance") or {}).get("async_minute_kline")
    assert isinstance(am, dict)
    assert "enabled" in am
    assert "refresh_sec" in am
    assert "max_bars" in am
