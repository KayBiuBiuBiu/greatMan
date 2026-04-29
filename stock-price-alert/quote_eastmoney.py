"""A 股行情聚合：实时价多源回退 + 东方财富日 K（均线 / 箱体策略用）。"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta
from typing import Any

import requests

from utils import safe_get

DEFAULT_UT = "fa5fd1943c7b386f172d6893dbfba10b"
QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

QUOTE_FIELDS = "f43,f57,f58,f170,f46"
QUOTE_METRIC_FIELDS = "f43,f57,f58,f170,f48,f117,f116"
KLINE_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
SINA_URL = "https://hq.sinajs.cn/list={code}"
QQ_URL = "https://qt.gtimg.cn/q={code}"
XUEQIU_URL = "https://stock.xueqiu.com/v5/stock/quote.json?symbol={code}"
BAIDU_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation?code={code}"
NETEASE_URL = "https://api.money.126.net/data/feed/{code},money.api"

_XUEQIU_SESSION: requests.Session | None = None
_AK_CACHE_TS: datetime | None = None
_AK_CACHE_ROWS: list[dict[str, Any]] = []
_AK_CACHE_TTL = timedelta(seconds=8)

def resolve_ut(ut: str | None) -> str:
    """配置里写 ea 时自动使用站内常用长 ut，减少接口异常。"""
    if ut is None or str(ut).strip() == "":
        return DEFAULT_UT
    u = str(ut).strip().lower()
    if u in ("ea", "e1"):
        return DEFAULT_UT
    return str(ut).strip()


def secid_for(code: str, market: str) -> str:
    c = str(code).strip()
    m = str(market).strip().lower()
    if m in ("sh", "1", "sse"):
        return f"1.{c}"
    if m in ("sz", "0", "szse"):
        return f"0.{c}"
    raise ValueError(f"未知 market={market!r}，请用 sh / sz")


def _normalize_market(code: str, market: str | None) -> str:
    m = str(market or "").strip().lower()
    if m in ("sh", "1", "sse"):
        return "sh"
    if m in ("sz", "0", "szse"):
        return "sz"
    c = str(code).strip()
    if c.startswith(("6", "9")):
        return "sh"
    return "sz"


def _to_sina_code(code: str, market: str) -> str:
    return f"{_normalize_market(code, market)}{str(code).strip()}"


def _to_qq_code(code: str, market: str) -> str:
    return f"{_normalize_market(code, market)}{str(code).strip()}"


def _to_xueqiu_code(code: str, market: str) -> str:
    return f"{_normalize_market(code, market).upper()}{str(code).strip()}"


def _to_163_code(code: str, market: str) -> str:
    c = str(code).strip()
    m = _normalize_market(c, market)
    return f"0{c}" if m == "sh" else f"1{c}"


def _to_float(v: Any, *, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _build_price_row(
    code: str,
    market: str,
    *,
    name: str = "",
    price: Any = 0.0,
    pre_close: Any = 0.0,
    open_: Any = 0.0,
    high: Any = 0.0,
    low: Any = 0.0,
    source: str = "",
) -> dict[str, Any]:
    p = _to_float(price)
    pc = _to_float(pre_close)
    chg = ((p - pc) / pc * 100.0) if pc > 0 else None
    return {
        "code": str(code).strip(),
        "name": str(name).strip() or str(code).strip(),
        "market": _normalize_market(code, market),
        "price": p,
        "pre_close": pc,
        "open": _to_float(open_),
        "high": _to_float(high),
        "low": _to_float(low),
        "change_pct": chg,
        "source": source,
    }


def _fetch_akshare(code: str, market: str, timeout: float) -> dict[str, Any]:
    _ = timeout
    global _AK_CACHE_TS, _AK_CACHE_ROWS
    now = datetime.now()
    if _AK_CACHE_TS is None or (now - _AK_CACHE_TS) > _AK_CACHE_TTL:
        import akshare as ak  # type: ignore[import-not-found]

        df = ak.stock_zh_a_spot_em()
        _AK_CACHE_ROWS = df.to_dict(orient="records")
        _AK_CACHE_TS = now
    code_s = str(code).strip()
    for row in _AK_CACHE_ROWS:
        if str(row.get("代码") or "").strip() != code_s:
            continue
        return _build_price_row(
            code,
            market,
            name=str(row.get("名称") or code_s),
            price=row.get("最新价"),
            pre_close=row.get("昨收"),
            open_=row.get("今开"),
            high=row.get("最高"),
            low=row.get("最低"),
            source="akshare",
        )
    raise ValueError("akshare 无该股票行")


def _fetch_sina(code: str, market: str, timeout: float) -> dict[str, Any]:
    full = _to_sina_code(code, market)
    headers = {"Referer": "https://finance.sina.com.cn/"}
    r = requests.get(SINA_URL.format(code=full), headers=headers, timeout=timeout)
    r.raise_for_status()
    r.encoding = "gbk"
    txt = r.text
    if '"' not in txt:
        raise ValueError("新浪返回格式异常")
    payload = txt.split('"', 2)[1]
    arr = payload.split(",")
    if len(arr) < 6:
        raise ValueError("新浪字段不足")
    return _build_price_row(
        code,
        market,
        name=arr[0],
        open_=arr[1],
        pre_close=arr[2],
        price=arr[3],
        high=arr[4],
        low=arr[5],
        source="sina",
    )


def _fetch_qq(code: str, market: str, timeout: float) -> dict[str, Any]:
    full = _to_qq_code(code, market)
    r = requests.get(QQ_URL.format(code=full), timeout=timeout)
    r.raise_for_status()
    r.encoding = "gbk"
    arr = r.text.split("~")
    if len(arr) < 35:
        raise ValueError("腾讯字段不足")
    return _build_price_row(
        code,
        market,
        name=arr[1],
        price=arr[3],
        pre_close=arr[4],
        open_=arr[5],
        high=arr[33],
        low=arr[34],
        source="qq",
    )


def _xueqiu_session() -> requests.Session:
    global _XUEQIU_SESSION
    if _XUEQIU_SESSION is not None:
        return _XUEQIU_SESSION
    sess = requests.Session()
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    sess.headers.update({"User-Agent": ua, "Referer": "https://xueqiu.com/"})
    # 预热 Cookie，避免部分场景直接访问 quote 接口被拒绝
    sess.get("https://xueqiu.com/", timeout=10)
    _XUEQIU_SESSION = sess
    return sess


def _fetch_xueqiu(code: str, market: str, timeout: float) -> dict[str, Any]:
    symbol = _to_xueqiu_code(code, market)
    sess = _xueqiu_session()
    r = sess.get(XUEQIU_URL.format(code=symbol), timeout=timeout)
    r.raise_for_status()
    j = r.json()
    q = (j.get("data") or {}).get("quote") or {}
    if not q:
        raise ValueError("雪球无 quote 数据")
    return _build_price_row(
        code,
        market,
        name=q.get("name") or symbol,
        price=q.get("current"),
        pre_close=q.get("last_close"),
        open_=q.get("open"),
        high=q.get("high"),
        low=q.get("low"),
        source="xueqiu",
    )


def _fetch_baidu(code: str, market: str, timeout: float) -> dict[str, Any]:
    c = str(code).strip()
    r = requests.get(BAIDU_URL.format(code=c), timeout=timeout)
    r.raise_for_status()
    j = r.json()
    lst = j.get("Result") or []
    if not lst:
        raise ValueError("百度无 Result 数据")
    d = lst[0]
    return _build_price_row(
        code,
        market,
        name=d.get("name") or c,
        price=d.get("price"),
        pre_close=d.get("preClose"),
        open_=d.get("open"),
        high=d.get("high"),
        low=d.get("low"),
        source="baidu",
    )


def _fetch_163(code: str, market: str, timeout: float) -> dict[str, Any]:
    ncode = _to_163_code(code, market)
    r = requests.get(NETEASE_URL.format(code=ncode), timeout=timeout)
    r.raise_for_status()
    txt = r.text.strip()
    if txt.startswith("_ntes_quote_callback(") and txt.endswith(");"):
        txt = txt[len("_ntes_quote_callback(") : -2]
    j = requests.models.complexjson.loads(txt)
    d = j.get(ncode) or {}
    if not d:
        raise ValueError("163 无股票数据")
    return _build_price_row(
        code,
        market,
        name=d.get("name") or code,
        price=d.get("price"),
        pre_close=d.get("yestclose") or d.get("prevClose"),
        open_=d.get("open"),
        high=d.get("high"),
        low=d.get("low"),
        source="163",
    )


def _fetch_price_multi_source(code: str, market: str, timeout: float) -> dict[str, Any]:
    errs: list[str] = []
    for source_name, fn in (
        ("akshare", _fetch_akshare),
        ("sina", _fetch_sina),
        ("qq", _fetch_qq),
        ("xueqiu", _fetch_xueqiu),
        ("baidu", _fetch_baidu),
        ("163", _fetch_163),
    ):
        try:
            row = fn(code, market, timeout)
            if row.get("price", 0.0) > 0:
                return row
            errs.append(f"{source_name}:price<=0")
        except Exception as e:
            errs.append(f"{source_name}:{e}")
    raise ValueError("多源行情均失败: " + " | ".join(errs))


def fetch_price(
    code: str,
    market: str,
    *,
    ut: str = DEFAULT_UT,
    timeout: float = 12.0,
    jitter: bool = True,
) -> dict[str, Any]:
    """返回 price（元）、change_pct（百分比数值，如 -3.96 表示 -3.96%）。"""
    _ = resolve_ut(ut)  # 兼容旧参数，不再依赖 ut 取实时价
    _ = jitter
    row = _fetch_price_multi_source(code, market, timeout)
    return {
        "code": row["code"],
        "name": row["name"],
        "price": row["price"],
        "change_pct": row["change_pct"],
        "pre_close": row["pre_close"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "source": row["source"],
    }


def fetch_quote_metrics(
    code: str,
    market: str,
    *,
    ut: str = DEFAULT_UT,
    timeout: float = 12.0,
    jitter: bool = True,
) -> dict[str, Any]:
    """现价 + 指标字段（多源实时价，成交额/市值暂置 0 保持兼容）。"""
    _ = resolve_ut(ut)
    _ = jitter
    q = fetch_price(code, market, ut=ut, timeout=timeout, jitter=jitter)
    return {
        "code": q["code"],
        "name": q["name"],
        "price": q["price"],
        "change_pct": q["change_pct"],
        "amount_yuan": 0.0,
        "float_mv_yuan": 0.0,
        "total_mv_yuan": 0.0,
        "source": q.get("source"),
    }


def get_stock_price(
    code: str,
    market: str = "sh",
    ut: str | None = None,
) -> tuple[float, float] | None:
    """
    兼容旧接口：(现价, 当日涨跌幅百分比)。
    涨跌幅与行情软件一致（约到小数点后两位）。
    """
    u = ut or DEFAULT_UT
    try:
        q = fetch_price(code, market, ut=u)
        pct = q["change_pct"]
        if pct is None:
            pct = 0.0
        return round(q["price"], 3), round(pct, 2)
    except Exception:
        return None


def get_stock_kline_data(
    code: str,
    market: str = "sh",
    ut: str | None = None,
    *,
    lmt: int = 120,
    return_closes: bool = False,
) -> dict[str, Any] | None:
    """最近日 K，计算 MA5、MA20、20 日高/低；可选返回收盘价序列供回测。"""
    u = resolve_ut(ut or DEFAULT_UT)
    secid = secid_for(code, market)
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": str(max(40, int(lmt))),
        "end": "20500101",
        "fields1": KLINE_FIELDS1,
        "fields2": KLINE_FIELDS2,
        "ut": u,
    }
    qs = urllib.parse.urlencode(params)
    url = f"{KLINE_URL}?{qs}"
    try:
        r = safe_get(url, timeout=12.0)
        if r is None:
            return None
        r.raise_for_status()
        j = r.json()
    except Exception:
        return None
    data = j.get("data") or {}
    klines = data.get("klines") or []
    if len(klines) < 20:
        return None
    closes: list[float] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            closes.append(float(parts[2]))
        except ValueError:
            continue
    if len(closes) < 20:
        return None
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    last20 = closes[-20:]
    high20 = max(last20)
    low20 = min(last20)
    out: dict[str, Any] = {
        "ma5": round(ma5, 3),
        "ma20": round(ma20, 3),
        "high20": round(high20, 3),
        "low20": round(low20, 3),
    }
    if return_closes:
        out["closes"] = closes
    return out
