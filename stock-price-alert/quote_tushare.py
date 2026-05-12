"""Tushare Pro：指数 index_daily + rt_idx_k；个股 pro_bar(qfq)/daily + rt_k；申万 sw_daily（回退 sw_index_daily）+ rt_sw_idx_k。"""

from __future__ import annotations

# PyPI「tushare」包内 DataApi 仍默认 http://api.waditu.com/dataapi；部分网络无法解析 api.waditu.com。
# 官方服务与 https://api.tushare.pro/dataapi/{api_name} 兼容旧版 POST 形态，故在 configure 时改写基址。
_DEFAULT_TUSHARE_DATAAPI_BASE = "https://api.tushare.pro/dataapi"
_LEGACY_WADITU_DATAAPI_BASE = "http://api.waditu.com/dataapi"

import errno
import os
import json
import socket
import threading
import time
from collections import deque
from datetime import date, timedelta
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
    "stock_basic_cache_path": "data/stock_basic_cache.json",
    "stock_to_sw_path": "data/stock_to_sw.json",
    # Tushare 文档：daily 类接口 500 次/分钟；pro_bar 等计入同类额度
    "daily_max_per_minute": 500,
}
_PRO: Any = None

_DEFAULT_DAILY_MAX_PER_MIN = 500
_daily_rate_lock = threading.Lock()
_daily_rate_mono: deque[float] = deque()
# configure_tushare_from_sources 会被 load_df 等高频路径反复调用；仅在配置实质变化时重置 pro / 限流窗口
_LAST_TUSHARE_CONFIGURE_FG: tuple[Any, ...] | None = None

# DataApi.query 补丁：多基址 + 连接/DNS 抖动时重试；成功后将该基址前置。
_DATAAPI_BASE_CHAIN: list[str] = []
_dataapi_bases_lock = threading.Lock()
_TUSHARE_QUERY_PATCH_INSTALLED = False


def _reset_daily_rate_window() -> None:
    with _daily_rate_lock:
        _daily_rate_mono.clear()


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
    add(_LEGACY_WADITU_DATAAPI_BASE)
    return chain


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
                params.setdefault("ts_type_name", url_base)
                req_params = {
                    "api_name": api_name,
                    "token": token,
                    "params": params,
                    "fields": fields,
                }
                post_url = f"{url_base}/{api_name}"
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
        _CFG["stock_basic_cache_path"] = "data/stock_basic_cache.json"
        _CFG["stock_to_sw_path"] = "data/stock_to_sw.json"
        _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
    else:
        t = sources.get("tushare")
        if not isinstance(t, dict):
            _CFG["enabled"] = False
            _CFG["token"] = ""
            _CFG["sh_index_free_fallback"] = False
            _CFG["stock_rt_k_enabled"] = True
            _CFG["stock_rt_k_fallback"] = False
            _CFG["sw_enabled"] = True
            _CFG["stock_basic_cache_path"] = "data/stock_basic_cache.json"
            _CFG["stock_to_sw_path"] = "data/stock_to_sw.json"
            _CFG["daily_max_per_minute"] = _DEFAULT_DAILY_MAX_PER_MIN
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

    tok_eff = _resolved_token()
    try:
        dm = int(_CFG.get("daily_max_per_minute") or 0)
    except (TypeError, ValueError):
        dm = _DEFAULT_DAILY_MAX_PER_MIN
    dataapi_base = _resolve_tushare_dataapi_base(sources if isinstance(sources, dict) else None)
    with _dataapi_bases_lock:
        _DATAAPI_BASE_CHAIN = _build_dataapi_base_chain(
            dataapi_base, sources if isinstance(sources, dict) else None
        )
        chain_fg = tuple(_DATAAPI_BASE_CHAIN)
    _apply_tushare_dataapi_base(_DATAAPI_BASE_CHAIN[0] if _DATAAPI_BASE_CHAIN else dataapi_base)
    fg: tuple[Any, ...] = (bool(_CFG.get("enabled")), tok_eff, dm, chain_fg)

    if fg != prev_fg:
        _PRO = None
        _reset_daily_rate_window()
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


def _rt_sw_idx_k_latest_row(ts_code: str) -> dict[str, Any] | None:
    pro = _get_pro()
    if pro is None:
        return None
    try:
        df = pro.rt_sw_idx_k(ts_code=str(ts_code).strip())
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
    snap = _rt_sw_idx_k_latest_row(ts_code)
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
    for api in ("sw_daily", "sw_index_daily"):
        try:
            fn = getattr(pro, api)
            df = fn(ts_code=tc, start_date=start_s, end_date=end_s)
        except Exception:
            continue
        if df is not None and not getattr(df, "empty", True):
            return df
    return None


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
    want = max(40, int(lmt))
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
    snap = _rt_sw_idx_k_latest_row(tc)
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
