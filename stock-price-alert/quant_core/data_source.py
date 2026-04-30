from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import requests

from quote_eastmoney import get_stock_kline_data
from utils import get_requests_verify, requests_get_with_health, session_get_with_health

SINA_URL = "https://hq.sinajs.cn/list={code}"
QQ_URL = "https://qt.gtimg.cn/q={code}"
XUEQIU_URL = "https://stock.xueqiu.com/v5/stock/quote.json?symbol={code}"
BAIDU_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation?code={code}"
NETEASE_URL = "https://api.money.126.net/data/feed/{code},money.api"


@dataclass
class MarketQuote:
    code: str
    market: str
    name: str
    price: float
    pre_close: float
    open: float
    high: float
    low: float
    change_pct: float | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _normalize_market(code: str, market: str | None) -> str:
    m = str(market or "").strip().lower()
    if m in ("sh", "1", "sse"):
        return "sh"
    if m in ("sz", "0", "szse"):
        return "sz"
    return "sh" if str(code).strip().startswith(("6", "9")) else "sz"


def _to_163_code(code: str, market: str) -> str:
    return ("0" if _normalize_market(code, market) == "sh" else "1") + str(code).strip()


class QuoteDataSource:
    """Realtime quote with fallback chain: akshare -> sina -> qq -> xueqiu -> baidu -> 163."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
    ) -> None:
        self.timeout = timeout
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._xueqiu = requests.Session()
        self._xueqiu.verify = get_requests_verify()
        self._xueqiu.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://xueqiu.com/",
            }
        )
        self._ak_cache_ts: datetime | None = None
        self._ak_cache_rows: list[dict[str, Any]] = []
        self._ak_cache_ttl = timedelta(seconds=8)

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _build_quote(
        self,
        code: str,
        market: str,
        *,
        name: str,
        price: Any,
        pre_close: Any,
        open_price: Any,
        high: Any,
        low: Any,
        source: str,
    ) -> MarketQuote:
        p = _to_float(price)
        pc = _to_float(pre_close)
        chg = ((p - pc) / pc * 100.0) if pc > 0 else None
        return MarketQuote(
            code=str(code).strip(),
            market=_normalize_market(code, market),
            name=str(name).strip() or str(code).strip(),
            price=p,
            pre_close=pc,
            open=_to_float(open_price),
            high=_to_float(high),
            low=_to_float(low),
            change_pct=chg,
            source=source,
        )

    def _quote_akshare(self, code: str, market: str) -> MarketQuote:
        now = datetime.now()
        if self._ak_cache_ts is None or (now - self._ak_cache_ts) > self._ak_cache_ttl:
            self._sleep()
            import akshare as ak  # type: ignore[import-not-found]

            df = ak.stock_zh_a_spot_em()
            self._ak_cache_rows = df.to_dict(orient="records")
            self._ak_cache_ts = now
        code_s = str(code).strip()
        for row in self._ak_cache_rows:
            if str(row.get("代码") or "").strip() != code_s:
                continue
            return self._build_quote(
                code,
                market,
                name=str(row.get("名称") or code),
                price=row.get("最新价"),
                pre_close=row.get("昨收"),
                open_price=row.get("今开"),
                high=row.get("最高"),
                low=row.get("最低"),
                source="akshare",
            )
        raise ValueError("akshare row not found")

    def _quote_sina(self, code: str, market: str) -> MarketQuote:
        self._sleep()
        full = f"{_normalize_market(code, market)}{str(code).strip()}"
        r = requests_get_with_health(
            SINA_URL.format(code=full),
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=self.timeout,
            verify=get_requests_verify(),
        )
        r.raise_for_status()
        r.encoding = "gbk"
        payload = r.text.split('"')[1]
        arr = payload.split(",")
        if len(arr) < 6:
            raise ValueError("sina fields missing")
        return self._build_quote(
            code,
            market,
            name=arr[0],
            open_price=arr[1],
            pre_close=arr[2],
            price=arr[3],
            high=arr[4],
            low=arr[5],
            source="sina",
        )

    def _quote_qq(self, code: str, market: str) -> MarketQuote:
        self._sleep()
        full = f"{_normalize_market(code, market)}{str(code).strip()}"
        r = requests_get_with_health(
            QQ_URL.format(code=full),
            timeout=self.timeout,
            verify=get_requests_verify(),
        )
        r.raise_for_status()
        r.encoding = "gbk"
        arr = r.text.split("~")
        if len(arr) < 35:
            raise ValueError("qq fields missing")
        return self._build_quote(
            code,
            market,
            name=arr[1],
            price=arr[3],
            pre_close=arr[4],
            open_price=arr[5],
            high=arr[33],
            low=arr[34],
            source="qq",
        )

    def _quote_xueqiu(self, code: str, market: str) -> MarketQuote:
        self._sleep()
        symbol = f"{_normalize_market(code, market).upper()}{str(code).strip()}"
        session_get_with_health(self._xueqiu, "https://xueqiu.com/", timeout=self.timeout)
        r = session_get_with_health(
            self._xueqiu, XUEQIU_URL.format(code=symbol), timeout=self.timeout
        )
        r.raise_for_status()
        q = (r.json().get("data") or {}).get("quote") or {}
        if not q:
            raise ValueError("xueqiu quote empty")
        return self._build_quote(
            code,
            market,
            name=q.get("name") or symbol,
            price=q.get("current"),
            pre_close=q.get("last_close"),
            open_price=q.get("open"),
            high=q.get("high"),
            low=q.get("low"),
            source="xueqiu",
        )

    def _quote_baidu(self, code: str, market: str) -> MarketQuote:
        self._sleep()
        c = str(code).strip()
        r = requests_get_with_health(
            BAIDU_URL.format(code=c),
            timeout=self.timeout,
            verify=get_requests_verify(),
        )
        r.raise_for_status()
        lst = r.json().get("Result") or []
        if not lst:
            raise ValueError("baidu result empty")
        d = lst[0]
        return self._build_quote(
            code,
            market,
            name=d.get("name") or c,
            price=d.get("price"),
            pre_close=d.get("preClose"),
            open_price=d.get("open"),
            high=d.get("high"),
            low=d.get("low"),
            source="baidu",
        )

    def _quote_163(self, code: str, market: str) -> MarketQuote:
        self._sleep()
        ncode = _to_163_code(code, market)
        r = requests_get_with_health(
            NETEASE_URL.format(code=ncode),
            timeout=self.timeout,
            verify=get_requests_verify(),
        )
        r.raise_for_status()
        txt = r.text.strip()
        if txt.startswith("_ntes_quote_callback(") and txt.endswith(");"):
            txt = txt[len("_ntes_quote_callback(") : -2]
        d = requests.models.complexjson.loads(txt).get(ncode) or {}
        if not d:
            raise ValueError("163 quote empty")
        return self._build_quote(
            code,
            market,
            name=d.get("name") or code,
            price=d.get("price"),
            pre_close=d.get("yestclose") or d.get("prevClose"),
            open_price=d.get("open"),
            high=d.get("high"),
            low=d.get("low"),
            source="163",
        )

    def get_quote(self, code: str, market: str) -> MarketQuote:
        errors: list[str] = []
        for source, fn in (
            ("akshare", self._quote_akshare),
            ("sina", self._quote_sina),
            ("qq", self._quote_qq),
            ("xueqiu", self._quote_xueqiu),
            ("baidu", self._quote_baidu),
            ("163", self._quote_163),
        ):
            try:
                q = fn(code, market)
                if q.price > 0:
                    return q
                errors.append(f"{source}:price<=0")
            except Exception as e:
                errors.append(f"{source}:{e}")
        raise RuntimeError("all quote sources failed: " + " | ".join(errors))

    def get_kline_snapshot(
        self,
        code: str,
        market: str,
        *,
        lmt: int = 160,
        with_closes: bool = True,
    ) -> dict[str, Any] | None:
        return get_stock_kline_data(code, market, lmt=lmt, return_closes=with_closes)

