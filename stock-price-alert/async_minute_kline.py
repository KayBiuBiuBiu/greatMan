"""异步维护当日分钟 K 摘要：后台线程周期性拉取，主轮询仅 O(1) 读缓存（无网络）。"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.RLock()
_minute_kline_cache: dict[str, dict[str, Any]] = {}
_targets: list[tuple[str, str]] = []
_refresh_sec: float = 300.0
_max_bars: int = 240
_ut: str | None = None
_stop = threading.Event()
_worker: threading.Thread | None = None


def _pair_from_rule(rule: dict[str, Any]) -> tuple[str, str] | None:
    c = str(rule.get("code") or "").strip()
    if not c.isdigit() or len(c) > 6:
        return None
    c6 = c.zfill(6)
    if len(c6) != 6:
        return None
    m = str(rule.get("market") or "").strip().lower()
    if m in ("sh", "1", "sse"):
        mkt = "sh"
    elif m in ("sz", "0", "szse"):
        mkt = "sz"
    else:
        mkt = "sh" if c6.startswith(("6", "9")) else "sz"
    return c6, mkt


def update_async_minute_kline_context(
    watch: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> None:
    """由主线程每轮更新标的列表与拉取参数（在 RLock 内拷贝）。"""
    global _targets, _refresh_sec, _max_bars, _ut
    perf = cfg.get("performance") or {}
    am = perf.get("async_minute_kline") if isinstance(perf, dict) else None
    if not isinstance(am, dict):
        am = {}
    pairs: list[tuple[str, str]] = []
    for r in watch:
        if not isinstance(r, dict) or not r.get("enabled", True):
            continue
        p = _pair_from_rule(r)
        if p is not None:
            pairs.append(p)
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for c, m in pairs:
        if c in seen:
            continue
        seen.add(c)
        deduped.append((c, m))
    ut_raw = (cfg.get("sources") or {}).get("eastmoney_ut")
    ut_s = str(ut_raw).strip() if ut_raw else None
    with _lock:
        _targets = deduped
        _refresh_sec = max(30.0, float(am.get("refresh_sec", 300) or 300))
        _max_bars = max(32, int(am.get("max_bars", 240) or 240))
        _ut = ut_s


def get_async_minute_kline_for_code(code: str) -> dict[str, Any] | None:
    """主轮询只读缓存；无则 None。返回浅拷贝避免调用方改写字典破坏缓存。"""
    c = str(code or "").strip().zfill(6)
    if len(c) != 6 or not c.isdigit():
        return None
    with _lock:
        hit = _minute_kline_cache.get(c)
        if hit is None:
            return None
        return dict(hit)


def _worker_loop() -> None:
    from quote_eastmoney import get_stock_minute_kline_summary_today

    first = True
    while not _stop.is_set():
        with _lock:
            codes = list(_targets)
            ref = float(_refresh_sec)
            mx = int(_max_bars)
            ut = _ut
        new_snaps: dict[str, dict[str, Any]] = {}
        for code, mkt in codes:
            if _stop.is_set():
                break
            try:
                snap = get_stock_minute_kline_summary_today(
                    code,
                    mkt,
                    ut=ut,
                    lmt=mx,
                    cache_ttl_sec=0.0,
                )
                if isinstance(snap, dict) and snap:
                    new_snaps[code] = snap
            except Exception:
                pass
            time.sleep(0.03)
        active = {c for c, _ in codes}
        with _lock:
            for k in list(_minute_kline_cache.keys()):
                if k not in active:
                    del _minute_kline_cache[k]
            _minute_kline_cache.update(new_snaps)
        if first:
            first = False
        if _stop.wait(timeout=max(1.0, ref)):
            break


def ensure_async_minute_kline_worker() -> None:
    """启动守护线程（幂等）。"""
    global _worker, _stop
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop = threading.Event()
        _worker = threading.Thread(
            target=_worker_loop,
            name="async_minute_kline",
            daemon=True,
        )
        _worker.start()


def stop_async_minute_kline_worker(*, join_timeout: float = 4.0) -> None:
    global _worker
    _stop.set()
    t = _worker
    if t is not None and t.is_alive():
        t.join(timeout=join_timeout)
    _worker = None


def clear_async_minute_kline_cache() -> None:
    with _lock:
        _minute_kline_cache.clear()
