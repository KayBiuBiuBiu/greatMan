"""A 股行情聚合：实时价多源回退 + 东方财富日 K（均线 / 箱体策略用）。"""

from __future__ import annotations

import copy
import re
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from utils import get_requests_verify, requests_get_with_health, safe_get, session_get_with_health

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

# 日 K 内存缓存（跨轮询复用，减轻东财压力）；TTL 由 configure_kline_performance 注入
_kline_lock = threading.Lock()
_kline_ram_cache: dict[tuple[str, str, int, bool], tuple[float, dict[str, Any]]] = {}
_kline_ttl_stock_sec: float = 900.0
_kline_ttl_bk_sec: float = 3600.0

# 本地 SQLite（kline_store），由 configure_kline_store_from_cfg 注入
_kline_local_store: dict[str, Any] = {
    "enabled": False,
    "db_path": "",
    "fresh_hours": 36.0,
}


def configure_kline_performance(
    stock_ttl_sec: float | None = None,
    bk_ttl_sec: float | None = None,
) -> None:
    """加载 config 后由 run_alert 调用；None 表示保持当前内存中的 TTL 默认值。"""
    global _kline_ttl_stock_sec, _kline_ttl_bk_sec
    with _kline_lock:
        if stock_ttl_sec is not None:
            _kline_ttl_stock_sec = max(0.0, float(stock_ttl_sec))
        if bk_ttl_sec is not None:
            _kline_ttl_bk_sec = max(0.0, float(bk_ttl_sec))


def clear_kline_ram_cache() -> None:
    with _kline_lock:
        _kline_ram_cache.clear()


def configure_kline_store_from_cfg(
    cfg: dict[str, Any] | None,
    *,
    root: Path | None = None,
) -> None:
    """启用后：在「同步新鲜度」窗口内优先从 SQLite 读日 K，减少东财 his 请求。"""
    global _kline_local_store
    raw_cfg = dict(cfg or {})
    k = raw_cfg.get("kline_store")
    if not isinstance(k, dict):
        _kline_local_store = {**_kline_local_store, "enabled": False}
        return
    rel = str(k.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if root is not None and not p.is_absolute():
        p = root / p
    _kline_local_store = {
        "enabled": bool(k.get("enabled")),
        "db_path": str(p.resolve()),
        "fresh_hours": float(k.get("fresh_hours_after_sync", 36) or 36),
        "use_indicator_last": bool(k.get("use_indicator_last")),
    }


def fetch_kline_rows_for_secid(
    secid: str,
    ut: str | None = None,
    *,
    lmt: int = 160,
    kline_bases: tuple[str, ...] | None = None,
) -> list[tuple[str, float, float, float, float, float]] | None:
    """东财日 K 原始行 (trade_date, o,h,l,c,v) 升序，供 sync_daily_klines 写入库。"""
    u = resolve_ut(ut or DEFAULT_UT)
    eff_lmt = max(40, int(lmt))
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": str(eff_lmt),
        "end": "20500101",
        "fields1": KLINE_FIELDS1,
        "fields2": KLINE_FIELDS2,
        "ut": u,
    }
    qs = urllib.parse.urlencode(params)
    bases = kline_bases or (
        KLINE_URL,
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "http://82.push2his.eastmoney.com/api/qt/stock/kline/get",
    )
    for base in bases:
        base_clean = base.split("?")[0] if "?" in base else base
        url = f"{base_clean}?{qs}"
        try:
            r = safe_get(url, timeout=12.0)
            if r is None:
                continue
            r.raise_for_status()
            j = r.json()
            klines = (j.get("data") or {}).get("klines") or []
            rows: list[tuple[str, float, float, float, float, float]] = []
            for line in klines:
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                try:
                    ds = str(parts[0]).strip()[:10]
                    o = float(parts[1])
                    c = float(parts[2])
                    h = float(parts[3])
                    low = float(parts[4])
                    v = float(parts[5]) if len(parts) > 5 else 0.0
                except (ValueError, IndexError):
                    continue
                rows.append((ds, o, h, low, c, max(v, 0.0)))
            if len(rows) >= 20:
                return rows
        except Exception:
            continue
    return None

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
    r = requests_get_with_health(
        SINA_URL.format(code=full),
        headers=headers,
        timeout=timeout,
        verify=get_requests_verify(),
    )
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
    r = requests_get_with_health(
        QQ_URL.format(code=full),
        timeout=timeout,
        verify=get_requests_verify(),
    )
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
    sess.verify = get_requests_verify()
    # 预热 Cookie，避免部分场景直接访问 quote 接口被拒绝
    session_get_with_health(sess, "https://xueqiu.com/", timeout=10)
    _XUEQIU_SESSION = sess
    return sess


def _fetch_xueqiu(code: str, market: str, timeout: float) -> dict[str, Any]:
    symbol = _to_xueqiu_code(code, market)
    sess = _xueqiu_session()
    r = session_get_with_health(
        sess, XUEQIU_URL.format(code=symbol), timeout=timeout
    )
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
    r = requests_get_with_health(
        BAIDU_URL.format(code=c),
        timeout=timeout,
        verify=get_requests_verify(),
    )
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
    r = requests_get_with_health(
        NETEASE_URL.format(code=ncode),
        timeout=timeout,
        verify=get_requests_verify(),
    )
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


def fetch_quote_metrics_bulk(
    items: list[tuple[str, str]],
    *,
    timeout: float = 12.0,
) -> dict[tuple[str, str], dict[str, Any]]:
    """批量现价（优先一次新浪接口）；失败或缺失时降级到单票多源。"""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for code, market in items:
        c = str(code).strip()
        m = str(market or "sh").strip().lower()
        if not c.isdigit() or len(c) != 6:
            continue
        k = (c, _normalize_market(c, m))
        if k in seen:
            continue
        seen.add(k)
        dedup.append(k)
    if not dedup:
        return out

    headers = {"Referer": "https://finance.sina.com.cn/"}
    chunk_n = 80
    sym_re = re.compile(r'^var hq_str_(?P<sym>[^=]+)="(?P<payload>.*)";$')
    sym_map: dict[str, tuple[str, str]] = {
        _to_sina_code(c, m): (c, m) for c, m in dedup
    }
    pending: set[tuple[str, str]] = set(dedup)

    for i in range(0, len(dedup), chunk_n):
        part = dedup[i : i + chunk_n]
        syms = [_to_sina_code(c, m) for c, m in part]
        try:
            r = requests_get_with_health(
                SINA_URL.format(code=",".join(syms)),
                headers=headers,
                timeout=timeout,
                verify=get_requests_verify(),
            )
            r.raise_for_status()
            r.encoding = "gbk"
            txt = r.text or ""
        except Exception:
            continue
        for ln in txt.splitlines():
            s = ln.strip()
            if not s:
                continue
            m0 = sym_re.match(s)
            if not m0:
                continue
            sym = m0.group("sym").strip()
            payload = m0.group("payload")
            cm = sym_map.get(sym)
            if cm is None:
                continue
            code, market = cm
            arr = payload.split(",")
            if len(arr) < 6:
                continue
            row = _build_price_row(
                code,
                market,
                name=arr[0],
                open_=arr[1],
                pre_close=arr[2],
                price=arr[3],
                high=arr[4],
                low=arr[5],
                source="sina_batch",
            )
            if float(row.get("price") or 0.0) <= 0:
                continue
            out[(code, market)] = {
                "code": row["code"],
                "name": row["name"],
                "price": row["price"],
                "change_pct": row["change_pct"],
                "amount_yuan": 0.0,
                "float_mv_yuan": 0.0,
                "total_mv_yuan": 0.0,
                "source": row.get("source"),
            }
            pending.discard((code, market))

    for code, market in sorted(pending):
        try:
            out[(code, market)] = fetch_quote_metrics(code, market, timeout=timeout)
        except Exception:
            continue
    return out


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


def kline_dict_from_ohlcv_series(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    vols: list[float],
    *,
    return_closes: bool,
    kline_data_source: str | None = None,
    kline_last_trade_date: str | None = None,
) -> dict[str, Any] | None:
    """由 OHLCV 序列构造与 `_parse_klines_payload` 一致的日 K 字典（供 SQLite 回放）。"""
    if (
        len(closes) < 20
        or len(opens) != len(closes)
        or len(highs) != len(closes)
        or len(lows) != len(closes)
        or len(vols) != len(closes)
    ):
        return None
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    last20 = closes[-20:]
    high20 = max(last20)
    low20 = min(last20)
    ma60: float | None = None
    if len(closes) >= 60:
        ma60 = sum(closes[-60:]) / 60.0
    out: dict[str, Any] = {
        "ma5": round(ma5, 3),
        "ma20": round(ma20, 3),
        "high20": round(high20, 3),
        "low20": round(low20, 3),
    }
    if ma60 is not None:
        out["ma60"] = round(ma60, 3)
    if return_closes:
        out["closes"] = list(closes)
        out["opens"] = list(opens)
        out["highs"] = list(highs)
        out["lows"] = list(lows)
        out["volumes"] = list(vols)
    if kline_data_source:
        out["kline_data_source"] = str(kline_data_source)
    if kline_last_trade_date:
        out["kline_last_trade_date"] = str(kline_last_trade_date)[:10]
    return out


def _parse_klines_payload(j: dict[str, Any], *, return_closes: bool) -> dict[str, Any] | None:
    data = j.get("data") or {}
    klines = data.get("klines") or []
    if len(klines) < 20:
        return None
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    vols: list[float] = []
    closes: list[float] = []
    last_trade_date: str | None = None
    for line in klines:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            o = float(parts[1])
            c = float(parts[2])
            h = float(parts[3])
            l = float(parts[4])
            v = float(parts[5]) if len(parts) > 5 else 0.0
        except (ValueError, IndexError):
            continue
        td = str(parts[0] or "").strip()[:10]
        if td:
            last_trade_date = td
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(max(v, 0.0))
    if len(closes) < 20:
        return None
    return kline_dict_from_ohlcv_series(
        opens,
        highs,
        lows,
        closes,
        vols,
        return_closes=return_closes,
        kline_data_source="network",
        kline_last_trade_date=last_trade_date,
    )


def get_kline_data_for_secid(
    secid: str,
    ut: str | None = None,
    *,
    lmt: int = 120,
    return_closes: bool = False,
    kline_bases: tuple[str, ...] | None = None,
    cache_ttl_sec: float | None = None,
) -> dict[str, Any] | None:
    """东财日 K 通用入口：secid 如 1.600711（个股）或 90.BK0474（行业板块指数）。"""
    u = resolve_ut(ut or DEFAULT_UT)
    eff_lmt = max(40, int(lmt))
    cache_key = (str(secid), u, eff_lmt, bool(return_closes))
    if cache_ttl_sec is not None:
        ttl = max(0.0, float(cache_ttl_sec))
    else:
        ttl = (
            _kline_ttl_bk_sec
            if str(secid).strip().startswith("90.")
            else _kline_ttl_stock_sec
        )
    now = time.time()
    if ttl > 0:
        with _kline_lock:
            hit = _kline_ram_cache.get(cache_key)
            if hit is not None:
                ts0, snap = hit
                if now - ts0 < ttl:
                    s2 = copy.deepcopy(snap)
                    if not str(s2.get("kline_data_source") or "").strip():
                        s2["kline_data_source"] = "ram_cache"
                    return s2

    loc = _kline_local_store
    if loc.get("enabled") and str(loc.get("db_path") or "").strip():
        try:
            from kline_store import (
                is_db_fresh,
                read_last_trade_date_for_secid,
                read_meta_value,
                read_ohlcv_lists,
            )

            dbp = Path(str(loc["db_path"]))
            if dbp.is_file() and is_db_fresh(dbp, float(loc.get("fresh_hours", 36))):
                ohlcv = read_ohlcv_lists(dbp, str(secid).strip(), lmt=eff_lmt)
                if ohlcv is not None:
                    last_dt = read_last_trade_date_for_secid(dbp, str(secid).strip())
                    out = kline_dict_from_ohlcv_series(
                        *ohlcv,
                        return_closes=return_closes,
                        kline_data_source="sqlite",
                        kline_last_trade_date=last_dt,
                    )
                    if out is not None:
                        sync_iso = read_meta_value(dbp, "last_full_sync_iso")
                        if sync_iso:
                            out["kline_db_last_sync_iso"] = sync_iso
                        if bool(loc.get("use_indicator_last")):
                            try:
                                from kline_indicators import (
                                    merge_indicator_last_into_kline,
                                    read_indicator_last,
                                )
                                from kline_store import open_store_connection

                                conn_i = open_store_connection(Path(str(loc["db_path"])))
                                try:
                                    snap = read_indicator_last(
                                        conn_i, str(secid).strip()
                                    )
                                    out = merge_indicator_last_into_kline(out, snap)
                                finally:
                                    conn_i.close()
                            except Exception:
                                pass
                        if ttl > 0:
                            with _kline_lock:
                                _kline_ram_cache[cache_key] = (
                                    time.time(),
                                    copy.deepcopy(out),
                                )
                        return out
        except Exception:
            pass

    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "lmt": str(eff_lmt),
        "end": "20500101",
        "fields1": KLINE_FIELDS1,
        "fields2": KLINE_FIELDS2,
        "ut": u,
    }
    qs = urllib.parse.urlencode(params)
    bases = kline_bases or (
        KLINE_URL,
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "http://82.push2his.eastmoney.com/api/qt/stock/kline/get",
    )
    for base in bases:
        base_clean = base.split("?")[0] if "?" in base else base
        url = f"{base_clean}?{qs}"
        try:
            r = safe_get(url, timeout=12.0)
            if r is None:
                continue
            r.raise_for_status()
            j = r.json()
            out = _parse_klines_payload(j, return_closes=return_closes)
            if out is not None:
                if ttl > 0:
                    with _kline_lock:
                        _kline_ram_cache[cache_key] = (time.time(), copy.deepcopy(out))
                return out
        except Exception:
            continue
    return None


def get_stock_kline_data(
    code: str,
    market: str = "sh",
    ut: str | None = None,
    *,
    lmt: int = 120,
    return_closes: bool = False,
    cache_ttl_sec: float | None = None,
) -> dict[str, Any] | None:
    """最近日 K，计算 MA5、MA20、20 日高/低；可选返回收盘价序列供回测。"""
    u = resolve_ut(ut or DEFAULT_UT)
    secid = secid_for(code, market)
    return get_kline_data_for_secid(
        secid, u, lmt=lmt, return_closes=return_closes, cache_ttl_sec=cache_ttl_sec
    )


def normalize_bk_code(raw: str) -> str:
    s = str(raw).strip().upper()
    if s.startswith("BK"):
        return s
    if s.isdigit():
        return f"BK{s}"
    return s if s else ""


def get_bk_kline_data(
    bk_code: str,
    ut: str | None = None,
    *,
    lmt: int = 120,
    return_closes: bool = True,
    cache_ttl_sec: float | None = None,
) -> dict[str, Any] | None:
    """行业板块指数日 K，secid=90.BKxxxx。"""
    bk = normalize_bk_code(bk_code)
    if not bk.startswith("BK") or len(bk) < 4:
        return None
    u = resolve_ut(ut or DEFAULT_UT)
    secid = f"90.{bk}"
    return get_kline_data_for_secid(
        secid, u, lmt=lmt, return_closes=return_closes, cache_ttl_sec=cache_ttl_sec
    )
