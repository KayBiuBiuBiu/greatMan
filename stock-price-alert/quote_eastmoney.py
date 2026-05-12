"""A 股行情：新浪 / 腾讯 / 雪球等多源现价；日 K 由 Tushare（quote_tushare）与本地 SQLite 提供。"""

from __future__ import annotations

import copy
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from utils import (
    apply_proxies_to_session,
    get_requests_verify,
    requests_get_with_health,
    session_get_with_health,
)

DEFAULT_UT = "fa5fd1943c7b386f172d6893dbfba10b"
SINA_URL = "https://hq.sinajs.cn/list={code}"
QQ_URL = "https://qt.gtimg.cn/q={code}"
XUEQIU_URL = "https://stock.xueqiu.com/v5/stock/quote.json?symbol={code}"
BAIDU_URL = "https://finance.pae.baidu.com/selfselect/getstockquotation?code={code}"
NETEASE_URL = "https://api.money.126.net/data/feed/{code},money.api"


_XUEQIU_SESSION: requests.Session | None = None
_AK_CACHE_TS: datetime | None = None
_AK_CACHE_ROWS: list[dict[str, Any]] = []
_AK_CACHE_TTL = timedelta(seconds=8)

# 现价：sources.quote.live_sources，不含 eastmoney
_QUOTE_LIVE_ORDER: tuple[str, ...] | None = None

# 日 K 内存缓存；TTL 由 configure_kline_performance 注入
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


def configure_quote_live_from_cfg(cfg: dict[str, Any] | None) -> None:
    """
    sources.quote.live_sources：按序尝试 sina / qq / xueqiu / akshare 等；忽略 eastmoney。
    新浪批量预取：仅当有效顺序首项为 sina 时启用。
    """
    global _QUOTE_LIVE_ORDER
    raw = cfg or {}
    src = raw.get("sources") if isinstance(raw.get("sources"), dict) else {}
    q = src.get("quote") if isinstance(src.get("quote"), dict) else {}
    order_raw = q.get("live_sources")
    if isinstance(order_raw, list) and order_raw:
        names: list[str] = []
        for x in order_raw:
            s = str(x).strip().lower()
            if s and s != "eastmoney":
                names.append(s)
        if names:
            _QUOTE_LIVE_ORDER = tuple(names)
            return
    _QUOTE_LIVE_ORDER = None


def configure_kline_store_from_cfg(
    cfg: dict[str, Any] | None,
    *,
    root: Path | None = None,
) -> None:
    """启用后：在「同步新鲜度」窗口内优先从 SQLite 读日 K。"""
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


_min1_ram_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_min1_ram_lock = threading.Lock()


def get_stock_minute_kline_summary_today(
    code: str,
    market: str,
    ut: str | None = None,
    *,
    lmt: int = 256,
    cache_ttl_sec: float = 45.0,
) -> dict[str, Any] | None:
    """当日 1 分钟 K：Tushare stk_mins（需积分权限）；失败返回 None。"""
    _ = ut
    c = str(code).strip()
    m = _normalize_market(c, market)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = (c, m, today)
    ttl = max(0.0, float(cache_ttl_sec))
    now = time.time()
    if ttl > 0:
        with _min1_ram_lock:
            hit = _min1_ram_cache.get(cache_key)
            if hit is not None:
                ts0, snap = hit
                if now - ts0 < ttl:
                    return copy.deepcopy(snap)
    try:
        from quote_tushare import try_stock_minute_kline_summary_from_tushare

        out = try_stock_minute_kline_summary_from_tushare(c, m, lmt=lmt)
    except Exception:
        out = None
    if out and ttl > 0:
        with _min1_ram_lock:
            _min1_ram_cache[cache_key] = (now, copy.deepcopy(out))
    return out


def fetch_kline_rows_for_secid(
    secid: str,
    ut: str | None = None,
    *,
    lmt: int = 160,
    kline_bases: tuple[str, ...] | None = None,
    max_fetch_rounds: int | None = None,
) -> list[tuple[str, float, float, float, float, float]] | None:
    """日 K 原始行：Tushare pro_bar / sw_daily（申万）/ daily + 实时合并。"""
    _ = kline_bases
    _ = max_fetch_rounds
    from quote_tushare import fetch_kline_rows_unified

    u = resolve_ut(ut or DEFAULT_UT)
    return fetch_kline_rows_unified(str(secid).strip(), int(lmt), ut=u)


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
    from quote_tencent import fetch_quote_row_gtimg

    p = fetch_quote_row_gtimg(code, market, timeout=timeout)
    return _build_price_row(
        code,
        market,
        name=p.get("name"),
        price=p.get("price"),
        pre_close=p.get("pre_close"),
        open_=p.get("open"),
        high=p.get("high"),
        low=p.get("low"),
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
    apply_proxies_to_session(sess)
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


_DEFAULT_QUOTE_LIVE_ORDER = (
    "sina",
    "qq",
    "xueqiu",
    "akshare",
    "baidu",
    "163",
)

_LIVE_FETCHERS: dict[str, Any] = {
    "akshare": _fetch_akshare,
    "sina": _fetch_sina,
    "qq": _fetch_qq,
    "xueqiu": _fetch_xueqiu,
    "baidu": _fetch_baidu,
    "163": _fetch_163,
}


def _effective_quote_live_order() -> tuple[str, ...]:
    return _QUOTE_LIVE_ORDER or _DEFAULT_QUOTE_LIVE_ORDER


def _fetch_price_multi_source(
    code: str, market: str, timeout: float, *, ut: str = DEFAULT_UT
) -> dict[str, Any]:
    errs: list[str] = []
    order = _effective_quote_live_order()
    u = resolve_ut(ut)
    for source_name in order:
        try:
            if source_name == "eastmoney":
                errs.append("eastmoney:removed")
                continue
            fn = _LIVE_FETCHERS.get(source_name)
            if fn is None:
                errs.append(f"{source_name}:unknown_source")
                continue
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
    _ = jitter
    row = _fetch_price_multi_source(code, market, timeout, ut=ut)
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
    ut: str = DEFAULT_UT,
) -> dict[tuple[str, str], dict[str, Any]]:
    """批量现价：仅当 live 优先级首项为 sina 时走 hq.sinajs 批量，否则直接按单票多源顺序拉取。"""
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

    pending: set[tuple[str, str]] = set(dedup)
    eff_order = _effective_quote_live_order()
    use_sina_bulk = bool(eff_order) and eff_order[0] == "sina"
    if use_sina_bulk:
        headers = {"Referer": "https://finance.sina.com.cn/"}
        chunk_n = 80
        sym_re = re.compile(r'^var hq_str_(?P<sym>[^=]+)="(?P<payload>.*)";$')
        sym_map: dict[str, tuple[str, str]] = {
            _to_sina_code(c, m): (c, m) for c, m in dedup
        }

    if use_sina_bulk:
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
            out[(code, market)] = fetch_quote_metrics(
                code, market, timeout=timeout, ut=ut
            )
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
        "pre_close": q.get("pre_close"),
        "open": q.get("open"),
        "high": q.get("high"),
        "low": q.get("low"),
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


def get_kline_data_for_secid(
    secid: str,
    ut: str | None = None,
    *,
    lmt: int = 120,
    return_closes: bool = False,
    kline_bases: tuple[str, ...] | None = None,
    cache_ttl_sec: float | None = None,
) -> dict[str, Any] | None:
    """日 K：SQLite（新鲜）→ Tushare（个股 pro_bar / 申万 sw_daily）。"""
    u = resolve_ut(ut or DEFAULT_UT)
    eff_lmt = max(40, int(lmt))
    cache_key = (str(secid), u, eff_lmt, bool(return_closes))
    sid_u = str(secid).strip().upper()
    if cache_ttl_sec is not None:
        ttl = max(0.0, float(cache_ttl_sec))
    else:
        ttl = (
            _kline_ttl_bk_sec
            if sid_u.startswith("90.") or sid_u.endswith(".SI")
            else _kline_ttl_stock_sec
        )
    skip_ram_rtk = False
    try:
        from quote_tushare import stock_rt_k_skip_ram_cache_for_secid

        skip_ram_rtk = stock_rt_k_skip_ram_cache_for_secid(str(secid).strip())
    except Exception:
        pass
    now = time.time()
    if ttl > 0 and not skip_ram_rtk:
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
                    op, hi, lo, cl, vo = ohlcv
                    try:
                        from quote_tushare import merge_stock_ohlcv_lists_with_rt_k

                        op, hi, lo, cl, vo, last_m = (
                            merge_stock_ohlcv_lists_with_rt_k(
                                str(secid).strip(),
                                list(op),
                                list(hi),
                                list(lo),
                                list(cl),
                                list(vo),
                                hist_last_date=last_dt,
                                ut=u,
                            )
                        )
                        if last_m:
                            last_dt = last_m
                    except Exception:
                        pass
                    out = kline_dict_from_ohlcv_series(
                        op,
                        hi,
                        lo,
                        cl,
                        vo,
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
                        if ttl > 0 and not skip_ram_rtk:
                            with _kline_lock:
                                _kline_ram_cache[cache_key] = (
                                    time.time(),
                                    copy.deepcopy(out),
                                )
                        return out
        except Exception:
            pass

    try:
        from quote_tushare import try_get_kline_dict_for_secid

        tu = try_get_kline_dict_for_secid(
            secid, eff_lmt, return_closes=return_closes, ut=u
        )
        if tu is not None:
            if ttl > 0 and not skip_ram_rtk:
                with _kline_lock:
                    _kline_ram_cache[cache_key] = (time.time(), copy.deepcopy(tu))
            return tu
    except Exception:
        pass

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
    """申万行业指数 ts_code（801780.SI）；遗留 BK 仅大写透传（已无东财 K 线）。"""
    s = str(raw).strip().upper()
    if len(s) >= 9 and s.endswith(".SI") and s[:-3].isdigit():
        return s
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
    """申万行业指数日 K（801xxx.SI）；东财 90.BK 已废弃。"""
    u = resolve_ut(ut or DEFAULT_UT)
    ts = normalize_bk_code(bk_code)
    if ts.endswith(".SI"):
        return get_kline_data_for_secid(
            ts, u, lmt=lmt, return_closes=return_closes, cache_ttl_sec=cache_ttl_sec
        )
    return None
