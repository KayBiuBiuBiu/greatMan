"""可选 Tushare Pro：上证 index_daily + rt_idx_k；个股历史 daily/东财/SQLite + rt_k 合并最新一根。"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

_CFG: dict[str, Any] = {
    "enabled": False,
    "token": "",
    "token_env": "TUSHARE_TOKEN",
    # True：index_daily 失败时仍用新浪/腾讯/东财补历史（仅持 rt_idx_k 时需开）
    "sh_index_free_fallback": False,
    # 个股：历史 + rt_k 合并（A 股日线 RT）
    "stock_rt_k_enabled": True,
    # True：rt_k 失败时用东财再拉最新一根补最后一根（默认关）
    "stock_rt_k_fallback": False,
}
_PRO: Any = None


def configure_tushare_from_sources(sources: dict[str, Any] | None) -> None:
    """在 configure_ssl_from_sources 之后由 utils 调用；更新 enabled / token / 重置 pro 句柄。"""
    global _PRO
    _PRO = None
    if not isinstance(sources, dict):
        _CFG["enabled"] = False
        _CFG["token"] = ""
        _CFG["sh_index_free_fallback"] = False
        _CFG["stock_rt_k_enabled"] = True
        _CFG["stock_rt_k_fallback"] = False
        return
    t = sources.get("tushare")
    if not isinstance(t, dict):
        _CFG["enabled"] = False
        _CFG["token"] = ""
        _CFG["sh_index_free_fallback"] = False
        _CFG["stock_rt_k_enabled"] = True
        _CFG["stock_rt_k_fallback"] = False
        return
    _CFG["enabled"] = bool(t.get("enabled", False))
    _CFG["token"] = str(t.get("token") or "").strip()
    _CFG["token_env"] = str(t.get("token_env") or "TUSHARE_TOKEN").strip() or "TUSHARE_TOKEN"
    _CFG["sh_index_free_fallback"] = bool(t.get("sh_index_free_fallback", False))
    _CFG["stock_rt_k_enabled"] = bool(t.get("stock_rt_k_enabled", True))
    _CFG["stock_rt_k_fallback"] = bool(t.get("stock_rt_k_fallback", False))


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


def fetch_sh_index_hist_index_daily(
    *, limit: int = 120
) -> tuple[list[float], list[float], str | None] | None:
    """
    上证指数历史日 K（积分接口 index_daily），升序；最后一根日期供与 rt_idx_k 对齐。
    无权限或失败时返回 None。
    """
    pro = _get_pro()
    if pro is None:
        return None
    want = max(40, int(limit))
    start_s, end_s = _date_window_for_bars(want)
    try:
        df = pro.index_daily(ts_code="000001.SH", start_date=start_s, end_date=end_s)
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


def merge_sh_index_with_rt_idx_k(
    closes: list[float],
    vols: list[float],
    *,
    free_last_date: str | None,
) -> tuple[list[float], list[float]]:
    """
    用 rt_idx_k 覆盖或追加「最新交易日」收盘/量；历史序列由 index_daily（或回退源）提供。
    free_last_date：历史最后一根交易日 YYYY-MM-DD，用于判断追加或替换。
    """
    if not (_CFG.get("enabled") and _resolved_token()):
        return closes, vols
    if not closes or len(closes) < 20:
        return closes, vols
    snap = _rt_idx_k_latest_row("000001.SH")
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


def _em_fallback_last_row(
    secid: str,
    ut: str | None,
) -> tuple[str, float, float, float, float, float] | None:
    """stock_rt_k_fallback：东财取最近一小段日 K 的最后一根。"""
    try:
        from quote_eastmoney import _fetch_kline_chunk_rows, resolve_ut

        u = resolve_ut(ut)
        rows = _fetch_kline_chunk_rows(secid, u, lmt=40, end_ymd="20500101")
        if not rows:
            return None
        return rows[-1]
    except Exception:
        return None


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
    if not rt and stock_rt_k_fallback_enabled():
        em = _em_fallback_last_row(secid, ut)
        if em:
            ds, o, h, low, c, v = em
            rt = {
                "trade_date": str(ds).strip()[:10],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "vol": v,
            }
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
    if not rt and stock_rt_k_fallback_enabled():
        em = _em_fallback_last_row(secid, ut)
        if em:
            ds, o, h, low, c, v = em
            rt = {
                "trade_date": str(ds).strip()[:10],
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "vol": v,
            }
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
    """与 quote_eastmoney.get_kline_data_for_secid 网络分支结构一致的快照（kline_data_source=tushare）。"""
    rows = try_fetch_daily_rows_for_secid(secid, lmt=lmt)
    if not rows:
        return None
    rows = merge_stock_rows_with_rt_k(secid, rows, ut=ut)
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
