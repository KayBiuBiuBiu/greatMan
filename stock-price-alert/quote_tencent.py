"""腾讯财经 qt.gtimg.cn 行情：解析 ~ 分隔文本。"""

from __future__ import annotations

from typing import Any

from utils import get_requests_verify, requests_get_with_health

QQ_URL = "https://qt.gtimg.cn/q={code}"


def parse_gtimg_tilde_line(text: str) -> dict[str, Any] | None:
    """
    单行响应：v_sh600000="名称~...~"; 取引号内 payload，按 ~ 切分。
    常见下标：1 名称, 3 现价, 4 昨收, 5 今开, 33 高, 34 低。
    """
    s = str(text or "").strip()
    if '="' not in s or not s.endswith('";'):
        return None
    try:
        inner = s.split('="', 1)[1]
        inner = inner.rstrip('";')
    except IndexError:
        return None
    arr = inner.split("~")
    if len(arr) < 35:
        return None
    return {
        "name": str(arr[1] or "").strip(),
        "price": arr[3],
        "pre_close": arr[4],
        "open": arr[5],
        "high": arr[33] if len(arr) > 33 else "",
        "low": arr[34] if len(arr) > 34 else "",
    }


def fetch_quote_row_gtimg(code: str, market: str, *, timeout: float = 12.0) -> dict[str, Any]:
    """返回与 quote_eastmoney._build_price_row 兼容的字段所需原始数值（由调用方组装）。"""
    m = str(market or "sh").strip().lower()
    c = str(code).strip().zfill(6)
    prefix = "sh" if m in ("sh", "1", "sse") else "sz"
    full = f"{prefix}{c}"
    r = requests_get_with_health(
        QQ_URL.format(code=full),
        timeout=timeout,
        verify=get_requests_verify(),
    )
    r.raise_for_status()
    r.encoding = "gbk"
    parsed = parse_gtimg_tilde_line(r.text)
    if not parsed:
        raise ValueError("腾讯返回无法解析")
    return parsed
