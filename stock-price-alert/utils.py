"""全局温和 HTTP：降频 + 统一头 + 失败重试一次（东方财富等接口）。"""

from __future__ import annotations

import random
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    每次请求前随机等待 1～3 秒；verify=False；失败则再等 3 秒后重试一次。
    两次均失败返回 None（调用方可自行处理）。
    """
    try:
        time.sleep(random.uniform(1.0, 3.0))
        response = requests.get(
            url,
            params=params,
            headers=_headers(),
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
        return response
    except Exception:
        time.sleep(3.0)
        try:
            return requests.get(
                url,
                params=params,
                headers=_headers(),
                timeout=timeout,
                verify=False,
            )
        except Exception:
            return None
