"""Tushare Pro：指数 index_daily + rt_idx_k；个股 pro_bar(qfq)/daily + rt_k；申万 sw_daily（回退 sw_index_daily）+ rt_sw_k。"""

from __future__ import annotations

# PyPI「tushare」包内 DataApi 仍默认 http://api.waditu.com/dataapi；部分网络无法解析 api.waditu.com。
# 优先走正式 Pro 入口，兼容 dataapi/{api_name} 与旧 waditu 作为 fallback。
_DEFAULT_TUSHARE_DATAAPI_BASE = "https://api.tushare.pro"
_TUSHARE_DATAAPI_COMPAT_BASE = "https://api.tushare.pro/dataapi"
_LEGACY_WADITU_DATAAPI_BASE = "http://api.waditu.com/dataapi"

import errno
import logging
import os
import json
import socket
import sqlite3
import threading
import time
from collections import deque
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

_CFG: dict[str, Any] = {
    "enabled": False,
    "token": "",
    "token_env": "TUSHARE_TOKEN",
    "sh_index_free_fallback": False,
    "stock_rt_k_enabled": True,
    "stock_rt_k_fallback": False,
    "sw_enabled": True,
    "sw_daily_bulk_enabled": False,
    "sw_daily_bulk_max_bars": 120,
    "financial_cache_db_path": "data/financial_factors.db",
    "stock_basic_cache_path": "data/stock_basic_cache.json",
    "stock_to_sw_path": "data/stock_to_sw.json",
    # Tushare 文档：daily 类接口 500 次/分钟；pro_bar 等计入同类额度
    "daily_max_per_minute": 500,
    # pro_bar(adj=qfq) 内部会调 adj_factor，独立限额 200 次/分钟（与 daily 额度无关）
    "adj_factor_max_per_minute": 180,
}
_PRO: Any = None

_DEFAULT_DAILY_MAX_PER_MIN = 500
_DEFAULT_ADJ_FACTOR_MAX_PER_MIN = 180
_DEFAULT_SW_DAILY_MAX_PER_MIN = 50
_DEFAULT_SW_DAILY_BULK_MAX_BARS = 120
_daily_rate_lock = threading.Lock()
_daily_rate_mono: deque[float] = deque()
_adj_factor_rate_lock = threading.Lock()
_adj_factor_rate_mono: deque[float] = deque()
_sw_daily_rate_lock = threading.Lock()
_sw_daily_rate_mono: deque[float] = deque()
# configure_tushare_from_sources 会被 load_df 等高频路径反复调用；仅在配置实质变化时重置 pro / 限流窗口
_LAST_TUSHARE_CONFIGURE_FG: tuple[Any, ...] | None = None

# DataApi.query 补丁：多基址 + 连接/DNS 抖动时重试；成功后将该基址前置。
_DATAAPI_BASE_CHAIN: list[str] = []
_dataapi_bases_lock = threading.Lock()
_TUSHARE_QUERY_PATCH_INSTALLED = False
_SW_DAILY_BULK_CACHE: dict[tuple[str, str], pd.DataFrame | None] = {}
_SW_DAILY_BULK_RATE_LIMITED = False


def _reset_daily_rate_window() -> None:
    with _daily_rate_lock:
        _daily_rate_mono.clear()


def _reset_adj_factor_rate_window() -> None:
    with _adj_factor_rate_lock:
        _adj_factor_rate_mono.clear()


def _reset_sw_daily_rate_window() -> None:
    with _sw_daily_rate_lock:
        _sw_daily_rate_mono.clear()


def _reset_sw_daily_bulk_cache() -> None:
    global _SW_DAILY_BULK_RATE_LIMITED
    _SW_DAILY_BULK_CACHE.clear()
    _SW_DAILY_BULK_RATE_LIMITED = False


def _is_tushare_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc)
    return "频率超限" in msg or "每分钟最多访问" in msg or "每小时最多访问" in msg


def _acquire_sw_daily_slot() -> None:
    """申万行业日线 sw_daily 账户频率通常很低，单独限速避免连续请求被拒。"""
    if not (_CFG.get("enabled") and _resolved_token()):
        return
    try:
        lim = int(_CFG.get("sw_daily_max_per_minute", _DEFAULT_SW_DAILY_MAX_PER_MIN) or 0)
    except (TypeError, ValueError):
        lim = _DEFAULT_SW_DAILY_MAX_PER_MIN
    if lim <= 0:
        return
    lim = max(1, min(500, lim))
    window = 60.0
    while True:
        with _sw_daily_rate_lock:
            now = time.monotonic()
            while _sw_daily_rate_mono and now - _sw_daily_rate_mono[0] >= window:
                _sw_daily_rate_mono.popleft()
            if len(_sw_daily_rate_mono) < lim:
                _sw_daily_rate_mono.append(now)
                return
            wait_s = window - (now - _sw_daily_rate_mono[0]) + 0.02
        time.sleep(max(wait_s, 0.05))


def _acquire_tushare_adj_factor_slot() -> None:
    """
    pro_bar(adj=qfq) 会触发 adj_factor 接口；Tushare 对该接口单独限 200 次/分钟。
    全市场选股多线程时若只限 daily 500/分钟仍会撞 adj_factor 上限。
    adj_factor_max_per_minute=0 表示不限制。
    """
    if not (_CFG.get("enabled") and _resolved_token()):
        return
    try:
        lim = int(
            _CFG.get("adj_factor_max_per_minute", _DEFAULT_ADJ_FACTOR_MAX_PER_MIN) or 0
        )
    except (TypeError, ValueError):
        lim = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
    if lim <= 0:
        return
    lim = max(30, min(200, lim))
    window = 60.0
    while True:
        with _adj_factor_rate_lock:
            now = time.monotonic()
            while _adj_factor_rate_mono and now - _adj_factor_rate_mono[0] >= window:
                _adj_factor_rate_mono.popleft()
            if len(_adj_factor_rate_mono) < lim:
                _adj_factor_rate_mono.append(now)
                return
            wait_s = window - (now - _adj_factor_rate_mono[0]) + 0.02
        time.sleep(max(wait_s, 0.05))


def _acquire_tushare_daily_slot() -> None:
    """
    在发起 pro_bar / pro.daily(trade_date|ts_code) 等「日线行情」类请求前调用，
    用滑动 60s 窗口限制全局频次，避免多线程选股时突破 500/分钟。
    daily_max_per_minute=0 表示不限制。
    """
    if not (_CFG.get("enabled") and _resolved_token()):
        return
    try:
        lim = int(_CFG.get("daily_max_per_minute", _DEFAULT_DAILY_MAX_PER_MIN) or 0)
    except (TypeError, ValueError):
        lim = _DEFAULT_DAILY_MAX_PER_MIN
    if lim <= 0:
        return
    lim = max(30, min(500, lim))
    window = 60.0
    while True:
        with _daily_rate_lock:
            now = time.monotonic()
            while _daily_rate_mono and now - _daily_rate_mono[0] >= window:
                _daily_rate_mono.popleft()
            if len(_daily_rate_mono) < lim:
                _daily_rate_mono.append(now)
                return
            wait_s = window - (now - _daily_rate_mono[0]) + 0.02
        time.sleep(max(wait_s, 0.05))


def _resolve_tushare_dataapi_base(sources: dict[str, Any] | None) -> str:
    """环境变量 TUSHARE_PRO_DATAAPI_BASE 优先；其次 sources.tushare.pro_dataapi_base；默认走 api.tushare.pro。"""
    env = str(os.environ.get("TUSHARE_PRO_DATAAPI_BASE") or "").strip().rstrip("/")
    if env:
        return env
    if isinstance(sources, dict):
        t = sources.get("tushare")
        if isinstance(t, dict):
            b = str(t.get("pro_dataapi_base") or "").strip().rstrip("/")
            if b:
                return b
    return _DEFAULT_TUSHARE_DATAAPI_BASE


def _apply_tushare_retry_settings(t: dict[str, Any] | None) -> None:
    if not isinstance(t, dict):
        _CFG["dataapi_connect_retries"] = 5
        _CFG["dataapi_retry_base_delay_sec"] = 0.45
        return
    try:
        cr = t.get("dataapi_connect_retries")
        _CFG["dataapi_connect_retries"] = (
            5 if cr is None else max(1, min(12, int(cr)))
        )
    except (TypeError, ValueError):
        _CFG["dataapi_connect_retries"] = 5
    try:
        d = t.get("dataapi_retry_base_delay_sec")
        _CFG["dataapi_retry_base_delay_sec"] = (
            0.45 if d is None else max(0.05, min(5.0, float(d)))
        )
    except (TypeError, ValueError):
        _CFG["dataapi_retry_base_delay_sec"] = 0.45


def _dataapi_connect_retries_n() -> int:
    try:
        return max(1, min(12, int(_CFG.get("dataapi_connect_retries", 5))))
    except (TypeError, ValueError):
        return 5


def _dataapi_retry_base_delay() -> float:
    try:
        return max(0.05, min(5.0, float(_CFG.get("dataapi_retry_base_delay_sec", 0.45))))
    except (TypeError, ValueError):
        return 0.45


def _tushare_transient_api_msg(msg: str) -> bool:
    """服务端返回 code!=0 时，部分文案为瞬时故障（可退避重试）。"""
    s = str(msg or "")
    needles = (
        "接收数据异常",
        "稍后再试",
        "请稍后",
        "网络异常",
        "连接超时",
        "连接失败",
        "超时",
        "频繁",
        "系统繁忙",
        "服务繁忙",
        "请降低访问频率",
        "Connection reset",
        "reset by peer",
        "Broken pipe",
        "broken pipe",
    )
    return any(x in s for x in needles)


def _is_transient_tushare_network_exc(exc: BaseException) -> bool:
    """Broken pipe / ECONNRESET / urllib3 协议错误等，与 ConnectionError 并列重试。"""
    import requests
    from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

    if isinstance(
        exc,
        (
            ConnectionError,
            Timeout,
            ChunkedEncodingError,
            BrokenPipeError,
            ConnectionResetError,
        ),
    ):
        return True
    if isinstance(exc, OSError):
        e = getattr(exc, "errno", None)
        transient_errnos = {
            errno.ECONNRESET,
            errno.EPIPE,
            errno.ETIMEDOUT,
            errno.ECONNABORTED,
        }
        if hasattr(errno, "EHOSTUNREACH"):
            transient_errnos.add(int(errno.EHOSTUNREACH))
        if hasattr(errno, "ENETUNREACH"):
            transient_errnos.add(int(errno.ENETUNREACH))
        if e in transient_errnos:
            return True
    try:
        from urllib3.exceptions import IncompleteRead, ProtocolError

        if isinstance(exc, (ProtocolError, IncompleteRead)):
            return True
    except ImportError:
        pass
    # requests 对底层 OSError 的包装
    if isinstance(exc, requests.exceptions.RequestException):
        if isinstance(exc, (ConnectionError, Timeout, ChunkedEncodingError)):
            return True
        cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
        if cause is not None and cause is not exc:
            return _is_transient_tushare_network_exc(cause)
    return False


def _resolve_dataapi_fallback_urls(sources: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    env = str(os.environ.get("TUSHARE_PRO_DATAAPI_FALLBACKS") or "").strip()
    if env:
        for part in env.split(","):
            u = part.strip().rstrip("/")
            if u:
                out.append(u)
    if isinstance(sources, dict):
        t = sources.get("tushare")
        if isinstance(t, dict):
            fb = t.get("pro_dataapi_fallbacks")
            if isinstance(fb, list):
                for x in fb:
                    u = str(x).strip().rstrip("/")
                    if u:
                        out.append(u)
    return out


def _build_dataapi_base_chain(primary: str, sources: dict[str, Any] | None) -> list[str]:
    """顺序：主基址 → 环境/配置额外 fallback → 官方双域名（去重）。"""
    seen: set[str] = set()
    chain: list[str] = []

    def add(u: str) -> None:
        s = str(u).strip().rstrip("/")
        if not s or s in seen:
            return
        seen.add(s)
        chain.append(s)

    add(primary)
    for u in _resolve_dataapi_fallback_urls(sources):
        add(u)
    add(_DEFAULT_TUSHARE_DATAAPI_BASE)
    add(_TUSHARE_DATAAPI_COMPAT_BASE)
    add(_LEGACY_WADITU_DATAAPI_BASE)
    return chain


def _tushare_post_url(base: str, api_name: str) -> str:
    b = str(base).strip().rstrip("/")
    if b.endswith("/dataapi"):
        return f"{b}/{api_name}"
    return b


def _dataapi_bases_snapshot() -> list[str]:
    with _dataapi_bases_lock:
        if _DATAAPI_BASE_CHAIN:
            return list(_DATAAPI_BASE_CHAIN)
    return _build_dataapi_base_chain(_DEFAULT_TUSHARE_DATAAPI_BASE, None)


def _note_dataapi_base_ok(base: str) -> None:
    """将成功连上的基址移到链首，并同步 DataApi 类属性（兼容依赖 __http_url 的代码）。"""
    b = str(base).strip().rstrip("/")
    if not b:
        return
    global _DATAAPI_BASE_CHAIN
    with _dataapi_bases_lock:
        lst = list(_DATAAPI_BASE_CHAIN) if _DATAAPI_BASE_CHAIN else _build_dataapi_base_chain(
            _DEFAULT_TUSHARE_DATAAPI_BASE, None
        )
        if b in lst:
            lst.remove(b)
        lst.insert(0, b)
        _DATAAPI_BASE_CHAIN = lst
    _apply_tushare_dataapi_base(b)


def _tushare_query_patched(self: Any, api_name: str, fields: str = "", **kwargs: Any) -> Any:
    """替换 tushare DataApi.query：多基址轮换 + 连接重置/断管/服务端繁忙等退避重试。"""
    import requests

    token = getattr(self, "_DataApi__token")
    timeout = getattr(self, "_DataApi__timeout")
    retries = _dataapi_connect_retries_n()
    delay0 = _dataapi_retry_base_delay()
    bases = _dataapi_bases_snapshot()
    last_exc: BaseException | None = None

    def _backoff(attempt: int) -> None:
        time.sleep(delay0 * (2**attempt))

    for base in bases:
        url_base = str(base).strip().rstrip("/")
        for attempt in range(retries):
            try:
                params = dict(kwargs)
                req_params = {
                    "api_name": api_name,
                    "token": token,
                    "params": params,
                    "fields": fields,
                }
                post_url = _tushare_post_url(url_base, api_name)
                res = requests.post(post_url, json=req_params, timeout=timeout)
                try:
                    _code = int(getattr(res, "status_code", 200))
                    _http_ok = 200 <= _code < 300
                except (TypeError, ValueError):
                    _http_ok = bool(res)
                if not _http_ok:
                    last_exc = RuntimeError(
                        f"HTTP {getattr(res, 'status_code', '?')}"
                    )
                    if attempt + 1 < retries:
                        _backoff(attempt)
                    continue
                try:
                    result = json.loads(res.text)
                except json.JSONDecodeError as je:
                    last_exc = je
                    if attempt + 1 < retries:
                        _backoff(attempt)
                    continue
                if result.get("code") != 0:
                    msg = str(result.get("msg") or "")
                    if _tushare_transient_api_msg(msg):
                        last_exc = Exception(msg)
                        if attempt + 1 < retries:
                            _backoff(attempt)
                        continue
                    raise Exception(msg)
                data = result.get("data") or {}
                columns = data.get("fields") or []
                items = data.get("items") or []
                _note_dataapi_base_ok(url_base)
                return pd.DataFrame(items, columns=columns)
            except socket.gaierror as exc:
                last_exc = exc
                if attempt + 1 < retries:
                    _backoff(attempt)
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                last_exc = exc
                if attempt + 1 < retries:
                    _backoff(attempt)
            except Exception as exc:
                if _is_transient_tushare_network_exc(exc):
                    last_exc = exc
                    if attempt + 1 < retries:
                        _backoff(attempt)
                    continue
                raise

    if last_exc is not None:
        raise last_exc
    return pd.DataFrame()


def _install_tushare_query_patch() -> None:
    global _TUSHARE_QUERY_PATCH_INSTALLED
    if _TUSHARE_QUERY_PATCH_INSTALLED:
        return
    try:
        from tushare.pro import client as _ts_client
    except ImportError:
        return
    _ts_client.DataApi.query = _tushare_query_patched  # type: ignore[method-assign]
    _TUSHARE_QUERY_PATCH_INSTALLED = True


def _apply_tushare_dataapi_base(base: str) -> None:
    """改写 tushare.pro.client.DataApi 类属性，使 pro_bar / adj_factor 等请求落到可解析的主机。"""
    b = str(base or "").strip().rstrip("/")
    if not b:
        b = _DEFAULT_TUSHARE_DATAAPI_BASE
    try:
        from tushare.pro import client as _ts_client
    except ImportError:
        return
    setattr(_ts_client.DataApi, "_DataApi__http_url", b)


def configure_tushare_from_sources(sources: dict[str, Any] | None) -> None:
    """在 configure_ssl_from_sources 之后由 utils 调用；更新 enabled / token / pro 句柄。

    注意：选股 load_df 每只股票都会调用本函数；**不得**每次清空日线限流窗口，否则全局限流失效。
    """
    global _PRO, _LAST_TUSHARE_CONFIGURE_FG, _DATAAPI_BASE_CHAIN
    prev_fg = _LAST_TUSHARE_CONFIGURE_FG

    t_retry: dict[str, Any] | None = None
    if isinstance(sources, dict):
        tt = sources.get("tushare")
        if isinstance(tt, dict):
            t_retry = tt
    _apply_tushare_retry_settings(t_retry)

    if not isinstance(sources, dict):
        _CFG["enabled"] = False
        _CFG["token"] = ""
        _CFG["sh_index_free_fallback"] = False
        _CFG["stock_rt_k_enabled"] = True
        _CFG["stock_rt_k_fallback"] = False
        _CFG["sw_enabled"] = True
        _CFG["sw_daily_bulk_enabled"] = False
        _CFG["sw_daily_bulk_max_bars"] = _DEFAULT_SW_DAILY_BULK_MAX_BARS
        _CFG["financial_cache_db_path"] = "data/financial_factors.db"
        _CFG["stock_basic_cache_path"] = "data/stock_basic_cache.json"
        _CFG["stock_to_sw_path"] = "data/stock_to_sw.json"
        _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
        _CFG["adj_factor_max_per_minute"] = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
        _CFG["sw_daily_max_per_minute"] = _DEFAULT_SW_DAILY_MAX_PER_MIN
    else:
        t = sources.get("tushare")
        if not isinstance(t, dict):
            _CFG["enabled"] = False
            _CFG["token"] = ""
            _CFG["sh_index_free_fallback"] = False
            _CFG["stock_rt_k_enabled"] = True
            _CFG["stock_rt_k_fallback"] = False
            _CFG["sw_enabled"] = True
            _CFG["sw_daily_bulk_enabled"] = False
            _CFG["sw_daily_bulk_max_bars"] = _DEFAULT_SW_DAILY_BULK_MAX_BARS
            _CFG["financial_cache_db_path"] = "data/financial_factors.db"
            _CFG["stock_basic_cache_path"] = "data/stock_basic_cache.json"
            _CFG["stock_to_sw_path"] = "data/stock_to_sw.json"
            _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
            _CFG["adj_factor_max_per_minute"] = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
            _CFG["sw_daily_max_per_minute"] = _DEFAULT_SW_DAILY_MAX_PER_MIN
        else:
            _CFG["enabled"] = bool(t.get("enabled", False))
            _CFG["token"] = str(t.get("token") or "").strip()
            _CFG["token_env"] = (
                str(t.get("token_env") or "TUSHARE_TOKEN").strip() or "TUSHARE_TOKEN"
            )
            _CFG["sh_index_free_fallback"] = bool(t.get("sh_index_free_fallback", False))
            _CFG["stock_rt_k_enabled"] = bool(t.get("stock_rt_k_enabled", True))
            _CFG["stock_rt_k_fallback"] = bool(t.get("stock_rt_k_fallback", False))
            _CFG["sw_enabled"] = bool(t.get("sw_enabled", True))
            _CFG["sw_daily_bulk_enabled"] = bool(t.get("sw_daily_bulk_enabled", False))
            _CFG["financial_cache_db_path"] = str(
                t.get("financial_cache_db_path") or "data/financial_factors.db"
            ).strip()
            try:
                bulk_bars = t.get("sw_daily_bulk_max_bars")
                if bulk_bars is None:
                    _CFG["sw_daily_bulk_max_bars"] = _DEFAULT_SW_DAILY_BULK_MAX_BARS
                else:
                    _CFG["sw_daily_bulk_max_bars"] = max(40, min(240, int(bulk_bars)))
            except (TypeError, ValueError):
                _CFG["sw_daily_bulk_max_bars"] = _DEFAULT_SW_DAILY_BULK_MAX_BARS
            _CFG["stock_basic_cache_path"] = str(
                t.get("stock_basic_cache_path") or "data/stock_basic_cache.json"
            ).strip()
            _CFG["stock_to_sw_path"] = str(
                t.get("stock_to_sw_path") or "data/stock_to_sw.json"
            ).strip()
            try:
                dlim = t.get("daily_max_per_minute")
                if dlim is None:
                    _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
                else:
                    v = int(dlim)
                    if v == 0:
                        _CFG["daily_max_per_minute"] = 0
                    else:
                        _CFG["daily_max_per_minute"] = max(30, min(500, v))
            except (TypeError, ValueError):
                _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
            try:
                alim = t.get("adj_factor_max_per_minute")
                if alim is None:
                    _CFG["adj_factor_max_per_minute"] = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
                else:
                    v = int(alim)
                    if v == 0:
                        _CFG["adj_factor_max_per_minute"] = 0
                    else:
                        _CFG["adj_factor_max_per_minute"] = max(30, min(200, v))
            except (TypeError, ValueError):
                _CFG["adj_factor_max_per_minute"] = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
            try:
                slim = t.get("sw_daily_max_per_minute")
                if slim is None:
                    _CFG["sw_daily_max_per_minute"] = _DEFAULT_SW_DAILY_MAX_PER_MIN
                else:
                    v = int(slim)
                    if v == 0:
                        _CFG["sw_daily_max_per_minute"] = 0
                    else:
                        _CFG["sw_daily_max_per_minute"] = max(1, min(60, v))
            except (TypeError, ValueError):
                _CFG["sw_daily_max_per_minute"] = _DEFAULT_SW_DAILY_MAX_PER_MIN

    tok_eff = _resolved_token()
    try:
        dm = int(_CFG.get("daily_max_per_minute") or 0)
    except (TypeError, ValueError):
        dm = _DEFAULT_DAILY_MAX_PER_MIN
    try:
        am = int(_CFG.get("adj_factor_max_per_minute") or 0)
    except (TypeError, ValueError):
        am = _DEFAULT_ADJ_FACTOR_MAX_PER_MIN
    try:
        sm = int(_CFG.get("sw_daily_max_per_minute") or 0)
    except (TypeError, ValueError):
        sm = _DEFAULT_SW_DAILY_MAX_PER_MIN
    try:
        sb = int(_CFG.get("sw_daily_bulk_max_bars") or _DEFAULT_SW_DAILY_BULK_MAX_BARS)
    except (TypeError, ValueError):
        sb = _DEFAULT_SW_DAILY_BULK_MAX_BARS
    dataapi_base = _resolve_tushare_dataapi_base(sources if isinstance(sources, dict) else None)
    with _dataapi_bases_lock:
        _DATAAPI_BASE_CHAIN = _build_dataapi_base_chain(
            dataapi_base, sources if isinstance(sources, dict) else None
        )
        chain_fg = tuple(_DATAAPI_BASE_CHAIN)
    _apply_tushare_dataapi_base(_DATAAPI_BASE_CHAIN[0] if _DATAAPI_BASE_CHAIN else dataapi_base)
    fg: tuple[Any, ...] = (
        bool(_CFG.get("enabled")),
        tok_eff,
        dm,
        am,
        sm,
        sb,
        bool(_CFG.get("sw_daily_bulk_enabled", False)),
        chain_fg,
    )

    if fg != prev_fg:
        _PRO = None
        _reset_daily_rate_window()
        _reset_adj_factor_rate_window()
        _reset_sw_daily_rate_window()
        _reset_sw_daily_bulk_cache()
        _LAST_TUSHARE_CONFIGURE_FG = fg


def _resolved_token() -> str:
    if not _CFG.get("enabled"):
        return ""
    tok = str(_CFG.get("token") or "").strip()
    if tok:
        return tok
    env_name = str(_CFG.get("token_env") or "TUSHARE_TOKEN")
    return str(os.environ.get(env_name) or "").strip()


def tushare_sh_index_primary() -> bool:
    """已配置 token 且启用时，上证主数据源为 Tushare（index_daily + rt_idx_k）。"""
    return bool(_CFG.get("enabled") and _resolved_token())


def sh_index_free_fallback_enabled() -> bool:
    return bool(_CFG.get("sh_index_free_fallback"))


def stock_rt_k_enabled() -> bool:
    """Tushare 已启用且配置允许时，对个股合并 rt_k。"""
    return bool(
        _CFG.get("enabled")
        and _resolved_token()
        and bool(_CFG.get("stock_rt_k_enabled", True))
    )


def stock_rt_k_fallback_enabled() -> bool:
    return bool(_CFG.get("stock_rt_k_fallback"))


def stock_rt_k_skip_ram_cache_for_secid(secid: str) -> bool:
    """
    个股启用 rt_k 时跳过日 K 内存缓存：缓存的是无 rt 的基准快照，避免返回缺少 OHLCV 序列时无法动态合并。
    """
    if not stock_rt_k_enabled():
        return False
    s = str(secid).strip()
    if s.startswith("90.") or s.startswith("92."):
        return False
    return secid_to_ts_code(s) is not None


def _get_pro() -> Any:
    global _PRO
    tok = _resolved_token()
    if not tok:
        return None
    if _PRO is not None:
        return _PRO
    try:
        import tushare as ts  # type: ignore[import-not-found]
    except ImportError:
        return None
    _PRO = ts.pro_api(tok)
    return _PRO


def _norm_code6(code: str) -> str | None:
    s = str(code or "").strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    c = s.zfill(6)
    if len(c) == 6 and c.isdigit():
        return c
    return None


def _stock_ts_code(code: str) -> str | None:
    s = str(code or "").strip().upper()
    if s.endswith((".SH", ".SZ")) and len(s.split(".", 1)[0]) == 6:
        return s
    c = _norm_code6(s)
    if not c:
        return None
    return f"{c}.SH" if c.startswith(("6", "9")) else f"{c}.SZ"


def resolved_financial_cache_db_path(root: Path | None = None) -> Path:
    r = root or Path(__file__).resolve().parent
    p = Path(str(_CFG.get("financial_cache_db_path") or "data/financial_factors.db"))
    return p if p.is_absolute() else (r / p)


def init_stock_financial_cache(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_financial_cache (
            code TEXT NOT NULL,
            factor_type TEXT NOT NULL,
            date TEXT NOT NULL,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (code, factor_type, date)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_stock_financial_cache_latest
        ON stock_financial_cache(code, factor_type, date)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_moneyflow_cache (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (code, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS industry_moneyflow_cache (
            industry_code TEXT NOT NULL,
            date TEXT NOT NULL,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (industry_code, date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hot_stock_cache (
            trade_date TEXT NOT NULL PRIMARY KEY,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS broker_recommend_cache (
            month TEXT NOT NULL PRIMARY KEY,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS concept_member_cache (
            concept_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (concept_code, trade_date)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hot_concept_stocks_cache (
            trade_date TEXT NOT NULL,
            code TEXT NOT NULL,
            json_data TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, code)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hot_concept_stocks_trade_date
        ON hot_concept_stocks_cache(trade_date)
        """
    )
    conn.commit()


def _open_stock_financial_cache() -> sqlite3.Connection:
    dbp = resolved_financial_cache_db_path()
    dbp.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    init_stock_financial_cache(conn)
    return conn


def _read_stock_factor_cache(
    code: str,
    factor_type: str,
    *,
    cache_date: str | None = None,
) -> dict[str, Any] | None:
    c6 = _norm_code6(code)
    if not c6:
        return None
    try:
        conn = _open_stock_financial_cache()
        try:
            if cache_date:
                row = conn.execute(
                    """
                    SELECT json_data FROM stock_financial_cache
                    WHERE code = ? AND factor_type = ? AND date = ?
                    """,
                    (c6, factor_type, str(cache_date)[:10]),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT json_data FROM stock_financial_cache
                    WHERE code = ? AND factor_type = ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (c6, factor_type),
                ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        data = json.loads(str(row["json_data"] or "{}"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_stock_factor_cache(
    code: str,
    factor_type: str,
    data: dict[str, Any],
    *,
    cache_date: str | None = None,
) -> None:
    c6 = _norm_code6(code)
    if not c6:
        return
    d = (cache_date or date.today().isoformat())[:10]
    try:
        conn = _open_stock_financial_cache()
        try:
            conn.execute(
                """
                INSERT INTO stock_financial_cache(code, factor_type, date, json_data, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(code, factor_type, date) DO UPDATE SET
                  json_data=excluded.json_data,
                  updated_at=excluded.updated_at
                """,
                (
                    c6,
                    factor_type,
                    d,
                    json.dumps(data, ensure_ascii=False, sort_keys=True),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        return


def _latest_float(row: Any, *names: str) -> float | None:
    for name in names:
        try:
            val = row.get(name)
        except AttributeError:
            val = None
        if val is None or str(val).strip() in ("", "nan", "None"):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def fetch_financial_factors(code: str, *, cache_only: bool = False) -> dict[str, Any]:
    """财务基本面因子；默认每日首次拉取并写入 SQLite，cache_only 仅读最近缓存。"""
    c6 = _norm_code6(code)
    tc = _stock_ts_code(code)
    if not c6 or not tc:
        return {}
    if cache_only:
        return _read_stock_factor_cache(c6, "financial") or {}
    today = date.today().isoformat()
    cached = _read_stock_factor_cache(c6, "financial", cache_date=today)
    if cached is not None:
        return cached
    pro = _get_pro()
    if pro is None:
        return _read_stock_factor_cache(c6, "financial") or {}

    out: dict[str, Any] = {
        "roe_ttm": None,
        "revenue_yoy": None,
        "profit_yoy": None,
        "debt_to_assets": None,
        "pe_ttm": None,
        "pb": None,
    }
    try:
        _acquire_tushare_daily_slot()
        df_db = pro.daily_basic(ts_code=tc, trade_date="", fields="ts_code,trade_date,pe_ttm,pb,turnover_rate,volume_ratio")
        if df_db is not None and not getattr(df_db, "empty", True):
            row = df_db.sort_values("trade_date").iloc[-1]
            out["pe_ttm"] = _latest_float(row, "pe_ttm")
            out["pb"] = _latest_float(row, "pb")
    except Exception:
        _LOG.debug("daily_basic 财务因子失败 %s", tc, exc_info=True)

    try:
        df_fi = pro.fina_indicator(ts_code=tc, start_date="", end_date="")
        if df_fi is not None and not getattr(df_fi, "empty", True):
            row = df_fi.sort_values("end_date").iloc[-1]
            roe = _latest_float(row, "roe_dt", "roe", "roe_waa")
            debt = _latest_float(row, "debt_to_assets")
            if roe is not None:
                out["roe_ttm"] = roe / 100.0 if abs(roe) > 1 else roe
            if debt is not None:
                out["debt_to_assets"] = debt / 100.0 if abs(debt) > 1 else debt
    except Exception:
        _LOG.debug("fina_indicator 财务因子失败 %s", tc, exc_info=True)

    try:
        df_income = pro.income(ts_code=tc, start_date="", end_date="")
        if df_income is not None and not getattr(df_income, "empty", True):
            inc = df_income.sort_values("end_date").drop_duplicates("end_date").tail(8)
            if len(inc) >= 5:
                cur = inc.iloc[-1]
                prev = inc.iloc[-5]
                rev_cur = _latest_float(cur, "revenue", "total_revenue")
                rev_prev = _latest_float(prev, "revenue", "total_revenue")
                prof_cur = _latest_float(cur, "n_income_attr_p", "n_income")
                prof_prev = _latest_float(prev, "n_income_attr_p", "n_income")
                if rev_cur is not None and rev_prev and rev_prev != 0:
                    out["revenue_yoy"] = (rev_cur - rev_prev) / abs(rev_prev)
                if prof_cur is not None and prof_prev and prof_prev != 0:
                    out["profit_yoy"] = (prof_cur - prof_prev) / abs(prof_prev)
    except Exception:
        _LOG.debug("income 财务因子失败 %s", tc, exc_info=True)

    _write_stock_factor_cache(c6, "financial", out, cache_date=today)
    return out


_MAX_MARGIN_BALANCE_YUAN = 5e10  # 个股融资余额（元）合理上限；误用 pro.margin 交易所汇总约 1e12


def _plausible_margin_balance(bal: Any) -> bool:
    try:
        f = float(bal)
    except (TypeError, ValueError):
        return False
    return f > 0 and f <= _MAX_MARGIN_BALANCE_YUAN


def fetch_margin_factor(code: str, *, cache_only: bool = False) -> dict[str, Any]:
    """个股融资融券因子（margin_detail）；近 5 日融资余额 rzye 变化率。单位：元。"""
    c6 = _norm_code6(code)
    tc = _stock_ts_code(code)
    if not c6 or not tc:
        return {}
    if cache_only:
        cached = _read_stock_factor_cache(c6, "margin") or {}
        if not _plausible_margin_balance(cached.get("margin_balance")):
            return {"margin_balance": None, "margin_change_pct_5d": None}
        return cached
    today = date.today().isoformat()
    cached = _read_stock_factor_cache(c6, "margin", cache_date=today)
    if cached is not None and _plausible_margin_balance(cached.get("margin_balance")):
        return cached
    pro = _get_pro()
    if pro is None:
        return _read_stock_factor_cache(c6, "margin") or {}
    out: dict[str, Any] = {"margin_balance": None, "margin_change_pct_5d": None}
    start_s = (date.today() - timedelta(days=20)).strftime("%Y%m%d")
    end_s = date.today().strftime("%Y%m%d")
    try:
        _acquire_tushare_daily_slot()
        df = None
        if hasattr(pro, "margin_detail"):
            df = pro.margin_detail(ts_code=tc, start_date=start_s, end_date=end_s)
        if df is not None and not getattr(df, "empty", True):
            if "ts_code" in df.columns:
                df = df[df["ts_code"].astype(str).str.upper() == tc.upper()]
            if not getattr(df, "empty", True):
                df = df.sort_values("trade_date")
                bal_col = "rzye" if "rzye" in df.columns else "margin_balance"
                vals = [
                    float(x)
                    for x in pd.to_numeric(df[bal_col], errors="coerce").dropna().tolist()
                ]
                if vals and _plausible_margin_balance(vals[-1]):
                    out["margin_balance"] = vals[-1]
                    if len(vals) >= 6 and vals[-6] != 0:
                        out["margin_change_pct_5d"] = (vals[-1] - vals[-6]) / abs(vals[-6])
                    elif len(vals) >= 2 and vals[-2] != 0:
                        out["margin_change_pct_5d"] = (vals[-1] - vals[-2]) / abs(vals[-2])
    except Exception:
        _LOG.debug("margin_detail 因子失败 %s", tc, exc_info=True)
    _write_stock_factor_cache(c6, "margin", out, cache_date=today)
    return out


def fetch_top_inst_factor(code: str, *, cache_only: bool = False) -> dict[str, Any]:
    """龙虎榜机构因子；近 30 天机构专用净买入与次数。"""
    c6 = _norm_code6(code)
    tc = _stock_ts_code(code)
    if not c6 or not tc:
        return {}
    if cache_only:
        return _read_stock_factor_cache(c6, "top_inst") or {}
    today = date.today().isoformat()
    cached = _read_stock_factor_cache(c6, "top_inst", cache_date=today)
    if cached is not None:
        return cached
    pro = _get_pro()
    if pro is None:
        return _read_stock_factor_cache(c6, "top_inst") or {}
    out: dict[str, Any] = {"inst_buy_net": None, "inst_buy_count": 0}
    start_s = (date.today() - timedelta(days=30)).strftime("%Y%m%d")
    end_s = date.today().strftime("%Y%m%d")
    try:
        _acquire_tushare_daily_slot()
        try:
            df = pro.top_inst(ts_code=tc, start_date=start_s, end_date=end_s)
        except Exception:
            df = None
        if df is None or getattr(df, "empty", True):
            df = pro.top_list(ts_code=tc, start_date=start_s, end_date=end_s)
        if df is not None and not getattr(df, "empty", True):
            if "exalter" in df.columns:
                df = df[df["exalter"].astype(str).str.contains("机构专用", na=False)]
            buy_src = df["buy_amount"] if "buy_amount" in df.columns else pd.Series([0.0] * len(df))
            sell_src = df["sell_amount"] if "sell_amount" in df.columns else pd.Series([0.0] * len(df))
            buy = pd.to_numeric(buy_src, errors="coerce").fillna(0.0)
            sell = pd.to_numeric(sell_src, errors="coerce").fillna(0.0)
            out["inst_buy_net"] = float((buy - sell).sum())
            out["inst_buy_count"] = int(len(df))
    except Exception:
        _LOG.debug("龙虎榜机构因子失败 %s", tc, exc_info=True)
    _write_stock_factor_cache(c6, "top_inst", out, cache_date=today)
    return out


def _today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def _date_range_back(days: int) -> tuple[str, str]:
    d = max(1, int(days))
    end_s = _today_yyyymmdd()
    start_s = (date.today() - timedelta(days=d * 3)).strftime("%Y%m%d")
    return start_s, end_s


def _wan_to_yuan(v: float) -> float:
    """Tushare 资金流金额字段多为万元。"""
    return float(v) * 10000.0


def _yuan_to_yi(v: float) -> float:
    return float(v) / 100000000.0


def _row_main_net_wan(row: Any) -> float | None:
    elg_b = _latest_float(row, "buy_elg_amount")
    elg_s = _latest_float(row, "sell_elg_amount")
    lg_b = _latest_float(row, "buy_lg_amount")
    lg_s = _latest_float(row, "sell_lg_amount")
    if any(x is not None for x in (elg_b, elg_s, lg_b, lg_s)):
        return (elg_b or 0.0) - (elg_s or 0.0) + (lg_b or 0.0) - (lg_s or 0.0)
    net = _latest_float(row, "net_mf_amount", "net_amount")
    if net is not None:
        return float(net)
    return None


def _sum_main_net_from_moneyflow_df(df: pd.DataFrame, days: int) -> tuple[float | None, float | None]:
    if df is None or getattr(df, "empty", True):
        return None, None
    work = df.copy()
    if "trade_date" in work.columns:
        work = work.sort_values("trade_date")
    tail = work.tail(max(1, int(days)))
    nets_wan: list[float] = []
    for _, row in tail.iterrows():
        v = _row_main_net_wan(row)
        if v is not None:
            nets_wan.append(float(v))
    if not nets_wan:
        return None, None
    total_wan = sum(nets_wan)
    last_wan = nets_wan[-1]
    return _wan_to_yuan(total_wan), _wan_to_yuan(last_wan)


def _read_json_table_row(
    table: str,
    *,
    key_col: str,
    key_val: str,
    cache_date: str | None = None,
) -> dict[str, Any] | None:
    try:
        conn = _open_stock_financial_cache()
        try:
            if table == "hot_stock_cache":
                row = conn.execute(
                    "SELECT json_data FROM hot_stock_cache WHERE trade_date = ?",
                    (str(key_val)[:10],),
                ).fetchone()
            elif table == "broker_recommend_cache":
                row = conn.execute(
                    "SELECT json_data FROM broker_recommend_cache WHERE month = ?",
                    (str(key_val)[:6],),
                ).fetchone()
            elif table == "concept_member_cache":
                d = (cache_date or date.today().isoformat())[:10]
                row = conn.execute(
                    """
                    SELECT json_data FROM concept_member_cache
                    WHERE concept_code = ? AND trade_date = ?
                    """,
                    (str(key_val), d),
                ).fetchone()
            elif cache_date:
                row = conn.execute(
                    f"SELECT json_data FROM {table} WHERE {key_col} = ? AND date = ?",
                    (key_val, str(cache_date)[:10]),
                ).fetchone()
            else:
                row = conn.execute(
                    f"""
                    SELECT json_data FROM {table}
                    WHERE {key_col} = ?
                    ORDER BY date DESC LIMIT 1
                    """,
                    (key_val,),
                ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        data = json.loads(str(row["json_data"] or "{}"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write_json_table_row(
    table: str,
    *,
    key_col: str,
    key_val: str,
    data: dict[str, Any],
    cache_date: str | None = None,
) -> None:
    d = (cache_date or date.today().isoformat())[:10]
    now_s = datetime.now().isoformat(timespec="seconds")
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    try:
        conn = _open_stock_financial_cache()
        try:
            if table == "hot_stock_cache":
                conn.execute(
                    """
                    INSERT INTO hot_stock_cache(trade_date, json_data, updated_at)
                    VALUES(?,?,?)
                    ON CONFLICT(trade_date) DO UPDATE SET
                      json_data=excluded.json_data,
                      updated_at=excluded.updated_at
                    """,
                    (d, payload, now_s),
                )
            elif table == "broker_recommend_cache":
                month = str(key_val)[:6]
                conn.execute(
                    """
                    INSERT INTO broker_recommend_cache(month, json_data, updated_at)
                    VALUES(?,?,?)
                    ON CONFLICT(month) DO UPDATE SET
                      json_data=excluded.json_data,
                      updated_at=excluded.updated_at
                    """,
                    (month, payload, now_s),
                )
            elif table == "concept_member_cache":
                conn.execute(
                    """
                    INSERT INTO concept_member_cache(concept_code, trade_date, json_data, updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(concept_code, trade_date) DO UPDATE SET
                      json_data=excluded.json_data,
                      updated_at=excluded.updated_at
                    """,
                    (str(key_val), d, payload, now_s),
                )
            elif table == "stock_moneyflow_cache":
                conn.execute(
                    """
                    INSERT INTO stock_moneyflow_cache(code, date, json_data, updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(code, date) DO UPDATE SET
                      json_data=excluded.json_data,
                      updated_at=excluded.updated_at
                    """,
                    (str(key_val).zfill(6)[-6:], d, payload, now_s),
                )
            elif table == "industry_moneyflow_cache":
                conn.execute(
                    """
                    INSERT INTO industry_moneyflow_cache(industry_code, date, json_data, updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(industry_code, date) DO UPDATE SET
                      json_data=excluded.json_data,
                      updated_at=excluded.updated_at
                    """,
                    (str(key_val).upper(), d, payload, now_s),
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        return


def _pack_moneyflow_out(net_5d_yuan: float | None, net_1d_yuan: float | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "net_main_5d": net_5d_yuan,
        "net_main_1d": net_1d_yuan,
        "net_main_5d_yi": _yuan_to_yi(net_5d_yuan) if net_5d_yuan is not None else None,
        "net_main_1d_yi": _yuan_to_yi(net_1d_yuan) if net_1d_yuan is not None else None,
    }
    return out


def fetch_moneyflow_individual(code: str, *, days: int = 5, cache_only: bool = False) -> dict[str, Any]:
    """个股主力资金流（超大单+大单净额），返回近 N 日累计与近 1 日（元/亿元）。"""
    c6 = _norm_code6(code)
    tc = _stock_ts_code(code)
    if not c6 or not tc:
        return {}
    today = date.today().isoformat()
    if cache_only:
        return _read_json_table_row("stock_moneyflow_cache", key_col="code", key_val=c6) or {}
    cached = _read_json_table_row("stock_moneyflow_cache", key_col="code", key_val=c6, cache_date=today)
    if cached is not None:
        return cached
    pro = _get_pro()
    if pro is None:
        return _read_json_table_row("stock_moneyflow_cache", key_col="code", key_val=c6) or {}
    start_s, end_s = _date_range_back(days)
    out = _pack_moneyflow_out(None, None)
    try:
        _acquire_tushare_daily_slot()
        df = pro.moneyflow(ts_code=tc, start_date=start_s, end_date=end_s)
        n5, n1 = _sum_main_net_from_moneyflow_df(df, days)
        out = _pack_moneyflow_out(n5, n1)
    except Exception:
        _LOG.debug("moneyflow 个股失败 %s", tc, exc_info=True)
    _write_json_table_row("stock_moneyflow_cache", key_col="code", key_val=c6, data=out, cache_date=today)
    return out


def _normalize_sw_l1_code(industry_code: str) -> str:
    ic = str(industry_code or "").strip().upper()
    if not ic:
        return ""
    if ic.endswith(".SI") and ic[:-3].isdigit():
        return ic
    if ic.isdigit() and len(ic) == 6:
        return f"{ic}.SI"
    return ""


def _norm_a_share_code6(raw: Any) -> str | None:
    """仅沪深 A 股 6 位代码（过滤港股/指数/概念码）。"""
    s = str(raw or "").strip().upper()
    if not s:
        return None
    if not (s.endswith(".SH") or s.endswith(".SZ")):
        return None
    sym = s.split(".", 1)[0].strip().zfill(6)
    if len(sym) != 6 or not sym.isdigit():
        return None
    if sym[0] not in ("0", "3", "6"):
        return None
    return sym


def _norm_hot_code(raw: Any) -> str | None:
    return _norm_a_share_code6(raw)


def _recent_trade_dates_yyyymmdd(max_days: int = 10) -> list[str]:
    out: list[str] = []
    d = date.today()
    while len(out) < max(1, int(max_days)):
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


def _lookup_sw_l1_for_ts_code(pro: Any, tc: str) -> str | None:
    """单票查询申万一级代码（补全 stock_to_sw 缺项）。"""
    tc = str(tc or "").strip().upper()
    if not tc:
        return None
    try:
        df = pro.index_member_all(ts_code=tc, is_new="Y")
        if df is not None and not getattr(df, "empty", True):
            for col in ("l1_code", "L1_code", "index_code"):
                if col not in df.columns:
                    continue
                v = str(df.iloc[0].get(col) or "").strip().upper()
                if v.endswith(".SI"):
                    return v
    except Exception:
        _LOG.debug("index_member_all 查询失败 %s", tc, exc_info=True)
    return None


def _persist_sw_map_entries(path: Path, entries: dict[str, str]) -> None:
    if not entries:
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    inner = raw.get("by_code") if isinstance(raw.get("by_code"), dict) else raw
    if not isinstance(inner, dict):
        inner = {}
    for k, v in entries.items():
        c6 = _norm_code6(k)
        sw = _normalize_sw_l1_code(v)
        if c6 and sw:
            inner[c6] = sw
    raw["by_code"] = inner
    raw["_meta"] = {
        "updated": datetime.now().isoformat(timespec="seconds"),
        "count": len(inner),
        "source": "tushare_sw_patch",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_sw_map_for_codes(
    codes: list[str] | set[str] | tuple[str, ...],
    sw_map: dict[str, str] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    """合并本地 stock_to_sw.json，并为缺失代码尝试 Tushare 补全。"""
    path = resolved_stock_to_sw_path(root)
    merged = load_stock_to_sw_map_for_factors(root)
    if isinstance(sw_map, dict):
        for k, v in sw_map.items():
            c6 = _norm_code6(k)
            sw = _normalize_sw_l1_code(v)
            if c6 and sw:
                merged[c6] = sw
    missing = sorted({_norm_code6(c) for c in codes if _norm_code6(c) and _norm_code6(c) not in merged})
    if not missing:
        return merged
    pro = _get_pro()
    if pro is None:
        return merged
    patch: dict[str, str] = {}
    for c6 in missing:
        sw = _lookup_sw_l1_for_ts_code(pro, _stock_ts_code(c6) or "")
        if sw:
            patch[c6] = sw
            merged[c6] = sw
    if patch:
        _persist_sw_map_entries(path, patch)
    return merged


def _aggregate_industry_moneyflow_from_stocks(
    codes: list[str] | set[str] | tuple[str, ...],
    sw_map: dict[str, str],
) -> int:
    """
    按申万一级汇总 watchlist/候选池内个股主力净流入（moneyflow_ths 无行业序列时的可靠方案）。
    """
    sum5: dict[str, float] = {}
    sum1: dict[str, float] = {}
    cnt: dict[str, int] = {}
    today = date.today().isoformat()
    for raw in codes:
        c6 = _norm_code6(raw)
        if not c6:
            continue
        sw = _normalize_sw_l1_code(sw_map.get(c6, ""))
        if not sw:
            continue
        mf = fetch_moneyflow_individual(c6, cache_only=True)
        if not mf or (mf.get("net_main_5d") is None and mf.get("net_main_1d") is None):
            mf = fetch_moneyflow_individual(c6, days=5, cache_only=False)
        n5 = mf.get("net_main_5d")
        n1 = mf.get("net_main_1d")
        if n5 is None and n1 is None:
            continue
        sum5[sw] = sum5.get(sw, 0.0) + float(n5 or 0.0)
        sum1[sw] = sum1.get(sw, 0.0) + float(n1 or 0.0)
        cnt[sw] = cnt.get(sw, 0) + 1
    written = 0
    for sw in sorted(sum5.keys()):
        data = _pack_moneyflow_out(sum5.get(sw), sum1.get(sw))
        data["source"] = "aggregated_sw"
        data["stock_count"] = cnt.get(sw, 0)
        _write_json_table_row(
            "industry_moneyflow_cache",
            key_col="industry_code",
            key_val=sw,
            data=data,
            cache_date=today,
        )
        written += 1
    return written


def fetch_moneyflow_industry(industry_code: str, *, days: int = 5, cache_only: bool = False) -> dict[str, Any]:
    """申万一级行业主力净流入（由候选池个股汇总写入缓存；读取 cache_only）。"""
    ic = _normalize_sw_l1_code(industry_code)
    if not ic:
        return {}
    today = date.today().isoformat()
    if cache_only:
        return _read_json_table_row("industry_moneyflow_cache", key_col="industry_code", key_val=ic) or {}
    cached = _read_json_table_row(
        "industry_moneyflow_cache", key_col="industry_code", key_val=ic, cache_date=today
    )
    if cached is not None and cached.get("net_main_5d") is not None:
        return cached
    stale = _read_json_table_row("industry_moneyflow_cache", key_col="industry_code", key_val=ic) or {}
    if stale:
        return stale
    return {}


def _hot_stock_rank_map_from_blob(blob: dict[str, Any]) -> dict[str, int]:
    ranks = blob.get("ranks") if isinstance(blob.get("ranks"), dict) else {}
    out: dict[str, int] = {}
    for k, v in ranks.items():
        c6 = _norm_code6(k)
        if not c6:
            continue
        try:
            out[c6] = int(v)
        except (TypeError, ValueError):
            continue
    if out:
        return out
    codes = blob.get("codes") if isinstance(blob.get("codes"), list) else []
    return {
        str(c): i + 1
        for i, c in enumerate(codes)
        if isinstance(c, str) and len(str(c).strip()) == 6
    }


def _read_hot_stock_cache_blob(trade_date_iso: str | None = None) -> dict[str, Any]:
    iso = str(trade_date_iso or date.today().isoformat())[:10]
    blob = _read_json_table_row("hot_stock_cache", key_col="trade_date", key_val=iso) or {}
    if blob.get("codes"):
        return blob
    try:
        conn = _open_stock_financial_cache()
        try:
            rows = conn.execute(
                """
                SELECT json_data FROM hot_stock_cache
                ORDER BY trade_date DESC LIMIT 12
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    for row in rows or []:
        try:
            data = json.loads(str(row["json_data"] or "{}"))
        except json.JSONDecodeError:
            continue
        if data.get("codes"):
            return data
    return {}


def _read_hot_stock_cache(trade_date_iso: str | None = None) -> list[str]:
    iso = str(trade_date_iso or date.today().isoformat())[:10]
    blob = _read_hot_stock_cache_blob(iso)
    codes = blob.get("codes") if isinstance(blob.get("codes"), list) else []
    return [str(c) for c in codes if isinstance(c, str) and len(c) == 6]


def get_hot_stock_rank(
    code: str,
    *,
    cache_only: bool = True,
    trade_date: str | None = None,
) -> int | None:
    c6 = _norm_code6(code)
    if not c6:
        return None
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    ranks = _hot_stock_rank_map_from_blob(_read_hot_stock_cache_blob(iso))
    r = ranks.get(c6)
    return int(r) if r is not None else None


def fetch_hot_stocks_ranked(
    trade_date: str | None = None,
    *,
    cache_only: bool = False,
    top_n: int = 10,
) -> list[tuple[str, int]]:
    """同花顺热股榜（代码, 排名），按排名升序。"""
    codes = fetch_hot_stocks(trade_date=trade_date, cache_only=cache_only, top_n=top_n)
    if not codes:
        return []
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    ranks = _hot_stock_rank_map_from_blob(_read_hot_stock_cache_blob(iso))
    out: list[tuple[str, int]] = []
    for i, c in enumerate(codes):
        c6 = _norm_code6(c)
        if not c6:
            continue
        out.append((c6, int(ranks.get(c6, i + 1))))
    out.sort(key=lambda x: x[1])
    return out[:top_n]


def _ths_hot_preferred_is_new(now: datetime | None = None) -> str:
    """
    同花顺 ths_hot：盘中/盘后 22:30 前用 is_new=N（约每小时更新）；
    22:30 后终榜用 is_new=Y。
    """
    ref = now or datetime.now()
    if ref.weekday() >= 5:
        return "Y"
    t = ref.time()
    if t >= dt_time(22, 30):
        return "Y"
    return "N"


def _ths_hot_is_new_modes(primary: str | None = None) -> list[str]:
    p = str(primary or _ths_hot_preferred_is_new()).strip().upper() or "N"
    alt = "Y" if p == "N" else "N"
    return [p, alt]


def _collect_hot_stock_codes_from_ths_df(
    df: pd.DataFrame | None,
    *,
    top_n: int,
) -> tuple[list[str], dict[str, int], str | None]:
    """解析 ths_hot 返回：仅沪深 A 股，按 rank/rank_time 去重取前 top_n。"""
    if df is None or getattr(df, "empty", True):
        return [], {}, None
    work = df.copy()
    for col in ("market", "data_type"):
        if col not in work.columns:
            continue
        ser = work[col].astype(str)
        mask = ser.str.contains("热股", na=False) | ser.str.contains("股票", na=False)
        if mask.any():
            work = work[mask]
        break
    if "rank" in work.columns:
        work = work.sort_values("rank")
    elif "rank_time" in work.columns:
        work = work.sort_values("rank_time", ascending=False)
    rank_col = "rank" if "rank" in work.columns else None
    codes: list[str] = []
    rank_map: dict[str, int] = {}
    latest_rt: str | None = None
    for _, row in work.iterrows():
        if latest_rt is None:
            rt = row.get("rank_time")
            if rt is not None and str(rt).strip():
                latest_rt = str(rt).strip()
        c = _norm_hot_code(row.get("ts_code") or row.get("code") or row.get("con_code"))
        if not c or c in rank_map:
            continue
        try:
            rk = int(row.get(rank_col)) if rank_col else len(codes) + 1
        except (TypeError, ValueError):
            rk = len(codes) + 1
        codes.append(c)
        rank_map[c] = rk
        if len(codes) >= top_n:
            break
    return codes, rank_map, latest_rt


def _fetch_ths_hot_codes(
    pro: Any,
    *,
    trade_date: str | None,
    top_n: int,
    is_new_modes: list[str] | None = None,
) -> tuple[list[str], dict[str, int], str, str | None, str | None]:
    """调用 ths_hot；返回 (codes, ranks, used_trade_date, rank_time, is_new_used)。"""
    modes = is_new_modes or _ths_hot_is_new_modes()
    td0 = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    dates_to_try = [td0] + [d for d in _recent_trade_dates_yyyymmdd(12) if d != td0]
    attempts: list[tuple[str | None, str]] = []
    for try_td in dates_to_try:
        for is_new in modes:
            attempts.append((try_td, is_new))
    attempts.append((None, modes[0]))
    attempts.append((None, modes[1] if len(modes) > 1 else modes[0]))

    for try_td, is_new in attempts:
        try:
            _acquire_tushare_daily_slot()
            kwargs: dict[str, Any] = {"market": "热股", "is_new": is_new}
            if try_td:
                kwargs["trade_date"] = try_td
            df = pro.ths_hot(**kwargs)
            codes, rank_map, rank_time = _collect_hot_stock_codes_from_ths_df(df, top_n=top_n)
            if codes:
                used_td = try_td or td0
                return codes, rank_map, used_td, rank_time, is_new
        except Exception:
            _LOG.debug(
                "ths_hot 失败 trade_date=%s is_new=%s",
                try_td,
                is_new,
                exc_info=True,
            )
    return [], {}, td0, None, None


def read_hot_stock_cache_meta(trade_date_iso: str | None = None) -> dict[str, Any]:
    """读取 hot_stock_cache 元数据（is_new、rank_time、更新时间等）。"""
    iso = str(trade_date_iso or date.today().isoformat())[:10]
    blob = _read_hot_stock_cache_blob(iso)
    if not blob:
        return {}
    return {
        "trade_date": blob.get("trade_date") or iso,
        "count": len(blob.get("codes") or []),
        "is_new": blob.get("is_new"),
        "rank_time": blob.get("rank_time"),
        "fetched_at": blob.get("fetched_at"),
        "codes_preview": (blob.get("codes") or [])[:10],
    }


def fetch_hot_stocks(
    trade_date: str | None = None,
    *,
    cache_only: bool = False,
    top_n: int = 50,
    force_refresh: bool = False,
) -> list[str]:
    """同花顺热股榜（仅沪深 A 股），返回 6 位代码列表（默认前 50）。"""
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    if cache_only:
        return _read_hot_stock_cache(iso)[:top_n]
    if not force_refresh:
        cached = _read_json_table_row("hot_stock_cache", key_col="trade_date", key_val=iso)
        if cached and isinstance(cached.get("codes"), list) and cached["codes"]:
            return [str(c) for c in cached["codes"]][:top_n]
    pro = _get_pro()
    if pro is None:
        return []
    primary_is_new = _ths_hot_preferred_is_new()
    codes, rank_map, used_td, rank_time, is_new_used = _fetch_ths_hot_codes(
        pro,
        trade_date=td,
        top_n=top_n,
        is_new_modes=_ths_hot_is_new_modes(primary_is_new),
    )
    if codes:
        iso = f"{used_td[:4]}-{used_td[4:6]}-{used_td[6:8]}"
        if not rank_map:
            rank_map = {c: i + 1 for i, c in enumerate(codes)}
        _write_json_table_row(
            "hot_stock_cache",
            key_col="trade_date",
            key_val=iso,
            data={
                "codes": codes,
                "ranks": rank_map,
                "trade_date": iso,
                "is_new": is_new_used or primary_is_new,
                "rank_time": rank_time,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            },
            cache_date=iso,
        )
    elif cache_only:
        return _read_hot_stock_cache(iso)[:top_n]
    return codes[:top_n]


def fetch_broker_recommend(
    month: str | None = None,
    *,
    cache_only: bool = False,
    min_count: int = 2,
) -> dict[str, int]:
    """券商金股：返回 {六位代码: 推荐次数}，仅含次数 >= min_count。"""
    m = str(month or date.today().strftime("%Y%m")).replace("-", "")[:6]
    if cache_only:
        blob = _read_json_table_row("broker_recommend_cache", key_col="month", key_val=m) or {}
        counts = blob.get("counts") if isinstance(blob.get("counts"), dict) else {}
        return {k: int(v) for k, v in counts.items() if int(v) >= min_count}
    cached = _read_json_table_row("broker_recommend_cache", key_col="month", key_val=m)
    if cached and isinstance(cached.get("counts"), dict):
        counts = {k: int(v) for k, v in cached["counts"].items()}
        return {k: v for k, v in counts.items() if v >= min_count}
    pro = _get_pro()
    if pro is None:
        return {}
    counts: dict[str, int] = {}
    try:
        _acquire_tushare_daily_slot()
        df = pro.broker_recommend(month=m)
        if df is not None and not getattr(df, "empty", True):
            for _, row in df.iterrows():
                c = _norm_hot_code(row.get("ts_code") or row.get("code"))
                if not c:
                    continue
                counts[c] = counts.get(c, 0) + 1
    except Exception:
        _LOG.debug("broker_recommend 失败 month=%s", m, exc_info=True)
    _write_json_table_row(
        "broker_recommend_cache",
        key_col="month",
        key_val=m,
        data={"counts": counts, "month": m},
        cache_date=date.today().isoformat(),
    )
    return {k: v for k, v in counts.items() if v >= min_count}


def _fetch_hot_concept_rows(
    trade_date: str | None = None,
    *,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    """同花顺概念指数（ths_index）按涨跌幅降序，返回前 top_n 条元数据。"""
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    pro = _get_pro()
    if pro is None:
        return []
    rows: list[dict[str, Any]] = []
    for try_td in [td] + [d for d in _recent_trade_dates_yyyymmdd(8) if d != td]:
        try:
            _acquire_tushare_daily_slot()
            df = pro.ths_index(trade_date=try_td)
            if df is None or getattr(df, "empty", True):
                continue
            pct_col = "pct_change" if "pct_change" in df.columns else "change_pct"
            for _, row in df.iterrows():
                ts = str(row.get("ts_code") or "").strip().upper()
                if not ts:
                    continue
                typ = str(row.get("type") or row.get("index_type") or "").strip()
                if typ and "概念" not in typ and "concept" not in typ.lower():
                    continue
                pct = _latest_float(row, pct_col, "pct_chg", "change")
                rows.append(
                    {
                        "ts_code": ts,
                        "name": str(row.get("name") or ""),
                        "pct_change": pct,
                    }
                )
            if rows:
                td = try_td
                break
        except Exception:
            _LOG.debug("ths_index 失败 trade_date=%s", try_td, exc_info=True)
    rows.sort(key=lambda x: (x.get("pct_change") is None, -(x.get("pct_change") or -999.0)))
    return rows[: max(1, int(top_n))]


def fetch_hot_concepts(
    trade_date: str | None = None,
    *,
    top_n: int = 5,
) -> list[str]:
    """同花顺概念板块涨幅前 top_n 的 ts_code 列表（ths_index）。"""
    return [
        str(r.get("ts_code") or "").strip()
        for r in _fetch_hot_concept_rows(trade_date, top_n=top_n)
        if str(r.get("ts_code") or "").strip()
    ]


def _dc_concept_code_for_member(
    concept_ts_code: str,
    concept_name: str = "",
    trade_date: str | None = None,
) -> str:
    """dc_member 需 BKxxxx.DC；同花顺代码通过名称与 dc_index 对齐。"""
    cc = str(concept_ts_code or "").strip().upper()
    if cc.endswith(".DC"):
        return cc
    nm = str(concept_name or "").strip()
    for row in fetch_concept_index(trade_date):
        dc = str(row.get("ts_code") or "").strip().upper()
        dn = str(row.get("name") or "").strip()
        if not dc.endswith(".DC"):
            continue
        if nm and nm == dn:
            return dc
    if nm:
        for row in fetch_concept_index(trade_date):
            dc = str(row.get("ts_code") or "").strip().upper()
            dn = str(row.get("name") or "").strip()
            if not dc.endswith(".DC"):
                continue
            if nm in dn or dn in nm:
                return dc
    return ""


def fetch_concept_members_for_codes(
    concept_codes: list[str] | tuple[str, ...] | set[str],
    trade_date: str | None = None,
    *,
    cache_only: bool = False,
    concept_names: dict[str, str] | None = None,
) -> set[str]:
    """多个概念成分股并集（dc_member）。"""
    names = concept_names if isinstance(concept_names, dict) else {}
    out: set[str] = set()
    for raw in concept_codes:
        cc = str(raw or "").strip().upper()
        if not cc:
            continue
        dc_code = _dc_concept_code_for_member(cc, names.get(cc, ""), trade_date)
        member_code = dc_code or (cc if cc.endswith(".DC") else "")
        if not member_code:
            continue
        for m in fetch_concept_members(member_code, trade_date, cache_only=cache_only):
            c6 = _norm_code6(m)
            if c6:
                out.add(c6)
    return out


def _clear_hot_concept_stocks_cache(trade_date_iso: str) -> None:
    iso = str(trade_date_iso)[:10]
    try:
        conn = _open_stock_financial_cache()
        try:
            conn.execute(
                "DELETE FROM hot_concept_stocks_cache WHERE trade_date = ?",
                (iso,),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        _LOG.debug("清理 hot_concept_stocks_cache 失败", exc_info=True)


def _write_hot_concept_stock_row(
    trade_date_iso: str,
    code: str,
    *,
    tier: str,
    concept_codes: list[str],
) -> None:
    c6 = _norm_code6(code)
    if not c6:
        return
    iso = str(trade_date_iso)[:10]
    payload = json.dumps(
        {"tier": tier, "concept_codes": concept_codes},
        ensure_ascii=False,
        sort_keys=True,
    )
    now_s = datetime.now().isoformat(timespec="seconds")
    try:
        conn = _open_stock_financial_cache()
        try:
            conn.execute(
                """
                INSERT INTO hot_concept_stocks_cache(trade_date, code, json_data, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(trade_date, code) DO UPDATE SET
                  json_data=excluded.json_data,
                  updated_at=excluded.updated_at
                """,
                (iso, c6, payload, now_s),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        _LOG.debug("写入 hot_concept_stocks_cache 失败 %s", c6, exc_info=True)


def _read_hot_concept_stock_meta(
    code: str,
    trade_date_iso: str | None = None,
) -> dict[str, Any] | None:
    c6 = _norm_code6(code)
    if not c6:
        return None
    iso = str(trade_date_iso or date.today().isoformat())[:10]
    try:
        conn = _open_stock_financial_cache()
        try:
            row = conn.execute(
                """
                SELECT json_data FROM hot_concept_stocks_cache
                WHERE trade_date = ? AND code = ?
                """,
                (iso, c6),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """
                    SELECT json_data FROM hot_concept_stocks_cache
                    WHERE code = ?
                    ORDER BY trade_date DESC LIMIT 1
                    """,
                    (c6,),
                ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        data = json.loads(str(row["json_data"] or "{}"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def refresh_hot_concept_stocks_cache(
    trade_date: str | None = None,
    *,
    top_n: int = 5,
    cache_only: bool = False,
) -> dict[str, int]:
    """
    刷新当日热门概念成分股缓存（ths_index 涨幅前 top_n → dc_member 成分并集）。
    涨幅前 3 名概念成分标 tier=fire，第 4–5 名标 tier=rocket。
    """
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    if cache_only:
        try:
            conn = _open_stock_financial_cache()
            try:
                n = conn.execute(
                    "SELECT COUNT(*) FROM hot_concept_stocks_cache WHERE trade_date = ?",
                    (iso,),
                ).fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            n = 0
        return {"concepts": 0, "stocks": int(n or 0)}

    rows = _fetch_hot_concept_rows(trade_date, top_n=top_n)
    if not rows:
        return {"concepts": 0, "stocks": 0}

    stock_best_rank: dict[str, int] = {}
    stock_concepts: dict[str, list[str]] = {}
    names = {str(r.get("ts_code") or ""): str(r.get("name") or "") for r in rows}
    concept_codes = [str(r.get("ts_code") or "") for r in rows if r.get("ts_code")]

    for rank, row in enumerate(rows):
        cc = str(row.get("ts_code") or "").strip()
        if not cc:
            continue
        dc_code = _dc_concept_code_for_member(cc, str(row.get("name") or ""), td)
        member_code = dc_code or (cc if cc.upper().endswith(".DC") else "")
        if not member_code:
            continue
        members = fetch_concept_members(member_code, td, cache_only=False)
        for m in members:
            c6 = _norm_code6(m)
            if not c6:
                continue
            prev = stock_best_rank.get(c6, 999)
            if rank < prev:
                stock_best_rank[c6] = rank
            stock_concepts.setdefault(c6, [])
            if cc not in stock_concepts[c6]:
                stock_concepts[c6].append(cc)

    _clear_hot_concept_stocks_cache(iso)
    for c6, rk in stock_best_rank.items():
        tier = "fire" if rk < 3 else "rocket"
        _write_hot_concept_stock_row(
            iso, c6, tier=tier, concept_codes=stock_concepts.get(c6, concept_codes)
        )

    return {"concepts": len(rows), "stocks": len(stock_best_rank)}


def is_hot_concept_stock(
    code: str,
    *,
    cache_only: bool = True,
    trade_date: str | None = None,
) -> bool:
    return hot_concept_factor_label(code, cache_only=cache_only, trade_date=trade_date) is not None


def hot_concept_factor_label(
    code: str,
    *,
    cache_only: bool = True,
    trade_date: str | None = None,
) -> str | None:
    """热门概念因子行标签：涨幅前 3 概念为 🔥概念，第 4–5 名为 🚀概念。"""
    if not cache_only:
        refresh_hot_concept_stocks_cache(trade_date, top_n=5, cache_only=False)
    meta = _read_hot_concept_stock_meta(code, trade_date_iso=_trade_date_iso(trade_date))
    if not meta:
        return None
    tier = str(meta.get("tier") or "").strip().lower()
    if tier == "rocket":
        return "🚀概念"
    return "🔥概念"


def _trade_date_iso(trade_date: str | None) -> str:
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    return f"{td[:4]}-{td[4:6]}-{td[6:8]}"


def fetch_concept_index(trade_date: str | None = None) -> list[dict[str, Any]]:
    """东财概念板块（dc_index），按涨跌幅降序；供 dc_member 取成分。"""
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    pro = _get_pro()
    if pro is None:
        return []
    rows: list[dict[str, Any]] = []
    for try_td in [td] + [d for d in _recent_trade_dates_yyyymmdd(8) if d != td]:
        try:
            _acquire_tushare_daily_slot()
            df = pro.dc_index(trade_date=try_td)
            if df is None or getattr(df, "empty", True):
                continue
            pct_col = "pct_change" if "pct_change" in df.columns else "change_pct"
            for _, row in df.iterrows():
                ts = str(row.get("ts_code") or "").strip().upper()
                if not ts.endswith(".DC"):
                    continue
                pct = _latest_float(row, pct_col, "pct_chg", "change")
                rows.append(
                    {
                        "ts_code": ts,
                        "name": str(row.get("name") or ""),
                        "pct_change": pct,
                    }
                )
            if rows:
                break
        except Exception:
            _LOG.debug("dc_index 失败 trade_date=%s", try_td, exc_info=True)
    rows.sort(key=lambda x: (x.get("pct_change") is None, -(x.get("pct_change") or -999.0)))
    return rows


def fetch_concept_members(concept_ts_code: str, trade_date: str | None = None, *, cache_only: bool = False) -> list[str]:
    """概念成分股（dc_member，概念代码须为 BKxxxx.DC）。"""
    cc = str(concept_ts_code or "").strip().upper()
    if not cc:
        return []
    if not cc.endswith(".DC"):
        return []
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    if cache_only:
        blob = _read_json_table_row("concept_member_cache", key_col="concept_code", key_val=cc, cache_date=iso)
        if blob and isinstance(blob.get("members"), list):
            return [str(x) for x in blob["members"]]
        return []
    try:
        conn = _open_stock_financial_cache()
        try:
            row = conn.execute(
                """
                SELECT json_data FROM concept_member_cache
                WHERE concept_code = ? AND trade_date = ?
                """,
                (cc, iso),
            ).fetchone()
        finally:
            conn.close()
        if row:
            data = json.loads(str(row["json_data"] or "{}"))
            if isinstance(data.get("members"), list):
                return [str(x) for x in data["members"]]
    except (sqlite3.Error, json.JSONDecodeError):
        pass
    pro = _get_pro()
    if pro is None:
        return []
    members: list[str] = []
    try:
        _acquire_tushare_daily_slot()
        df = pro.dc_member(ts_code=cc, trade_date=td)
        if df is None or getattr(df, "empty", True):
            df = pro.dc_member(ts_code=cc)
        if df is not None and not getattr(df, "empty", True):
            for _, row in df.iterrows():
                c = _norm_a_share_code6(row.get("con_code") or row.get("ts_code") or row.get("code"))
                if c and c not in members:
                    members.append(c)
    except Exception:
        _LOG.debug("dc_member 失败 %s", cc, exc_info=True)
    _write_json_table_row(
        "concept_member_cache",
        key_col="concept_code",
        key_val=cc,
        data={"members": members, "concept_code": cc, "trade_date": iso},
        cache_date=iso,
    )
    return members


def load_stock_to_sw_map_for_factors(root: Path | None = None) -> dict[str, str]:
    from sw_member_cache import load_stock_to_sw_map

    return load_stock_to_sw_map(resolved_stock_to_sw_path(root))


def get_broker_recommend_count(
    code: str,
    *,
    cache_only: bool = True,
    month: str | None = None,
) -> int:
    c6 = _norm_code6(code)
    if not c6:
        return 0
    counts = fetch_broker_recommend(month=month, cache_only=cache_only)
    return int(counts.get(c6, 0))


def is_hot_stock(
    code: str,
    *,
    cache_only: bool = True,
    top_n: int = 50,
    trade_date: str | None = None,
) -> bool:
    c6 = _norm_code6(code)
    if not c6:
        return False
    td = str(trade_date or _today_yyyymmdd()).replace("-", "")[:8]
    iso = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
    if cache_only:
        blob = _read_hot_stock_cache_blob(iso)
        codes = blob.get("codes") if isinstance(blob.get("codes"), list) else []
        if not codes and not trade_date:
            return False
        return c6 in {str(x) for x in codes}
    hot = fetch_hot_stocks(trade_date=trade_date, cache_only=False, top_n=top_n)
    return c6 in set(hot)


def update_tushare_special_factors_for_candidates(
    codes: list[str] | set[str] | tuple[str, ...],
    *,
    code_to_sw: dict[str, str] | None = None,
    moneyflow_days: int = 5,
    hot_top_n: int = 50,
    concept_top_n: int = 5,
) -> dict[str, int]:
    """
    收盘后批量刷新：个股/行业资金流、热股榜、券商金股、热门概念成分股。
    失败单票/单行业跳过。
    """
    stats = {
        "stock_moneyflow": 0,
        "industry_moneyflow": 0,
        "hot_stocks": 0,
        "broker_recommend": 0,
        "concept_members": 0,
        "hot_concept_stocks": 0,
    }
    norm_codes = sorted({str(c).strip().zfill(6) for c in codes if _norm_code6(c)})
    sw_map = ensure_sw_map_for_codes(norm_codes, code_to_sw if isinstance(code_to_sw, dict) else None)

    for raw in norm_codes:
        try:
            if fetch_moneyflow_individual(raw, days=moneyflow_days):
                stats["stock_moneyflow"] += 1
        except Exception:
            _LOG.debug("刷新个股资金流失败 %s", raw, exc_info=True)

    try:
        stats["industry_moneyflow"] = _aggregate_industry_moneyflow_from_stocks(norm_codes, sw_map)
    except Exception:
        _LOG.debug("汇总行业资金流失败", exc_info=True)

    try:
        hot = fetch_hot_stocks(top_n=hot_top_n, force_refresh=True)
        stats["hot_stocks"] = len(hot)
    except Exception:
        _LOG.debug("刷新热股榜失败", exc_info=True)

    try:
        br = fetch_broker_recommend()
        stats["broker_recommend"] = len(br)
    except Exception:
        _LOG.debug("刷新券商金股失败", exc_info=True)

    try:
        hc = refresh_hot_concept_stocks_cache(top_n=max(1, int(concept_top_n)))
        stats["hot_concept_stocks"] = int(hc.get("stocks", 0))
        stats["concept_members"] = int(hc.get("concepts", 0))
    except Exception:
        _LOG.debug("刷新热门概念成分股缓存失败", exc_info=True)

    return stats


def update_financial_factors_for_all_candidates(
    codes: list[str] | set[str] | tuple[str, ...],
    *,
    include_margin: bool = True,
    include_top_inst: bool = False,
) -> dict[str, int]:
    """收盘后批量刷新候选股票的财务/融资/龙虎榜缓存；失败单票跳过。"""
    stats = {"financial": 0, "margin": 0, "top_inst": 0}
    for raw in sorted({str(c).strip().zfill(6) for c in codes if str(c).strip()}):
        if not _norm_code6(raw):
            continue
        try:
            if fetch_financial_factors(raw):
                stats["financial"] += 1
        except Exception:
            _LOG.debug("刷新 financial 缓存失败 %s", raw, exc_info=True)
        if include_margin:
            try:
                if fetch_margin_factor(raw):
                    stats["margin"] += 1
            except Exception:
                _LOG.debug("刷新 margin 缓存失败 %s", raw, exc_info=True)
        if include_top_inst:
            try:
                if fetch_top_inst_factor(raw):
                    stats["top_inst"] += 1
            except Exception:
                _LOG.debug("刷新 top_inst 缓存失败 %s", raw, exc_info=True)
    return stats


def secid_to_ts_code(secid: str) -> str | None:
    """东财 secid → Tushare ts_code；板块 90.BK* 等不支持，返回 None。"""
    s = str(secid).strip()
    if s.startswith("90.") or s.startswith("92."):
        return None
    if "." not in s:
        return None
    prefix, code = s.split(".", 1)
    code = code.strip().zfill(6)
    if not code.isdigit() or len(code) != 6:
        return None
    if prefix == "1":
        return f"{code}.SH"
    if prefix == "0":
        return f"{code}.SZ"
    return None


def _norm_trade_date(raw: Any) -> str:
    s = str(raw).strip()
    if len(s) >= 8 and s[:8].isdigit():
        s8 = s[:8]
        return f"{s8[:4]}-{s8[4:6]}-{s8[6:8]}"
    return s[:10]


def fetch_index_hist_index_daily(
    ts_code: str, *, limit: int = 120
) -> tuple[list[float], list[float], str | None] | None:
    """
    任意指数历史日 K（index_daily），升序；最后一根日期供与 rt_idx_k 对齐。
    ts_code 如 000001.SH、000300.SH、399006.SZ。
    """
    pro = _get_pro()
    if pro is None:
        return None
    tc = str(ts_code or "").strip().upper()
    if not tc:
        return None
    want = max(40, int(limit))
    start_s, end_s = _date_window_for_bars(want)
    try:
        df = pro.index_daily(ts_code=tc, start_date=start_s, end_date=end_s)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    tail = df.tail(want)
    try:
        closes = [float(x) for x in tail["close"].tolist()]
    except Exception:
        return None
    if "vol" in tail.columns:
        vols = [max(0.0, float(x or 0.0)) for x in tail["vol"].tolist()]
    else:
        vols = [0.0] * len(closes)
    if len(closes) < 20:
        return None
    last_td: str | None = None
    try:
        last_td = _norm_trade_date(tail.iloc[-1].get("trade_date"))[:10]
    except Exception:
        pass
    return closes, vols, last_td


def fetch_sh_index_hist_index_daily(
    *, limit: int = 120
) -> tuple[list[float], list[float], str | None] | None:
    """上证指数；等价于 fetch_index_hist_index_daily(\"000001.SH\", limit=...)。"""
    return fetch_index_hist_index_daily("000001.SH", limit=limit)


def _date_window_for_bars(want: int) -> tuple[str, str]:
    from datetime import date

    end = date.today()
    span = min(4000, max(400, int(want) * 3))
    start = end - timedelta(days=span)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _rt_idx_k_latest_row(ts_code: str) -> dict[str, Any] | None:
    """指数实时日线（独立权限）；返回最新一行含 trade_date、close、vol 等。"""
    pro = _get_pro()
    if pro is None:
        return None
    try:
        df = pro.rt_idx_k(ts_code=str(ts_code).strip())
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    if "trade_date" in df.columns:
        df = df.sort_values("trade_date")
    row = df.iloc[-1]
    try:
        td = _norm_trade_date(row.get("trade_date"))
        c = float(row.get("close") or 0.0)
        v = float(row.get("vol") or row.get("volume") or 0.0)
    except (TypeError, ValueError):
        return None
    if c <= 0 or not td:
        return None
    return {"trade_date": td[:10], "close": c, "vol": max(v, 0.0)}


def merge_index_closes_with_rt_idx_k(
    closes: list[float],
    vols: list[float],
    *,
    ts_code: str,
    free_last_date: str | None,
) -> tuple[list[float], list[float]]:
    """
    用 rt_idx_k 覆盖或追加「最新交易日」收盘/量；历史序列由 index_daily 提供。
    ts_code：指数代码，如 000001.SH、000300.SH。
    """
    if not (_CFG.get("enabled") and _resolved_token()):
        return closes, vols
    if not closes or len(closes) < 20:
        return closes, vols
    tc = str(ts_code or "").strip().upper()
    if not tc:
        return closes, vols
    snap = _rt_idx_k_latest_row(tc)
    if not snap:
        return closes, vols
    rt_d = str(snap["trade_date"]).strip()[:10]
    rt_c = float(snap["close"])
    rt_v = float(snap["vol"])
    fl = (str(free_last_date).strip()[:10] if free_last_date else "") or None

    c = list(closes)
    v = list(vols)
    if len(v) < len(c):
        v.extend([0.0] * (len(c) - len(v)))
    elif len(v) > len(c):
        v = v[: len(c)]

    if fl and rt_d < fl:
        return closes, vols
    if fl and rt_d > fl:
        return c + [rt_c], v + [rt_v]
    c[-1] = rt_c
    v[-1] = rt_v
    return c, v


def merge_sh_index_with_rt_idx_k(
    closes: list[float],
    vols: list[float],
    *,
    free_last_date: str | None,
) -> tuple[list[float], list[float]]:
    """上证综指 rt_idx_k 合并；内部调用 merge_index_closes_with_rt_idx_k。"""
    return merge_index_closes_with_rt_idx_k(
        closes, vols, ts_code="000001.SH", free_last_date=free_last_date
    )


def fetch_stock_rt_k(ts_code: str) -> dict[str, Any] | None:
    """
    A 股实时日线（独立权限 rt_k）；返回单条：trade_date, open, high, low, close, vol。
    """
    if not stock_rt_k_enabled():
        return None
    pro = _get_pro()
    if pro is None:
        return None
    tc = str(ts_code).strip()
    if not tc:
        return None
    try:
        df = pro.rt_k(ts_code=tc)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    if "ts_code" in df.columns and len(df) > 1:
        try:
            df = df[df["ts_code"].astype(str).str.strip() == tc]
        except Exception:
            pass
    if df is None or getattr(df, "empty", True):
        return None
    row = df.iloc[-1]
    try:
        td_raw = row.get("trade_date")
        if td_raw is None or (isinstance(td_raw, float) and str(td_raw) == "nan"):
            return None
        td = _norm_trade_date(td_raw)[:10]
        o = float(row.get("open") or 0.0)
        h = float(row.get("high") or 0.0)
        low = float(row.get("low") or 0.0)
        c = float(row.get("close") or 0.0)
        v = float(row.get("vol") or row.get("volume") or 0.0)
    except (TypeError, ValueError):
        return None
    if c <= 0 or not td:
        return None
    return {
        "trade_date": td,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "vol": max(v, 0.0),
    }


def merge_stock_rows_with_rt_k(
    secid: str,
    rows: list[tuple[str, float, float, float, float, float]],
    *,
    ut: str | None = None,
) -> list[tuple[str, float, float, float, float, float]]:
    """历史日 K 行（升序）与 rt_k 合并最后一根或追加。"""
    if not stock_rt_k_enabled() or len(rows) < 20:
        return rows
    ts_code = secid_to_ts_code(secid)
    if not ts_code:
        return rows
    rt = fetch_stock_rt_k(ts_code)
    if not rt:
        return rows

    hist_last = str(rows[-1][0]).strip()[:10]
    rt_d = str(rt["trade_date"]).strip()[:10]
    o = float(rt["open"])
    h = float(rt["high"])
    low = float(rt["low"])
    c = float(rt["close"])
    v = max(float(rt["vol"]), 0.0)

    out = list(rows)
    if rt_d < hist_last:
        return rows
    if rt_d > hist_last:
        out.append((rt_d, o, h, low, c, v))
        return out
    out[-1] = (rt_d, o, h, low, c, v)
    return out


def merge_stock_ohlcv_lists_with_rt_k(
    secid: str,
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    vols: list[float],
    *,
    hist_last_date: str | None,
    ut: str | None = None,
) -> tuple[list[float], list[float], list[float], list[float], list[float], str | None]:
    """与 merge_stock_rows_with_rt_k 等价；返回合并后 OHLCV 与最后一根 trade_date（YYYY-MM-DD）。"""
    base_last = (
        str(hist_last_date).strip()[:10] if hist_last_date else None
    ) or None
    if not stock_rt_k_enabled() or len(closes) < 20:
        return opens, highs, lows, closes, vols, base_last
    ts_code = secid_to_ts_code(secid)
    if not ts_code:
        return opens, highs, lows, closes, vols, base_last
    rt = fetch_stock_rt_k(ts_code)
    if not rt:
        return opens, highs, lows, closes, vols, base_last

    fl = base_last
    rt_d = str(rt["trade_date"]).strip()[:10]
    o = float(rt["open"])
    h = float(rt["high"])
    low = float(rt["low"])
    c = float(rt["close"])
    v = max(float(rt["vol"]), 0.0)

    o2, h2, l2, c2, v2 = (
        list(opens),
        list(highs),
        list(lows),
        list(closes),
        list(vols),
    )
    if len(v2) < len(c2):
        v2.extend([0.0] * (len(c2) - len(v2)))
    elif len(v2) > len(c2):
        v2 = v2[: len(c2)]
    for lst in (o2, h2, l2):
        if len(lst) < len(c2):
            lst.extend([0.0] * (len(c2) - len(lst)))
        elif len(lst) > len(c2):
            del lst[len(c2) :]

    if fl and rt_d < fl:
        return opens, highs, lows, closes, vols, base_last
    if fl and rt_d > fl:
        return (
            o2 + [o],
            h2 + [h],
            l2 + [low],
            c2 + [c],
            v2 + [v],
            rt_d,
        )
    o2[-1] = o
    h2[-1] = h
    l2[-1] = low
    c2[-1] = c
    v2[-1] = v
    return o2, h2, l2, c2, v2, rt_d


def resolved_stock_basic_cache_path(root: Path | None = None) -> Path:
    r = root or Path(__file__).resolve().parent
    p = Path(str(_CFG.get("stock_basic_cache_path") or "data/stock_basic_cache.json"))
    return p if p.is_absolute() else (r / p)


def resolved_stock_to_sw_path(root: Path | None = None) -> Path:
    r = root or Path(__file__).resolve().parent
    p = Path(str(_CFG.get("stock_to_sw_path") or "data/stock_to_sw.json"))
    return p if p.is_absolute() else (r / p)


def fetch_stock_kline_rows_pro_bar(
    secid: str, lmt: int
) -> list[tuple[str, float, float, float, float, float]] | None:
    ts_code = secid_to_ts_code(secid)
    if not ts_code or not (_CFG.get("enabled") and _resolved_token()):
        return None
    want = max(40, int(lmt))
    start_s, end_s = _date_window_for_bars(want)
    try:
        import tushare as ts

        _acquire_tushare_adj_factor_slot()
        _acquire_tushare_daily_slot()
        ts.set_token(_resolved_token())
        df = ts.pro_bar(ts_code=ts_code, adj="qfq", start_date=start_s, end_date=end_s)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    tail = df.tail(want)
    rows: list[tuple[str, float, float, float, float, float]] = []
    for _, row in tail.iterrows():
        try:
            ds = _norm_trade_date(row.get("trade_date"))
            o = float(row.get("open") or 0.0)
            h = float(row.get("high") or 0.0)
            low = float(row.get("low") or 0.0)
            c = float(row.get("close") or 0.0)
            v = float(row.get("vol") or row.get("volume") or 0.0)
        except (TypeError, ValueError):
            continue
        rows.append((ds, o, h, low, c, max(v, 0.0)))
    if len(rows) < 20:
        return None
    return rows


_LOG = logging.getLogger(__name__)

# 申万一级行业 ts_code（与 data/sw_l1_names.json 一致；文件缺失时作硬编码回退）
_DEFAULT_SW_L1_TS_CODES: tuple[str, ...] = (
    "801010.SI",
    "801030.SI",
    "801040.SI",
    "801050.SI",
    "801080.SI",
    "801110.SI",
    "801120.SI",
    "801130.SI",
    "801140.SI",
    "801150.SI",
    "801160.SI",
    "801170.SI",
    "801180.SI",
    "801200.SI",
    "801210.SI",
    "801230.SI",
    "801710.SI",
    "801720.SI",
    "801730.SI",
    "801740.SI",
    "801750.SI",
    "801760.SI",
    "801770.SI",
    "801780.SI",
    "801790.SI",
    "801880.SI",
    "801890.SI",
    "801950.SI",
    "801960.SI",
    "801970.SI",
    "801980.SI",
)


def list_sw_l1_ts_codes(root: Path | None = None) -> list[str]:
    """申万一级行业代码列表（801xxx.SI），优先 data/sw_l1_names.json。"""
    r = root or Path(__file__).resolve().parent
    path = r / "data" / "sw_l1_names.json"
    if path.is_file():
        try:
            j = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(j, dict):
                codes = sorted(
                    str(k).strip().upper()
                    for k in j
                    if str(k).strip().upper().endswith(".SI")
                )
                if codes:
                    return codes
        except (json.JSONDecodeError, OSError):
            _LOG.debug("list_sw_l1_ts_codes read %s", path, exc_info=True)
    return list(_DEFAULT_SW_L1_TS_CODES)


def _normalize_rt_sw_k_row(
    row: Any,
    *,
    default_ts_code: str | None = None,
) -> dict[str, Any] | None:
    """rt_sw_k 单行 → 统一 dict（内部涨跌幅字段为 pct_chg）。"""
    tc = str(row.get("ts_code") or default_ts_code or "").strip().upper()
    if not (tc.endswith(".SI") and tc[:-3].isdigit()):
        return None
    try:
        c = float(row.get("close") or 0.0)
        v = float(row.get("vol") or row.get("volume") or 0.0)
    except (TypeError, ValueError):
        return None
    if c <= 0:
        return None
    trade_time = str(row.get("trade_time") or "").strip()
    trade_date = trade_time[:10] if len(trade_time) >= 10 else ""
    if not trade_date:
        td_raw = row.get("trade_date")
        if td_raw is not None:
            try:
                trade_date = _norm_trade_date(td_raw)[:10]
            except Exception:
                trade_date = ""
    if not trade_date:
        trade_date = date.today().isoformat()
    pct_raw = row.get("pct_change")
    if pct_raw is None:
        pct_raw = row.get("pct_chg")
    pct: float | None
    try:
        pct = float(pct_raw) if pct_raw is not None and str(pct_raw) != "nan" else None
    except (TypeError, ValueError):
        pct = None
    name = str(row.get("name") or "").strip()
    out: dict[str, Any] = {
        "ts_code": tc,
        "trade_time": trade_time or None,
        "trade_date": trade_date,
        "close": c,
        "vol": max(v, 0.0),
    }
    if name:
        out["name"] = name
    if pct is not None:
        out["pct_chg"] = pct
        out["pct_change"] = pct
    for col in ("pre_close", "open", "high", "low", "amount"):
        val = row.get(col)
        if val is None or (isinstance(val, float) and str(val) == "nan"):
            continue
        try:
            out[col] = float(val)
        except (TypeError, ValueError):
            out[col] = val
    return out


def _fetch_rt_sw_k_dataframe(ts_code: str | None = None) -> pd.DataFrame | None:
    """调用 pro.rt_sw_k；ts_code 为空时拉全市场申万指数截面。"""
    if not (_CFG.get("enabled") and _resolved_token()) or not bool(
        _CFG.get("sw_enabled", True)
    ):
        return None
    pro = _get_pro()
    if pro is None:
        return None
    try:
        if ts_code:
            df = pro.rt_sw_k(ts_code=str(ts_code).strip())
        else:
            df = pro.rt_sw_k()
    except Exception as exc:
        label = ts_code or "ALL"
        msg = str(exc)
        if "请指定正确的接口名" in msg or "rt_sw_idx_k" in msg:
            _LOG.error(
                "rt_sw_k 失败 %s: %s（若日志仍出现 rt_sw_idx_k，请确认已保存 quote_tushare.py 并重启 run_alert）",
                label,
                msg,
            )
        else:
            _LOG.warning("rt_sw_k 失败 %s: %s", label, msg)
        return None
    if df is None or getattr(df, "empty", True):
        _LOG.debug("rt_sw_k 空表 %s", ts_code or "ALL")
        return None
    return df


def fetch_sector_realtime(ts_code: str) -> dict[str, Any] | None:
    """
    申万行业指数实时截面（独立权限 rt_sw_k）。
    返回：ts_code、name、pct_chg（由 pct_change 归一化）、trade_time、trade_date、close 等。
    """
    tc = str(ts_code or "").strip().upper()
    if not (tc.endswith(".SI") and tc[:-3].isdigit()):
        return None
    df = _fetch_rt_sw_k_dataframe(ts_code=tc)
    if df is None or getattr(df, "empty", True):
        return None
    if "ts_code" in df.columns and len(df) > 1:
        try:
            sub = df[df["ts_code"].astype(str).str.strip().str.upper() == tc]
            if not sub.empty:
                df = sub
        except Exception:
            pass
    if "trade_time" in df.columns:
        df = df.sort_values("trade_time")
    elif "trade_date" in df.columns:
        df = df.sort_values("trade_date")
    row = df.iloc[-1]
    snap = _normalize_rt_sw_k_row(row, default_ts_code=tc)
    if snap is None:
        _LOG.debug("rt_sw_k 解析失败 %s", tc, exc_info=True)
    return snap


def fetch_all_sectors_realtime(
    *,
    root: Path | None = None,
    sleep_sec: float = 0.04,
) -> pd.DataFrame:
    """
    汇总申万一级 rt_sw_k 实时行情为 DataFrame。
    优先 pro.rt_sw_k() 一次拉全表再筛一级行业；失败时分批 ts_code 请求。
    """
    l1_codes = list_sw_l1_ts_codes(root)
    l1_set = frozenset(l1_codes)
    rows: list[dict[str, Any]] = []

    df_all = _fetch_rt_sw_k_dataframe(ts_code=None)
    if df_all is not None and not getattr(df_all, "empty", True):
        for _, row in df_all.iterrows():
            tc = str(row.get("ts_code") or "").strip().upper()
            if tc not in l1_set:
                continue
            snap = _normalize_rt_sw_k_row(row)
            if snap:
                rows.append(snap)
        if rows:
            _LOG.debug("rt_sw_k 全量拉取：申万一级 %s 条", len(rows))
            return pd.DataFrame(rows)

    batch_size = 12
    for i in range(0, len(l1_codes), batch_size):
        chunk = ",".join(l1_codes[i : i + batch_size])
        df = _fetch_rt_sw_k_dataframe(ts_code=chunk)
        if df is None or getattr(df, "empty", True):
            continue
        for _, row in df.iterrows():
            tc = str(row.get("ts_code") or "").strip().upper()
            if tc not in l1_set:
                continue
            snap = _normalize_rt_sw_k_row(row)
            if snap and not any(r.get("ts_code") == tc for r in rows):
                rows.append(snap)
        if sleep_sec > 0 and i + batch_size < len(l1_codes):
            time.sleep(float(sleep_sec))

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _rt_sw_k_latest_row(ts_code: str) -> dict[str, Any] | None:
    """申万指数实时截面最后一根（rt_sw_k）；供日 K 合并用。"""
    snap = fetch_sector_realtime(ts_code)
    if not snap:
        return None
    try:
        td = str(snap.get("trade_date") or "")[:10]
        c = float(snap.get("close") or 0.0)
        v = float(snap.get("vol") or 0.0)
    except (TypeError, ValueError):
        return None
    if c <= 0 or not td:
        return None
    return {"trade_date": td, "close": c, "vol": max(v, 0.0)}


# 旧名兼容（内部已统一 rt_sw_k，勿再调用 pro.rt_sw_idx_k）
_rt_sw_idx_k_latest_row = _rt_sw_k_latest_row


def merge_sw_index_with_rt_sw(
    closes: list[float],
    vols: list[float],
    *,
    ts_code: str,
    free_last_date: str | None,
) -> tuple[list[float], list[float]]:
    if not (_CFG.get("enabled") and _resolved_token()) or not bool(_CFG.get("sw_enabled", True)):
        return closes, vols
    if not closes or len(closes) < 10:
        return closes, vols
    snap = _rt_sw_k_latest_row(ts_code)
    if not snap:
        return closes, vols
    rt_d = str(snap["trade_date"]).strip()[:10]
    rt_c = float(snap["close"])
    rt_v = float(snap["vol"])
    fl = (str(free_last_date).strip()[:10] if free_last_date else "") or None

    c = list(closes)
    v = list(vols)
    if len(v) < len(c):
        v.extend([0.0] * (len(c) - len(v)))
    elif len(v) > len(c):
        v = v[: len(c)]

    if fl and rt_d < fl:
        return closes, vols
    if fl and rt_d > fl:
        return c + [rt_c], v + [rt_v]
    c[-1] = rt_c
    v[-1] = rt_v
    return c, v


def _fetch_sw_level1_daily_df(pro: Any, tc: str, start_s: str, end_s: str) -> Any:
    """
    申万一级行业日 K：官方「申万行业日线」为 sw_daily（801xxx.SI）；部分环境 sw_index_daily 空表，故先 sw_daily 再回退。
    """
    if bool(_CFG.get("sw_daily_bulk_enabled", False)):
        bulk = _fetch_sw_level1_bulk_daily_df(pro, start_s, end_s)
        if bulk is not None and not getattr(bulk, "empty", True) and "ts_code" in bulk.columns:
            try:
                sub = bulk[bulk["ts_code"].astype(str).str.strip().str.upper() == tc]
                if not sub.empty:
                    _LOG.debug("sw_daily 批量缓存命中 %s 行数=%s", tc, len(sub))
                    return sub
                return None
            except Exception:
                _LOG.debug("sw_daily 批量缓存筛选失败 %s", tc, exc_info=True)
        if _SW_DAILY_BULK_RATE_LIMITED:
            return None
    for api in ("sw_daily", "sw_index_daily"):
        try:
            fn = getattr(pro, api, None)
            if api == "sw_daily":
                _acquire_sw_daily_slot()
            else:
                _acquire_tushare_daily_slot()
            if callable(fn):
                df = fn(ts_code=tc, start_date=start_s, end_date=end_s)
            else:
                q = getattr(pro, "query", None)
                if not callable(q):
                    continue
                df = q(api, ts_code=tc, start_date=start_s, end_date=end_s)
        except Exception as exc:
            _LOG.debug("%s 失败 %s: %s", api, tc, exc)
            continue
        if df is not None and not getattr(df, "empty", True):
            _LOG.debug("%s 成功 %s 行数=%s", api, tc, len(df))
            return df
    return None


def _fetch_sw_level1_bulk_daily_df(pro: Any, start_s: str, end_s: str) -> pd.DataFrame | None:
    """
    sw_daily 账号常见限制是 1 次/小时；先批量拉所有申万指数，再让各行业从缓存筛选。
    """
    global _SW_DAILY_BULK_RATE_LIMITED
    key = (str(start_s), str(end_s))
    if key in _SW_DAILY_BULK_CACHE:
        return _SW_DAILY_BULK_CACHE[key]
    if _SW_DAILY_BULK_RATE_LIMITED:
        return None
    try:
        q = getattr(pro, "query", None)
        if callable(q):
            _acquire_sw_daily_slot()
            df = q("sw_daily", start_date=start_s, end_date=end_s)
        else:
            fn = getattr(pro, "sw_daily", None)
            if not callable(fn):
                return None
            _acquire_sw_daily_slot()
            df = fn(start_date=start_s, end_date=end_s)
    except Exception as exc:
        if _is_tushare_rate_limit_error(exc):
            _SW_DAILY_BULK_RATE_LIMITED = True
            _LOG.warning("sw_daily 批量拉取触发频率限制：%s", exc)
        else:
            _LOG.debug("sw_daily 批量拉取失败: %s", exc)
        _SW_DAILY_BULK_CACHE[key] = None
        return None
    if df is None or getattr(df, "empty", True):
        _SW_DAILY_BULK_CACHE[key] = None
        return None
    _SW_DAILY_BULK_CACHE[key] = df
    _LOG.debug("sw_daily 批量拉取成功 行数=%s", len(df))
    return df


def fetch_sw_index_kline_rows(
    ts_code_si: str, lmt: int
) -> list[tuple[str, float, float, float, float, float]] | None:
    if not bool(_CFG.get("sw_enabled", True)):
        return None
    pro = _get_pro()
    if pro is None:
        return None
    tc = str(ts_code_si).strip().upper()
    if not (tc.endswith(".SI") and tc[:-3].isdigit()):
        return None
    try:
        bulk_max = int(_CFG.get("sw_daily_bulk_max_bars") or _DEFAULT_SW_DAILY_BULK_MAX_BARS)
    except (TypeError, ValueError):
        bulk_max = _DEFAULT_SW_DAILY_BULK_MAX_BARS
    want = min(max(40, int(lmt)), max(40, min(240, bulk_max)))
    start_s, end_s = _date_window_for_bars(want)
    df = _fetch_sw_level1_daily_df(pro, tc, start_s, end_s)
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    tail = df.tail(want)
    rows: list[tuple[str, float, float, float, float, float]] = []
    for _, row in tail.iterrows():
        try:
            ds = _norm_trade_date(row.get("trade_date"))
            o = float(row.get("open") or 0.0)
            h = float(row.get("high") or 0.0)
            low = float(row.get("low") or 0.0)
            c = float(row.get("close") or 0.0)
            v = float(row.get("vol") or row.get("volume") or 0.0)
        except (TypeError, ValueError):
            continue
        rows.append((ds, o, h, low, c, max(v, 0.0)))
    if len(rows) < 20:
        return None
    last_td = str(rows[-1][0]).strip()[:10]
    closes = [float(r[4]) for r in rows]
    vols = [float(r[5]) for r in rows]
    c2, v2 = merge_sw_index_with_rt_sw(closes, vols, ts_code=tc, free_last_date=last_td)
    if len(c2) == len(rows):
        r_last = list(rows[-1])
        r_last[4] = c2[-1]
        r_last[5] = v2[-1]
        rows[-1] = (
            str(r_last[0]),
            float(r_last[1]),
            float(r_last[2]),
            float(r_last[3]),
            float(r_last[4]),
            float(r_last[5]),
        )
        return rows
    snap = _rt_sw_k_latest_row(tc)
    rt_d = str(snap["trade_date"]).strip()[:10] if snap else last_td
    rt_c = float(snap["close"]) if snap else float(c2[-1])
    rt_v = float(snap["vol"]) if snap else float(v2[-1])
    rows.append((rt_d, rt_c, rt_c, rt_c, rt_c, max(rt_v, 0.0)))
    return rows


def n_day_close_return_pct(closes: list[float], n: int) -> float | None:
    """最近 n 根日 K 的涨跌幅（%），closes 升序。"""
    if n < 1 or len(closes) < n + 1:
        return None
    c_old = float(closes[-1 - n])
    c_new = float(closes[-1])
    if c_old <= 0 or c_new <= 0:
        return None
    return 100.0 * (c_new / c_old - 1.0)


def sw_l1_n_day_return_pct(ts_code_si: str, *, n: int = 5) -> float | None:
    """申万一级指数近 n 个交易日涨跌幅（%）；依赖 sw_daily / sw_index_daily。"""
    lmt = max(24, int(n) + 12)
    rows = fetch_sw_index_kline_rows(str(ts_code_si).strip().upper(), lmt)
    if not rows:
        return None
    closes = [float(r[4]) for r in rows]
    return n_day_close_return_pct(closes, int(n))


def sh_index_n_day_return_pct(*, n: int = 5, ts_code: str = "000001.SH") -> float | None:
    """指数近 n 日涨跌幅（%）；index_daily + rt_idx_k 与宏观/强度逻辑一致。"""
    tc = str(ts_code or "000001.SH").strip().upper()
    want = max(40, int(n) + 15)
    tu_hist = fetch_index_hist_index_daily(tc, limit=want)
    if not tu_hist:
        return None
    closes, vols, last_d = tu_hist
    closes, vols = merge_index_closes_with_rt_idx_k(
        list(closes), list(vols), ts_code=tc, free_last_date=last_d
    )
    if len(closes) < int(n) + 5:
        return None
    return n_day_close_return_pct(closes, int(n))


def fetch_kline_rows_unified(
    secid: str, lmt: int, ut: str | None = None
) -> list[tuple[str, float, float, float, float, float]] | None:
    s0 = str(secid).strip()
    su = s0.upper()
    if su.endswith(".SI") and su[:-3].isdigit():
        return fetch_sw_index_kline_rows(su, lmt)
    if s0.startswith("90.") or s0.startswith("92."):
        return None
    rows = fetch_stock_kline_rows_pro_bar(s0, lmt)
    if not rows:
        rows = try_fetch_daily_rows_for_secid(s0, lmt=lmt)
    if not rows:
        return None
    return merge_stock_rows_with_rt_k(s0, rows, ut=ut)


def _hs_cy_code_allowed_for_scanner(code: str) -> bool:
    c = str(code).strip().zfill(6)
    if len(c) != 6 or not c.isdigit():
        return False
    if c.startswith(("688", "689", "83", "87", "43", "92")):
        return False
    return c.startswith(("60", "000", "001", "002", "003", "300", "301"))


def _tushare_latest_open_trade_date(pro: Any) -> str | None:
    end_d = date.today().strftime("%Y%m%d")
    start_d = (date.today() - timedelta(days=40)).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_d, end_date=end_d, is_open="1")
    except Exception:
        return None
    if cal is None or getattr(cal, "empty", True):
        return None
    cal = cal.sort_values("cal_date")
    return str(cal.iloc[-1]["cal_date"]).strip()


def fetch_a_share_name_map_tushare() -> dict[str, str] | None:
    if not (_CFG.get("enabled") and _resolved_token()):
        return None
    pro = _get_pro()
    if pro is None:
        return None
    try:
        df = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name",
        )
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        tc = str(row.get("ts_code") or "").strip()
        if "." not in tc:
            continue
        sym, suf = tc.split(".", 1)
        suf_u = suf.strip().upper()
        if suf_u not in ("SH", "SZ", "BJ"):
            continue
        sym6 = "".join(ch for ch in sym if ch.isdigit()).zfill(6)
        if len(sym6) != 6 or not sym6.isdigit():
            continue
        name = str(row.get("name") or "").strip()
        if name:
            out[sym6] = name
    return out if out else None


def fetch_hs_cy_scanner_rows_tushare() -> list[dict[str, Any]] | None:
    if not (_CFG.get("enabled") and _resolved_token()):
        return None
    pro = _get_pro()
    if pro is None:
        return None
    td = _tushare_latest_open_trade_date(pro)
    if not td:
        return None
    try:
        df_sb = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name,industry",
        )
    except Exception:
        return None
    if df_sb is None or getattr(df_sb, "empty", True):
        return None
    try:
        _acquire_tushare_daily_slot()
        df_d = pro.daily(trade_date=td)
    except Exception:
        return None
    if df_d is None or getattr(df_d, "empty", True):
        return None
    try:
        _acquire_tushare_daily_slot()
        df_db = pro.daily_basic(trade_date=td, fields="ts_code,circ_mv")
    except Exception:
        df_db = None

    ts_col = df_sb["ts_code"].astype(str)
    df_sb = df_sb[ts_col.str.endswith(".SH") | ts_col.str.endswith(".SZ")].copy()
    df_sb["_sym"] = df_sb["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    df_sb = df_sb[df_sb["_sym"].map(_hs_cy_code_allowed_for_scanner)].copy()
    if df_sb.empty:
        return None

    m = df_sb.merge(df_d, on="ts_code", how="inner", suffixes=("", "_d"))
    if df_db is not None and not getattr(df_db, "empty", True):
        m = m.merge(df_db[["ts_code", "circ_mv"]], on="ts_code", how="left")
    else:
        m["circ_mv"] = None

    rows: list[dict[str, Any]] = []
    for _, r in m.iterrows():
        code = str(r.get("_sym") or "").strip().zfill(6)
        name = str(r.get("name") or "").strip()
        ind = str(r.get("industry") or "").strip()
        try:
            close = float(r.get("close") or 0.0)
        except (TypeError, ValueError):
            close = 0.0
        try:
            vol = float(r.get("vol") or 0.0)
        except (TypeError, ValueError):
            vol = 0.0
        try:
            amount_qian = float(r.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount_qian = 0.0
        cm = r.get("circ_mv")
        try:
            circ_mv_wan = float(cm) if cm is not None and str(cm) != "nan" else 0.0
        except (TypeError, ValueError):
            circ_mv_wan = 0.0
        fmv_yuan = max(0.0, circ_mv_wan) * 10000.0
        amt_yuan = max(0.0, amount_qian) * 1000.0
        f2 = int(round(close * 100.0)) if close > 0 else 0
        rows.append(
            {
                "f12": code,
                "f14": name,
                "f100": ind,
                "f2": f2,
                "f20": fmv_yuan,
                "f21": fmv_yuan,
                "f5": vol,
                "f6": amt_yuan,
            }
        )
    return rows if rows else None


def fetch_hs_cy_scanner_rows_from_cache(
    cache_path: Path,
    *,
    pro: Any,
) -> list[dict[str, Any]] | None:
    from stock_basic_cache import ensure_stock_basic_cache, load_stock_basic_cache

    if not (_CFG.get("enabled") and _resolved_token()):
        return None
    ensure_stock_basic_cache(cache_path, pro=pro, max_age_hours=168.0)
    blob = load_stock_basic_cache(cache_path)
    stocks = blob.get("stocks") or []
    if not stocks:
        return None
    td = _tushare_latest_open_trade_date(pro)
    if not td:
        return None
    try:
        _acquire_tushare_daily_slot()
        df_d = pro.daily(trade_date=td)
    except Exception:
        return None
    if df_d is None or getattr(df_d, "empty", True):
        return None
    try:
        _acquire_tushare_daily_slot()
        df_db = pro.daily_basic(trade_date=td, fields="ts_code,circ_mv")
    except Exception:
        df_db = None
    sb = pd.DataFrame(stocks)
    if "ts_code" not in sb.columns:
        return None
    ts_col = sb["ts_code"].astype(str)
    sb = sb[ts_col.str.endswith(".SH") | ts_col.str.endswith(".SZ")].copy()
    sb["_sym"] = sb["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    sb = sb[sb["_sym"].map(_hs_cy_code_allowed_for_scanner)].copy()
    if sb.empty:
        return None
    m = sb.merge(df_d, on="ts_code", how="inner", suffixes=("", "_d"))
    if df_db is not None and not getattr(df_db, "empty", True):
        m = m.merge(df_db[["ts_code", "circ_mv"]], on="ts_code", how="left")
    else:
        m["circ_mv"] = None

    rows: list[dict[str, Any]] = []
    for _, r in m.iterrows():
        code = str(r.get("_sym") or "").strip().zfill(6)
        name = str(r.get("name") or "").strip()
        ind = str(r.get("industry") or "").strip()
        try:
            close = float(r.get("close") or 0.0)
        except (TypeError, ValueError):
            close = 0.0
        try:
            vol = float(r.get("vol") or 0.0)
        except (TypeError, ValueError):
            vol = 0.0
        try:
            amount_qian = float(r.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount_qian = 0.0
        cm = r.get("circ_mv")
        try:
            circ_mv_wan = float(cm) if cm is not None and str(cm) != "nan" else 0.0
        except (TypeError, ValueError):
            circ_mv_wan = 0.0
        fmv_yuan = max(0.0, circ_mv_wan) * 10000.0
        amt_yuan = max(0.0, amount_qian) * 1000.0
        f2 = int(round(close * 100.0)) if close > 0 else 0
        rows.append(
            {
                "f12": code,
                "f14": name,
                "f100": ind,
                "f2": f2,
                "f20": fmv_yuan,
                "f21": fmv_yuan,
                "f5": vol,
                "f6": amt_yuan,
            }
        )
    return rows if rows else None


def try_fetch_daily_rows_for_secid(
    secid: str,
    *,
    lmt: int,
) -> list[tuple[str, float, float, float, float, float]] | None:
    """个股日 K 原始行 (trade_date, o,h,l,c,v) 升序；不支持板块 secid。"""
    ts_code = secid_to_ts_code(secid)
    if not ts_code:
        return None
    pro = _get_pro()
    if pro is None:
        return None
    want = max(40, int(lmt))
    start_s, end_s = _date_window_for_bars(want)
    try:
        _acquire_tushare_daily_slot()
        df = pro.daily(ts_code=ts_code, start_date=start_s, end_date=end_s)
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    tail = df.tail(want)
    rows: list[tuple[str, float, float, float, float, float]] = []
    for _, row in tail.iterrows():
        try:
            ds = _norm_trade_date(row.get("trade_date"))
            o = float(row.get("open") or 0.0)
            h = float(row.get("high") or 0.0)
            low = float(row.get("low") or 0.0)
            c = float(row.get("close") or 0.0)
            v = float(row.get("vol") or 0.0)
        except (TypeError, ValueError):
            continue
        rows.append((ds, o, h, low, c, max(v, 0.0)))
    if len(rows) < 20:
        return None
    return rows


def last_two_unadj_closes_on_or_before(
    secid: str, day_iso: str, *, lmt: int = 160
) -> tuple[float | None, float | None]:
    """Tushare pro.daily（不复权）中 trade_date≤day_iso 的最近两根收盘。

    与本地 daily_klines（pro_bar qfq）区分，用于持仓成本与「券商口径」收盘对比。
    失败返回 (None, None)。
    """
    rows = try_fetch_daily_rows_for_secid(str(secid).strip(), lmt=int(lmt))
    if not rows:
        return None, None
    day_s = str(day_iso).strip()[:10]
    elig = [r for r in rows if str(r[0]).strip()[:10] <= day_s]
    if not elig:
        return None, None
    last = elig[-1]
    prev = elig[-2] if len(elig) >= 2 else None
    try:
        c0 = float(last[4]) if last[4] is not None else None
    except (TypeError, ValueError):
        c0 = None
    if c0 is None or c0 <= 0:
        return None, None
    if prev is None:
        return c0, None
    try:
        c1 = float(prev[4]) if prev[4] is not None else None
    except (TypeError, ValueError):
        c1 = None
    if c1 is not None and c1 <= 0:
        c1 = None
    return c0, c1


def try_get_kline_dict_for_secid(
    secid: str,
    lmt: int,
    *,
    return_closes: bool,
    ut: str | None = None,
) -> dict[str, Any] | None:
    """个股 / 申万指数统一：pro_bar 或 sw_daily / sw_index_daily + 实时合并。"""
    rows = fetch_kline_rows_unified(secid, lmt, ut=ut)
    if not rows or len(rows) < 20:
        return None
    opens = [float(r[1]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]
    vols = [float(r[5]) for r in rows]
    last_td = str(rows[-1][0]).strip()[:10]
    from quote_eastmoney import kline_dict_from_ohlcv_series

    return kline_dict_from_ohlcv_series(
        opens,
        highs,
        lows,
        closes,
        vols,
        return_closes=return_closes,
        kline_data_source="tushare",
        kline_last_trade_date=last_td,
    )


def try_stock_minute_kline_summary_from_tushare(
    code: str,
    market: str,
    *,
    lmt: int = 256,
) -> dict[str, Any] | None:
    """当日 1 分钟 K 摘要（Tushare stk_mins）；非交易日或失败返回 None。"""
    pro = _get_pro()
    if pro is None:
        return None
    c = str(code).strip().zfill(6)
    m = str(market or "sh").strip().lower()
    if m in ("sh", "1", "sse"):
        secid = f"1.{c}"
    elif m in ("sz", "0", "szse"):
        secid = f"0.{c}"
    else:
        return None
    ts_code = secid_to_ts_code(secid)
    if not ts_code:
        return None
    today = date.today().strftime("%Y%m%d")
    try:
        df = pro.stk_mins(
            ts_code=ts_code,
            start_date=today,
            end_date=today,
            freq="1min",
        )
    except Exception:
        return None
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_time") if "trade_time" in df.columns else df
    tail = df.tail(max(32, int(lmt)))
    day_rows: list[tuple[Any, ...]] = []
    for _, row in tail.iterrows():
        try:
            ts_raw = row.get("trade_time")
            ds = str(ts_raw).strip()
            o = float(row.get("open") or 0.0)
            h = float(row.get("high") or 0.0)
            low = float(row.get("low") or 0.0)
            cl = float(row.get("close") or 0.0)
        except (TypeError, ValueError):
            continue
        day_rows.append((ds, o, h, low, cl))
    if not day_rows:
        return None
    highs = [r[2] for r in day_rows]
    lows = [r[3] for r in day_rows]
    last = day_rows[-1]
    trade_date = date.today().strftime("%Y-%m-%d")
    return {
        "klt": "1",
        "trade_date": trade_date,
        "bar_count": len(day_rows),
        "session_high": max(highs) if highs else None,
        "session_low": min(lows) if lows else None,
        "last_close": float(last[4]) if last else None,
        "last_bar_ts": str(last[0]) if last else None,
        "open_first": float(day_rows[0][1]) if day_rows else None,
    }


# 导入本模块：默认基址链 + 覆盖 DataApi.query（多域名重试）。
with _dataapi_bases_lock:
    _DATAAPI_BASE_CHAIN = _build_dataapi_base_chain(
        _resolve_tushare_dataapi_base(None), None
    )
_apply_tushare_dataapi_base(
    _DATAAPI_BASE_CHAIN[0] if _DATAAPI_BASE_CHAIN else _DEFAULT_TUSHARE_DATAAPI_BASE
)
_install_tushare_query_patch()
