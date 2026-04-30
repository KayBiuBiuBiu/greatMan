"""按 HTTP 主机累计连续失败（P1-6 第一块），供退避与运维观测。"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

_enabled: bool = False
_threshold: int = 5
_backoff_cap: float = 32.0
_backoff_base: float = 0.5
_lock = threading.Lock()
_fails: dict[str, int] = {}
_announced: dict[str, int] = {}


def configure_data_health(cfg: dict[str, Any] | None) -> None:
    """在 merge_full_config 末尾调用；未配置时关闭（不改变现网行为）。"""
    global _enabled, _threshold, _backoff_cap, _backoff_base
    dh = (cfg or {}).get("data_health") or {}
    _enabled = bool(dh.get("enabled", False))
    _threshold = max(1, int(dh.get("host_consecutive_fail_threshold", 5)))
    _backoff_cap = float(dh.get("backoff_cap_sec", 32) or 32)
    _backoff_base = float(dh.get("backoff_base_sec", 0.5) or 0.5)


def _netloc(url: str) -> str:
    try:
        p = urlparse(url)
        h = (p.netloc or "").split("@")[-1]
        return h or url[:64]
    except Exception:
        return "unknown"


def record_http_result(
    url: str,
    *,
    ok: bool,
    status_code: int | None = None,
) -> None:
    if not _enabled:
        return
    host = _netloc(url)
    with _lock:
        if ok:
            _fails.pop(host, None)
            _announced.pop(host, None)
            return
        n = _fails.get(host, 0) + 1
        _fails[host] = n
        prev = _announced.get(host, 0)
        if n >= _threshold and prev < _threshold:
            _announced[host] = n
            try:
                from app_logging import get_alert_logger

                get_alert_logger().warning(
                    "data_health host=%s consecutive_fails=%s threshold=%s status=%s url=%s",
                    host,
                    n,
                    _threshold,
                    status_code,
                    url[:120],
                    extra={
                        "event": "data_health_host_threshold",
                        "host": host,
                        "consecutive_fails": n,
                        "status_code": status_code,
                        "url": url[:200],
                    },
                )
            except Exception:
                import logging

                logging.getLogger("data_health").warning(
                    "data_health host=%s consecutive_fails=%s",
                    host,
                    n,
                )


def extra_backoff_sleep_sec(url: str) -> float:
    """在既有随机等待之外追加的指数退避秒数（按主机当前失败计数）。"""
    if not _enabled:
        return 0.0
    host = _netloc(url)
    with _lock:
        n = _fails.get(host, 0)
    if n <= 0:
        return 0.0
    return float(min(_backoff_cap, _backoff_base * (2 ** min(n - 1, 6))))


def host_fail_snapshot() -> dict[str, int]:
    with _lock:
        return dict(_fails)


def degraded_hosts(min_fails: int | None = None) -> list[tuple[str, int]]:
    m = min_fails if min_fails is not None else _threshold
    with _lock:
        return sorted((h, n) for h, n in _fails.items() if n >= m)
