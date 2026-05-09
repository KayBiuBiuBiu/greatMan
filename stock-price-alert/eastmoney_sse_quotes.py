"""东方财富行情 SSE（/api/qt/stock/sse）：同源 JSON 行推送，作 realtime_hub 的推送通道。

说明：东财站点对通用 WebSocket 升级常返回非 ws(s) 的跳转，websocket-client 无法作为
「单连接多标的」稳定方案；SSE 已实测可返回 f43/f57/f58/f170 等字段。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from typing import Any, Callable

import requests

from quote_eastmoney import secid_for
from utils import get_requests_proxies, get_requests_verify

_log = logging.getLogger("eastmoney_sse")

DEFAULT_SSE_URL = "https://push2.eastmoney.com/api/qt/stock/sse"
DEFAULT_FIELDS = "f43,f57,f58,f170,f46,f13"

__all__ = [
    "DEFAULT_FIELDS",
    "DEFAULT_SSE_URL",
    "build_sse_quote_url",
    "parse_sse_quote_line",
    "start_sse_partition_threads",
]


def build_sse_quote_url(
    *,
    secid: str,
    ut: str,
    base_url: str = DEFAULT_SSE_URL,
    fields: str = DEFAULT_FIELDS,
) -> str:
    q = {
        "fields": fields,
        "mpi": "1000",
        "invt": "2",
        "fltt": "2",
        "secid": str(secid).strip(),
        "ut": str(ut).strip(),
    }
    base = base_url.split("?")[0]
    sep = "&" if "?" in base_url else "?"
    return f"{base}{sep}{urllib.parse.urlencode(q)}"


def parse_sse_quote_line(line: str) -> dict[str, Any] | None:
    """解析单行 `data: {...}`；rc!=0 或 data 空则返回 None。"""
    s = str(line or "").strip()
    if not s.startswith("data:"):
        return None
    raw = s[5:].strip()
    if not raw:
        return None
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        return None
    rc = j.get("rc")
    try:
        rc_i = int(rc) if rc is not None else -1
    except (TypeError, ValueError):
        rc_i = -1
    if rc_i != 0:
        return None
    data = j.get("data")
    if not isinstance(data, dict):
        return None
    return data


def _em_row_to_metrics(data: dict[str, Any], *, fallback_market: str) -> dict[str, Any] | None:
    """SSE data 对象 → 与 fetch_quote_metrics 对齐的 dict。"""
    code = str(data.get("f57") or "").strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    mraw = data.get("f13")
    if mraw is not None:
        mi = int(float(mraw))
        market = "sh" if mi == 1 else "sz" if mi == 0 else ""
    else:
        market = str(fallback_market or "sh").strip().lower()
    if market not in ("sh", "sz"):
        market = "sh"
    p = float(data.get("f43") or 0.0)
    if p <= 0:
        return None
    chg = data.get("f170")
    chgf = float(chg) if chg is not None else None
    return {
        "code": code,
        "market": market,
        "name": str(data.get("f58") or ""),
        "price": round(p, 3),
        "change_pct": chgf,
        "amount_yuan": 0.0,
        "float_mv_yuan": 0.0,
        "total_mv_yuan": 0.0,
        "price_source": "eastmoney_sse",
    }


def _eligible_rules(watch_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in watch_rules or []:
        code = str(rule.get("code") or "").strip()
        market = str(rule.get("market") or "sh").strip().lower()
        if not code.isdigit() or len(code) != 6:
            continue
        out.append({**rule, "code": code.zfill(6), "market": market})
    return out


def sse_burst_read(
    *,
    secid: str,
    market_fallback: str,
    ut: str,
    base_url: str,
    fields: str,
    stop: threading.Event,
    on_metrics: Callable[[dict[str, Any]], None],
    burst_sec: float,
    read_timeout_sec: float,
) -> None:
    """单次连接：读最多 burst_sec 秒推送后返回（便于线程内轮询多标的）。"""
    url = build_sse_quote_url(secid=secid, ut=ut, base_url=base_url, fields=fields)
    headers = {
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    t_end = time.monotonic() + max(1.0, float(burst_sec))
    r: requests.Response | None = None
    try:
        kw: dict[str, Any] = dict(
            url=url,
            stream=True,
            timeout=(10, max(20.0, float(read_timeout_sec))),
            headers=headers,
            verify=get_requests_verify(),
        )
        px = get_requests_proxies()
        if px:
            kw["proxies"] = px
        r = requests.get(**kw)
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if stop.is_set() or time.monotonic() >= t_end:
                break
            if not line:
                continue
            data = parse_sse_quote_line(line)
            if not data:
                continue
            m = _em_row_to_metrics(data, fallback_market=market_fallback)
            if m:
                on_metrics(m)
    except Exception as e:
        if not stop.is_set():
            _log.debug("sse burst %s: %s", secid, e)
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


def sse_partition_worker_loop(
    *,
    get_rules: Callable[[], list[dict[str, Any]]],
    slot_idx: int,
    n_slots: int,
    ut: str,
    base_url: str,
    fields: str,
    stop: threading.Event,
    on_metrics: Callable[[dict[str, Any]], None],
    reconnect_sec: float,
    burst_sec: float,
    read_timeout_sec: float,
) -> None:
    """第 slot_idx 条工作线程：对分区内标的按 burst 轮询 SSE。"""
    while not stop.is_set():
        rules = _eligible_rules(get_rules())
        mine = [r for i, r in enumerate(rules) if (i % max(1, n_slots)) == slot_idx]
        if not mine:
            if stop.wait(timeout=max(2.0, reconnect_sec)):
                return
            continue
        for rule in mine:
            if stop.is_set():
                return
            code = str(rule["code"])
            market = str(rule.get("market") or "sh").strip().lower()
            try:
                sid = secid_for(code, market)
            except Exception:
                continue
            sse_burst_read(
                secid=sid,
                market_fallback=market,
                ut=ut,
                base_url=base_url,
                fields=fields,
                stop=stop,
                on_metrics=on_metrics,
                burst_sec=burst_sec,
                read_timeout_sec=read_timeout_sec,
            )
        if stop.wait(timeout=0.05):
            return


def start_sse_partition_threads(
    *,
    get_rules: Callable[[], list[dict[str, Any]]],
    n_slots: int,
    ut: str,
    base_url: str,
    fields: str,
    stop: threading.Event,
    on_metrics: Callable[[dict[str, Any]], None],
    reconnect_sec: float,
    burst_sec: float,
    read_timeout_sec: float,
) -> list[threading.Thread]:
    threads: list[threading.Thread] = []
    for slot in range(max(1, int(n_slots))):

        def _run(s: int = slot) -> None:
            sse_partition_worker_loop(
                get_rules=get_rules,
                slot_idx=s,
                n_slots=max(1, int(n_slots)),
                ut=ut,
                base_url=base_url,
                fields=fields,
                stop=stop,
                on_metrics=on_metrics,
                reconnect_sec=reconnect_sec,
                burst_sec=burst_sec,
                read_timeout_sec=read_timeout_sec,
            )

        t = threading.Thread(target=_run, name=f"EastmoneySSE-{slot}", daemon=True)
        t.start()
        threads.append(t)
    return threads
