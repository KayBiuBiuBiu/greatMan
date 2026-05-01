"""全局温和 HTTP：降频 + 统一头 + 失败重试一次（东方财富等接口）。"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 由 run_alert 在加载 config 后调用；True 时校验证书（内网/生产常用）
_ssl_verify: bool = False
_ssl_ca_bundle: str | None = None

# P1-9：任意 safe_get 调用之间的最小间隔（秒），串行化全局限流
_pacing_lock = threading.Lock()
_pacing_min_interval: float = 0.0
_pacing_last_release: float = 0.0

# safe_get 随机抖动（秒）；由 configure_safe_get_jitter 覆盖
_jitter_min_sec: float = 1.0
_jitter_max_sec: float = 3.0

# 按 hostname 的令牌桶（请求/秒）；0 表示关闭
_domain_bucket_rps: float = 0.0
_domain_bucket_hosts: frozenset[str] | None = None  # None = 所有主机
_domain_bucket_lock = threading.Lock()
_domain_bucket_next_ok: dict[str, float] = {}

# 线程本地 Session（keep-alive，减少 TLS 握手）
_tls = threading.local()


def configure_safe_get_jitter(min_sec: float | None, max_sec: float | None) -> None:
    """performance.safe_get_jitter_sec_min / max；max<=0 关闭抖动。"""
    global _jitter_min_sec, _jitter_max_sec
    lo = 0.0 if min_sec is None else float(min_sec)
    hi = 0.0 if max_sec is None else float(max_sec)
    if hi <= 0:
        _jitter_min_sec = 0.0
        _jitter_max_sec = 0.0
        return
    lo = max(0.0, lo)
    hi = max(lo, hi)
    _jitter_min_sec = lo
    _jitter_max_sec = hi


def configure_http_domain_token_bucket(
    requests_per_sec: float | None,
    only_hosts: list[str] | str | None = None,
) -> None:
    """
    performance.http_domain_bucket_rps：每个 hostname 独立令牌桶（近似均速）。
    performance.http_domain_bucket_hosts：仅对这些主机限流（小写 netloc），空则全部。
    """
    global _domain_bucket_rps, _domain_bucket_hosts
    rps = 0.0 if requests_per_sec is None else float(requests_per_sec)
    if rps <= 0:
        _domain_bucket_rps = 0.0
        _domain_bucket_hosts = None
        return
    _domain_bucket_rps = rps
    if only_hosts is None:
        _domain_bucket_hosts = None
        return
    if isinstance(only_hosts, str):
        raw = [only_hosts]
    else:
        raw = list(only_hosts)
    hs = {str(h).strip().lower() for h in raw if str(h).strip()}
    _domain_bucket_hosts = frozenset(hs) if hs else None


def _domain_bucket_wait(url: str) -> None:
    if _domain_bucket_rps <= 0:
        return
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        return
    if not host:
        return
    if _domain_bucket_hosts is not None and host not in _domain_bucket_hosts:
        return
    interval = 1.0 / _domain_bucket_rps
    with _domain_bucket_lock:
        now = time.monotonic()
        t_ready = _domain_bucket_next_ok.get(host, now)
        if t_ready > now:
            time.sleep(t_ready - now)
            now = time.monotonic()
        _domain_bucket_next_ok[host] = now + interval


def _thread_session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is not None:
        return s
    s = requests.Session()
    h = _headers()
    h.pop("Connection", None)
    s.headers.update(h)
    s.verify = get_requests_verify()
    _tls.session = s
    return s


def configure_request_pacing(min_interval_sec: float | None) -> None:
    """performance.request_min_interval_sec；0 或未配置则关闭。"""
    global _pacing_min_interval
    if min_interval_sec is None:
        _pacing_min_interval = 0.0
        return
    _pacing_min_interval = max(0.0, float(min_interval_sec))


def _pacing_wait_turn() -> None:
    if _pacing_min_interval <= 0:
        return
    with _pacing_lock:
        now = time.time()
        wait = _pacing_last_release + _pacing_min_interval - now
        if wait > 0:
            time.sleep(wait)


def _pacing_mark_done() -> None:
    global _pacing_last_release
    if _pacing_min_interval <= 0:
        return
    with _pacing_lock:
        _pacing_last_release = time.time()


def configure_ssl_verify(value: bool | str | None) -> None:
    """仅更新 ssl_verify 布尔语义；完整配置请用 configure_ssl_from_sources。"""
    global _ssl_verify
    if value is None:
        return
    if isinstance(value, bool):
        _ssl_verify = value
        return
    s = str(value).strip().lower()
    _ssl_verify = s in ("1", "true", "yes", "on")


def configure_ssl_from_sources(sources: dict[str, Any] | None) -> None:
    """
    sources.ssl_verify：证书校验开关。
    sources.ssl_ca_bundle：可选 PEM 路径；存在且为文件时，requests 使用该 CA 包（常用于内网根证书）。
    """
    global _ssl_ca_bundle
    src = sources or {}
    configure_ssl_verify(src.get("ssl_verify"))
    raw = str(src.get("ssl_ca_bundle") or "").strip()
    _ssl_ca_bundle = raw or None


def get_ssl_verify() -> bool:
    return _ssl_verify


def get_requests_verify() -> bool | str:
    """传给 requests 的 verify：优先自定义 CA 文件，否则为 ssl_verify 布尔值。"""
    if _ssl_ca_bundle:
        p = Path(_ssl_ca_bundle).expanduser()
        if p.is_file():
            return str(p)
    return _ssl_verify


SAFE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.8",
    "Connection": "close",
}

# 东方财富 JSON 接口常用补充（避免仅文本 Accept 被拒）
_EM_EXTRA = {
    "Referer": "https://quote.eastmoney.com/",
    "Origin": "https://quote.eastmoney.com",
    "Accept": "application/json,text/plain,*/*",
}


def _headers() -> dict[str, str]:
    h = dict(SAFE_HEADERS)
    h.update(_EM_EXTRA)
    return h


def safe_get(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 20,
) -> requests.Response | None:
    """
    请求前：可选 pacing / 域名令牌桶 / configure_safe_get_jitter 配置的抖动（max<=0 则无抖动）；
    data_health 失败退避；verify 由 configure_ssl_from_sources 控制。
    首次失败则固定 sleep 3s 后重试一次；两次均失败返回 None。
    """
    from data_health import extra_backoff_sleep_sec, record_http_result

    v = get_requests_verify()
    extra = extra_backoff_sleep_sec(url)
    if extra > 0:
        time.sleep(extra)

    def _one_get() -> requests.Response | None:
        try:
            _pacing_wait_turn()
            _domain_bucket_wait(url)
            if _jitter_max_sec > 0:
                time.sleep(random.uniform(_jitter_min_sec, _jitter_max_sec))
            sess = _thread_session()
            if sess.verify != v:
                sess.verify = v
            response = sess.get(
                url,
                params=params,
                timeout=timeout,
                allow_redirects=True,
            )
            ok = response is not None and response.status_code == 200
            record_http_result(
                url,
                ok=ok,
                status_code=getattr(response, "status_code", None),
            )
            return response
        except Exception:
            record_http_result(url, ok=False, status_code=None)
            return None
        finally:
            _pacing_mark_done()

    r = _one_get()
    if r is not None:
        return r
    time.sleep(3.0)
    return _one_get()


def requests_get_with_health(url: str, **kwargs: Any) -> requests.Response:
    """直连 requests.get，写入 data_health（无 safe_get 的随机等待与重试）。"""
    from data_health import record_http_result

    try:
        r = requests.get(url, **kwargs)
        ok = r.status_code == 200
        record_http_result(str(r.url), ok=ok, status_code=r.status_code)
        return r
    except Exception:
        record_http_result(url, ok=False, status_code=None)
        raise


def session_get_with_health(sess: requests.Session, url: str, **kwargs: Any) -> requests.Response:
    """Session.get，写入 data_health。"""
    from data_health import record_http_result

    try:
        r = sess.get(url, **kwargs)
        ok = r.status_code == 200
        record_http_result(str(r.url), ok=ok, status_code=r.status_code)
        return r
    except Exception:
        record_http_result(url, ok=False, status_code=None)
        raise
