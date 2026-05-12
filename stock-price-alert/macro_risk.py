"""后台宏观/板块风控权重（仅参与打分降权，不单独前台展示）。"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

_INDEX_KLINE_LOCK = threading.Lock()
# ts_code -> {"closes": list, "vols": list | None, "ts": float}
_index_bar_cache: dict[str, dict[str, Any]] = {}
_index_kline_ttl_sec: float = 60.0
# 配置中的默认跟踪列表（供文档/预热；get_index_closes_cached 任意合法 ts_code 均可拉取）
_index_list_default: list[str] = ["000001.SH", "000300.SH", "399006.SZ"]

_SH_INDEX_MIN_BARS = 20
_SH_INDEX_LMT = 120


def configure_index_kline_cache(
    ttl_sec: float | None = None,
    *,
    index_list: list[str] | None = None,
) -> None:
    """
    加载 config 后由 run_alert 调用。
    index_list：默认跟踪的指数 ts_code 列表（沪深300、创业板指等）。
    """
    global _index_kline_ttl_sec, _index_list_default
    if ttl_sec is not None:
        with _INDEX_KLINE_LOCK:
            _index_kline_ttl_sec = max(0.0, float(ttl_sec))
    if index_list is not None:
        cleaned: list[str] = []
        for x in index_list:
            s = str(x).strip().upper()
            if s:
                cleaned.append(s)
        if cleaned:
            with _INDEX_KLINE_LOCK:
                _index_list_default = cleaned


def default_index_list() -> list[str]:
    """当前配置的默认指数列表副本。"""
    with _INDEX_KLINE_LOCK:
        return list(_index_list_default)


def _normalize_index_ts(ts_code: str) -> str:
    return str(ts_code or "").strip().upper()


def _fetch_index_closes_network(ts_code: str) -> tuple[list[float], list[float]] | None:
    """单指数：Tushare index_daily + rt_idx_k。"""
    tc = _normalize_index_ts(ts_code)
    if not tc:
        return None
    try:
        from quote_tushare import (
            fetch_index_hist_index_daily,
            merge_index_closes_with_rt_idx_k,
        )

        tu_hist = fetch_index_hist_index_daily(tc, limit=_SH_INDEX_LMT)
        if not tu_hist:
            return None
        closes, vols, last_d = tu_hist
        closes, vols = merge_index_closes_with_rt_idx_k(
            list(closes), list(vols), ts_code=tc, free_last_date=last_d
        )
        return closes, vols
    except Exception:
        return None


def _fetch_sh_index_closes_network() -> tuple[list[float], list[float]] | None:
    """上证指数；兼容旧调用。"""
    return _fetch_index_closes_network("000001.SH")


def get_index_closes_cached(ts_code: str) -> list[float] | None:
    """指定指数日 K 收盘序列（进程内按 ts_code + TTL 缓存）。"""
    tc = _normalize_index_ts(ts_code)
    if not tc:
        return None
    now = time.time()
    with _INDEX_KLINE_LOCK:
        ent = _index_bar_cache.get(tc)
        if (
            ent
            and _index_kline_ttl_sec > 0
            and now - float(ent.get("ts", 0.0)) < _index_kline_ttl_sec
        ):
            c = ent.get("closes")
            return list(c) if isinstance(c, list) else None
    bars = _fetch_index_closes_network(tc)
    with _INDEX_KLINE_LOCK:
        if bars:
            closes, vols = bars
            _index_bar_cache[tc] = {
                "closes": closes,
                "vols": vols,
                "ts": time.time(),
            }
            return list(closes)
        return None


def get_index_volumes_cached(ts_code: str) -> list[float] | None:
    """与 get_index_closes_cached 同次拉取的量序列。"""
    get_index_closes_cached(ts_code)
    tc = _normalize_index_ts(ts_code)
    with _INDEX_KLINE_LOCK:
        ent = _index_bar_cache.get(tc)
        if not ent:
            return None
        v = ent.get("vols")
        return list(v) if isinstance(v, list) else None


def get_sh_index_closes_cached() -> list[float] | None:
    """上证指数日 K 收盘价序列。"""
    return get_index_closes_cached("000001.SH")


def get_sh_index_volumes_cached() -> list[float] | None:
    """与 `get_sh_index_closes_cached` 同一次拉取的量序列。"""
    return get_index_volumes_cached("000001.SH")


def get_market_regime_snapshot(
    *,
    ma_period: int = 20,
    dynamic_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    上证日 K 牛熊判定用到的数值快照（与 get_market_regime 一致）。

    规则：最新收盘 > 近 n 根收盘的简单均值（n=min(数据长度, ma_period)，含当日）则倾向 bull；
    可选 ``use_volume_filter``：量比低于阈值时强制 bear。
    数据不足或拉取失败时 ``data_ok`` 为 False、``regime`` 为 bear（偏保守）。
    """
    dc = dynamic_cfg if isinstance(dynamic_cfg, dict) else {}
    out: dict[str, Any] = {
        "regime": "bear",
        "latest": None,
        "ma_value": None,
        "ma_period_effective": None,
        "bars": 0,
        "volume_demoted": None,
        "data_ok": False,
    }
    closes = get_sh_index_closes_cached()
    mp = max(2, int(ma_period))
    if not closes or len(closes) < mp:
        return out
    n = min(len(closes), mp)
    window = closes[-n:]
    ma_val = sum(float(x) for x in window) / float(len(window))
    latest = float(closes[-1])
    out["bars"] = len(closes)
    out["latest"] = latest
    out["ma_value"] = ma_val
    out["ma_period_effective"] = n
    out["data_ok"] = True
    regime: str = "bull" if latest > ma_val else "bear"
    vol_dem: bool | None = None
    if bool(dc.get("use_volume_filter", False)):
        thr = float(dc.get("volume_ratio_active", 1.2) or 1.2)
        vols = get_sh_index_volumes_cached()
        if (
            vols
            and len(vols) >= len(closes)
            and len(closes) >= 22
        ):
            v_last = float(vols[-1])
            v_ma = sum(float(x) for x in vols[-21:-1]) / 20.0
            if v_ma > 0 and (v_last / v_ma) < thr:
                vol_dem = True
                regime = "bear"
            else:
                vol_dem = False
    out["volume_demoted"] = vol_dem
    out["regime"] = regime
    return out


def get_market_regime(
    *,
    ma_period: int = 20,
    dynamic_cfg: dict[str, Any] | None = None,
) -> str:
    """
    上证日 K：最新收盘是否高于近 ma_period 日简单均线。
    数据不足或失败时返回 ``bear``（偏保守）。
    """
    snap = get_market_regime_snapshot(
        ma_period=ma_period, dynamic_cfg=dynamic_cfg
    )
    return str(snap.get("regime") or "bear")


def _sma_last_window(closes: list[float], n: int) -> float | None:
    if len(closes) < n or n < 1:
        return None
    w = closes[-n:]
    return sum(w) / float(len(w))


def _rsi_last_wilder(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI，取序列最后一个 bar 的 RSI。"""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        d = float(closes[i]) - float(closes[i - 1])
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_g = gains / float(period)
    avg_l = losses / float(period)
    if avg_l <= 1e-12 and avg_g <= 1e-12:
        return 50.0
    if avg_l <= 1e-12:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _bb_width_ratio_last(closes: list[float], period: int = 20) -> float | None:
    """(上轨-下轨)/中轨，中轨与标准差均基于最近 period 根收盘。"""
    if len(closes) < period:
        return None
    w = [float(x) for x in closes[-period:]]
    mid = sum(w) / float(len(w))
    if mid <= 0:
        return None
    var = sum((x - mid) ** 2 for x in w) / max(1.0, float(len(w) - 1))
    std = math.sqrt(max(1e-12, var))
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std
    return (upper - lower) / mid


def _index_volume_ratio_last(closes: list[float], vols: list[float]) -> float | None:
    if not vols or len(vols) < len(closes) or len(closes) < 22:
        return None
    v_last = float(vols[-1])
    tail = [float(x) for x in vols[-21:-1]]
    if not tail:
        return None
    v_ma = sum(tail) / float(len(tail))
    if v_ma <= 0:
        return None
    return v_last / v_ma


def get_index_mood_three_tier(
    ts_code: str,
    *,
    dynamic_cfg: dict[str, Any] | None = None,
) -> str:
    """
    指定指数三档情绪：strong_bull / range / weak_bear。
    结合 MA、RSI、布林带宽度与可选量能；数据不足时偏保守为 weak_bear。
    """
    dc = dynamic_cfg if isinstance(dynamic_cfg, dict) else {}
    ma_p = max(5, min(120, int(dc.get("ma_period", 20) or 20)))
    closes = get_index_closes_cached(ts_code)
    if not closes or len(closes) < max(ma_p, 22):
        return "weak_bear"
    ma_val = _sma_last_window(closes, ma_p)
    if ma_val is None:
        return "weak_bear"
    latest = float(closes[-1])
    rsi_p_raw = dc.get("rsi_period", dc.get("mood_rsi_period", 14))
    rsi_p = max(2, min(30, int(rsi_p_raw if rsi_p_raw is not None else 14)))
    rsi = _rsi_last_wilder(closes, period=rsi_p)
    bb_p_raw = dc.get("bb_period", dc.get("mood_bb_period", 20))
    bb_p = max(5, min(60, int(bb_p_raw if bb_p_raw is not None else 20)))
    bbw = _bb_width_ratio_last(closes, period=bb_p)
    rsi_strong = float(
        dc.get("rsi_strong_bull_min", dc.get("mood_rsi_bull", 56)) or 56
    )
    rsi_weak = float(
        dc.get("rsi_weak_bear_max", dc.get("mood_rsi_bear", 44)) or 44
    )
    bb_min = float(
        dc.get("bb_width_min_for_strong", dc.get("mood_bb_width_bull", 0.012))
        or 0.012
    )
    use_vol = bool(dc.get("use_volume_filter", False))
    vol_thr = float(dc.get("volume_ratio_active", 1.2) or 1.2)
    vols = get_index_volumes_cached(ts_code)
    vr = (
        _index_volume_ratio_last(closes, vols)
        if use_vol and vols
        else None
    )

    weak = latest <= ma_val
    if rsi is not None:
        weak = weak or (rsi <= rsi_weak)
    if use_vol and vr is not None and vr < vol_thr:
        weak = True
    if weak:
        return "weak_bear"

    strong = latest > ma_val
    if rsi is not None:
        strong = strong and (rsi >= rsi_strong)
    if use_vol and vr is not None:
        strong = strong and (vr >= vol_thr)
    if bbw is not None:
        strong = strong and (bbw >= bb_min)
    if strong:
        return "strong_bull"
    return "range"


def get_market_mood_three_tier(*, dynamic_cfg: dict[str, Any] | None = None) -> str:
    """大盘三档情绪：以上证综指为准（兼容旧逻辑）。"""
    return get_index_mood_three_tier("000001.SH", dynamic_cfg=dynamic_cfg)


def get_index_mood(
    ts_code: str, *, dynamic_cfg: dict[str, Any] | None = None
) -> str:
    """同 get_index_mood_three_tier，供策略按指数查询。"""
    return get_index_mood_three_tier(ts_code, dynamic_cfg=dynamic_cfg)


def sector_rs_bucket(
    sector_closes: list[float],
    index_closes: list[float] | None,
    *,
    ret_days: int = 20,
    out_pct: float = 0.005,
    under_pct: float = -0.005,
) -> str:
    """板块相对上证 N 日收益：outperform / neutral / underperform。"""
    if not sector_closes or not index_closes:
        return "neutral"
    n = max(5, min(60, int(ret_days)))
    if len(sector_closes) < n + 1 or len(index_closes) < n + 1:
        return "neutral"
    a_s = float(sector_closes[-n - 1])
    b_s = float(sector_closes[-1])
    a_i = float(index_closes[-n - 1])
    b_i = float(index_closes[-1])
    if a_s <= 0 or a_i <= 0:
        return "neutral"
    rs = b_s / a_s - 1.0
    ri = b_i / a_i - 1.0
    d = rs - ri
    if d >= out_pct:
        return "outperform"
    if d <= under_pct:
        return "underperform"
    return "neutral"


def _keyword_hit(text: str, keywords: tuple[str, ...]) -> bool:
    t = text or ""
    return any(k in t for k in keywords)


def industry_whitelist_bonus(industry: str, stock_name: str) -> bool:
    """消费、食品家电、高端制造、汽车零部件、风光储、新能源有色等。"""
    blob = f"{industry or ''}{stock_name or ''}"
    keys = (
        "食品饮料",
        "白酒",
        "啤酒",
        "调味发酵",
        "食品加工",
        "家电",
        "家居",
        "纺织",
        "服装",
        "商贸零售",
        "机械设备",
        "通用设备",
        "专用设备",
        "自动化",
        "军工",
        "国防",
        "汽车零部件",
        "汽车零",
        "电机",
        "电池",
        "光伏",
        "风电",
        "储能",
        "电力设备",
        "能源金属",
        "小金属",
        "稀有金属",
        "稀土",
        "锂",
        "钴",
        "镍",
        "电网设备",
        "电机",
        "消费电子",
        "半导体",
        "通信",
        "光学光电子",
        "元件",
        "电子化学品",
    )
    return _keyword_hit(blob, keys)


def industry_blacklist_penalty(industry: str, stock_name: str) -> bool:
    """地产、基建、建材、金融、煤炭钢铁、传统化工等。"""
    blob = f"{industry or ''}{stock_name or ''}"
    keys = (
        "房地产",
        "房地产开发",
        "水泥",
        "工程建设",
        "基础建设",
        "房屋建设",
        "装修建材",
        "建筑材料",
        "钢铁",
        "煤炭",
        "石油石化",
        "炼化",
        "银行",
        "保险",
        "证券",
        "多元金融",
        "化学原料",
        "化学制品",
        "农化制品",
        "塑料",
        "橡胶",
    )
    if _keyword_hit(blob, keys):
        return True
    # 低端有色：铝/铅/锡（名称或行业含关键字）
    metal_low = ("铝", "铅", "锡")
    if _keyword_hit(industry or "", metal_low) or _keyword_hit(stock_name or "", metal_low):
        if not _keyword_hit(blob, ("锂", "钴", "镍", "稀土", "能源金属", "稀土永磁")):
            return True
    return False


def fetch_index_5d_return() -> float | None:
    """上证指数近 5 个交易日累计涨跌比例 (close[-1]/close[-6]-1)，失败返回 None。"""
    try:
        closes = get_sh_index_closes_cached()
        if closes is None or len(closes) < 6:
            return None
        c0, c5 = closes[-1], closes[-6]
        if c5 <= 0:
            return None
        return float((c0 - c5) / c5)
    except Exception:
        return None


def fetch_index_mood_mult() -> float:
    """
    粗略大盘情绪：上证指数近 5 日涨跌。
    失败时返回 1.0，成功时 [-0.03,0.03] 映射到 [0.94,1.06] 乘子。
    """
    try:
        closes = get_sh_index_closes_cached()
        if closes is None or len(closes) < 6:
            return 1.0
        c0, c5 = closes[-1], closes[-6]
        if c5 <= 0:
            return 1.0
        ret5 = (c0 - c5) / c5
        m = 1.0 + max(-0.06, min(0.06, ret5))
        return float(max(0.94, min(1.06, m)))
    except Exception:
        return 1.0


def macro_score_multiplier(
    industry: str,
    stock_name: str,
    *,
    index_mood_mult: float | None = None,
    cfg: dict[str, Any] | None = None,
) -> float:
    """
    后台综合乘子：利好赛道略加成，利空板块降权；叠加大盘情绪。
    不在控制台单独展示，仅作用于排序分。
    """
    cfg = cfg or {}
    base = 1.0
    if industry_whitelist_bonus(industry, stock_name):
        base *= 1.06
    if industry_blacklist_penalty(industry, stock_name):
        base *= 0.72

    mood_ov = float((cfg.get("macro_risk") or {}).get("index_mood_mult_override") or 0.0)
    if mood_ov > 0:
        base *= mood_ov
    elif index_mood_mult is not None:
        base *= float(index_mood_mult)
    else:
        base *= fetch_index_mood_mult()

    return float(max(0.55, min(1.25, base)))
