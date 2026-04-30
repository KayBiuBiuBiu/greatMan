"""趋势下滑预警：个股技术 + 大盘 + 东财行业板块指数(BK) 三柱联立，任意 2 柱走弱即触发。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _true_range_series(
    closes: list[float],
    highs: list[float] | None,
    lows: list[float] | None,
) -> list[float] | None:
    """与收盘价对齐的日 TR 序列（长度 len(closes)-1）。"""
    if len(closes) < 2:
        return None
    use_hl = (
        isinstance(highs, list)
        and isinstance(lows, list)
        and len(highs) == len(lows) == len(closes)
    )
    tr: list[float] = []
    for i in range(1, len(closes)):
        c0, c1 = float(closes[i]), float(closes[i - 1])
        if use_hl:
            h0, l0 = float(highs[i]), float(lows[i])
            tr.append(max(h0 - l0, abs(h0 - c1), abs(l0 - c1)))
        else:
            tr.append(abs(c0 - c1))
    return tr


def _wilder_atr_last(tr: list[float], period: int) -> float | None:
    """Wilder 平滑：首值 = 前 period 根 TR 简单均值，之后 ATR=(ATR_prev*(n-1)+TR)/n。"""
    n = max(2, int(period))
    if len(tr) < n:
        return None
    atr = sum(tr[:n]) / float(n)
    for j in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[j]) / float(n)
    return atr


def _atr_close_pct(
    closes: list[float],
    kline: dict[str, Any],
    lookback: int,
    *,
    method: str = "wilder",
) -> float | None:
    """ATR% = ATR / 最后一根收盘价；默认 Wilder，可选 simple_ma（原简均 TR）。"""
    highs = kline.get("highs") if isinstance(kline.get("highs"), list) else None
    lows = kline.get("lows") if isinstance(kline.get("lows"), list) else None
    tr = _true_range_series(closes, highs, lows)
    if tr is None:
        return None
    lb = max(2, min(int(lookback), len(tr)))
    m = (method or "wilder").strip().lower()
    if m in ("simple", "simple_ma", "sma"):
        if len(tr) < lb:
            return None
        atr = sum(tr[-lb:]) / float(lb)
    else:
        atr = _wilder_atr_last(tr, lb)
        if atr is None:
            return None
    last = float(closes[-1])
    if last <= 0:
        return None
    return 100.0 * atr / last


def _sort_atr_tier_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple[int, float]:
        m = r.get("max_close_atr_pct")
        if m is None:
            return (1, float("inf"))
        try:
            return (0, float(m))
        except (TypeError, ValueError):
            return (0, float("inf"))

    return sorted(rows, key=key)


def _pick_atr_tier_dims(
    atr_pct: float | None,
    tiers_raw: Any,
    *,
    base_stock_min: int,
    base_sector_min: int,
    base_min_pillars: int,
) -> tuple[int, int, int, str | None]:
    """按 ATR% 命中分档；pct 缺失时退回配置基线（不启用分档逻辑）。"""
    if atr_pct is None:
        return base_stock_min, base_sector_min, base_min_pillars, None
    rows_in = [x for x in (tiers_raw or []) if isinstance(x, dict)]
    if not rows_in:
        return base_stock_min, base_sector_min, base_min_pillars, None
    rows = _sort_atr_tier_rows(rows_in)
    chosen = rows[-1]
    for r in rows:
        mx = r.get("max_close_atr_pct")
        if mx is None:
            chosen = r
            break
        try:
            if atr_pct <= float(mx):
                chosen = r
                break
        except (TypeError, ValueError):
            continue
    sm = max(1, int(chosen.get("stock_min_weak_dims", base_stock_min)))
    sec = max(1, int(chosen.get("sector_min_weak_dims", base_sector_min)))
    mp = max(1, int(chosen.get("min_pillars_weak", base_min_pillars)))
    mxv = chosen.get("max_close_atr_pct")
    cap = "∞" if mxv is None else str(mxv)
    note = f"ATR分档≈{atr_pct:.2f}%（档至{cap}%）阈个股{sm}/板块{sec}/柱{mp}"
    return sm, sec, mp, note


def _ema_series(values: list[float], span: int) -> list[float]:
    if not values or span <= 0:
        return []
    k = 2.0 / (span + 1)
    out: list[float] = []
    e = float(values[0])
    for x in values:
        e = float(x) * k + e * (1.0 - k)
        out.append(e)
    return out


def _macd_components(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    if len(closes) < 35:
        return [], [], []
    ema12 = _ema_series(closes, 12)
    ema26 = _ema_series(closes, 26)
    n = min(len(ema12), len(ema26), len(closes))
    ema12 = ema12[-n:]
    ema26 = ema26[-n:]
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = _ema_series(dif, 9)
    m = min(len(dif), len(dea))
    dif = dif[-m:]
    dea = dea[-m:]
    hist = [dif[i] - dea[i] for i in range(m)]
    return dif, dea, hist


def _count_ma_pattern_macd_vol(
    price: float,
    kline: dict[str, Any],
    closes: list[float],
    tc: dict[str, Any],
    tag_prefix: str,
) -> tuple[int, list[str]]:
    """返回走弱子项数量(0~4)：均线、K 线形态、MACD、放量下跌。"""
    vol_spike = float(tc.get("volume_spike_vs_ma20", 1.85))
    near_high_ratio = float(tc.get("near_high_20_ratio", 0.88))
    reasons: list[str] = []
    ma20 = float(kline.get("ma20") or 0.0)
    ma5 = float(kline.get("ma5") or 0.0)
    ma60_v = kline.get("ma60")
    ma60 = float(ma60_v) if ma60_v is not None else None
    high20 = float(kline.get("high20") or 0.0)
    opens = kline.get("opens")
    highs = kline.get("highs")
    lows = kline.get("lows")
    vols = kline.get("volumes")
    if (
        not isinstance(opens, list)
        or not isinstance(highs, list)
        or not isinstance(lows, list)
        or not isinstance(vols, list)
        or len(closes) < 6
        or len(closes) != len(highs)
    ):
        return 0, []

    cnt = 0
    ma_tags: list[str] = []
    if ma20 > 0 and price < ma20:
        ma_tags.append("收盘低于20日线")
    if ma60 is not None and ma60 > 0 and price < ma60:
        ma_tags.append("收盘低于60日线")
    if ma20 > 0 and ma5 < ma20:
        ma_tags.append("5日线低于20日线")
    if ma_tags:
        cnt += 1
        reasons.append(f"{tag_prefix}均线偏弱(" + "，".join(ma_tags[:3]) + ")")

    o0, h0, l0, c0 = (
        float(opens[-1]),
        float(highs[-1]),
        float(lows[-1]),
        float(closes[-1]),
    )
    rng = max(h0 - l0, 1e-6)
    upper_shadow = (h0 - max(o0, c0)) / rng
    pat_hit = False
    if high20 > 0 and c0 >= high20 * near_high_ratio and upper_shadow >= 0.5 and c0 < o0:
        pat_hit = True
        reasons.append(f"{tag_prefix}高位长上影")
    if len(closes) >= 2:
        o_1, c_1 = float(opens[-2]), float(closes[-2])
        if o0 > c_1 and c0 < o_1 and c0 < c_1:
            pat_hit = True
            reasons.append(f"{tag_prefix}阴包阳")
    if len(closes) >= 4:
        c1, c2, c3 = closes[-1], closes[-2], closes[-3]
        if c1 < c2 < c3 and c1 < float(lows[-2]) * 1.002:
            pat_hit = True
            reasons.append(f"{tag_prefix}破位连阴")
    if pat_hit:
        cnt += 1

    pre = kline.get("precomputed_macd")
    if isinstance(pre, dict):
        dif = [float(x) for x in (pre.get("dif") or [])]
        dea = [float(x) for x in (pre.get("dea") or [])]
        hist = [float(x) for x in (pre.get("hist") or [])]
        if len(hist) < 4 or len(dif) < 3 or len(dea) < 3:
            dif, dea, hist = _macd_components(closes)
    else:
        dif, dea, hist = _macd_components(closes)
    macd_hit = False
    if len(dif) >= 3 and len(dea) >= 3 and len(hist) >= 4:
        if dif[-2] >= dea[-2] and dif[-1] < dea[-1] and hist[-1] < 0:
            macd_hit = True
            reasons.append(f"{tag_prefix}MACD死叉转弱")
        elif hist[-1] < 0 and hist[-1] < hist[-2] < hist[-3]:
            macd_hit = True
            reasons.append(f"{tag_prefix}MACD柱翻负衰减")
        else:
            look = min(25, len(closes) - 1)
            j0 = len(hist)
            if look >= 15 and j0 >= look:
                hi_hist = max(hist[j0 - look :])
                mid_hist = max(hist[max(0, j0 - 2 * look) : max(1, j0 - look)])
                if closes[-1] >= max(closes[-look:]) * 0.998 and hi_hist < mid_hist * 0.65:
                    macd_hit = True
                    reasons.append(f"{tag_prefix}MACD顶背离迹象")
    if macd_hit:
        cnt += 1

    if len(vols) >= 22 and len(closes) >= 2:
        v_last = float(vols[-1])
        v_ma = sum(float(x) for x in vols[-21:-1]) / 20.0
        if v_ma > 0 and v_last >= vol_spike * v_ma and c0 < float(closes[-2]):
            cnt += 1
            reasons.append(f"{tag_prefix}放量下跌")

    return cnt, reasons


@dataclass
class TrendSlippageResult:
    fire: bool
    weak_count: int
    reasons: list[str]
    summary: str
    pillars: tuple[bool, bool, bool]  # 个股, 大盘, 板块
    sector_eligible: bool  # 板块日 K 是否参与三柱（否则为两柱退化）
    weak_pillars: dict[str, bool] = field(default_factory=dict)
    weak_dims_by_pillar: dict[str, list[str]] = field(default_factory=dict)
    sector_data_warning: str | None = None
    skipped_by_filter: str | None = None


def _trend_skip(
    summary: str,
    *,
    sector_eligible: bool = False,
    skipped: str,
) -> TrendSlippageResult:
    return TrendSlippageResult(
        False,
        0,
        [],
        summary,
        (False, False, False),
        sector_eligible=sector_eligible,
        weak_pillars={},
        weak_dims_by_pillar={},
        sector_data_warning=None,
        skipped_by_filter=skipped,
    )


def evaluate_trend_slippage_alert(
    price: float,
    kline: dict[str, Any],
    closes: list[float],
    index_mood_mult: float,
    index_5d_ret: float | None,
    *,
    sector_bk: str | None,
    sector_kline: dict[str, Any] | None,
    sector_closes: list[float],
    cfg: dict[str, Any],
    stock_code: str | None = None,
    float_mv_yuan: float | None = None,
) -> TrendSlippageResult:
    tc = dict(cfg.get("trend_slippage_alert") or {})
    if not bool(tc.get("enabled", True)):
        return TrendSlippageResult(
            False,
            0,
            [],
            "",
            (False, False, False),
            sector_eligible=False,
            weak_pillars={},
            weak_dims_by_pillar={},
            sector_data_warning=None,
            skipped_by_filter=None,
        )

    ign = tc.get("alert_ignore_codes")
    if isinstance(ign, list) and stock_code:
        raw_c = str(stock_code).strip()
        c6 = raw_c.zfill(6) if raw_c.isdigit() else ""
        if len(c6) == 6:
            ign_set = {
                str(x).strip().zfill(6)
                for x in ign
                if str(x).strip().isdigit() and len(str(x).strip()) <= 6
            }
            if c6 in ign_set:
                return _trend_skip(
                    "（趋势预警：该股在 alert_ignore_codes 中已忽略）",
                    skipped="alert_ignore_codes",
                )

    min_price = float(tc.get("min_price") or 0)
    if min_price > 0 and float(price) < min_price:
        return _trend_skip(
            f"（趋势预警：现价 {float(price):.2f} 低于 min_price={min_price}，已跳过）",
            skipped="min_price",
        )

    min_mv_yi = float(tc.get("min_float_mv_yi") or 0)
    if min_mv_yi > 0 and float_mv_yuan is not None and float(float_mv_yuan) > 0:
        yi = float(float_mv_yuan) / 1e8
        if yi < min_mv_yi:
            return _trend_skip(
                f"（趋势预警：流通市值约 {yi:.2f} 亿低于 min_float_mv_yi={min_mv_yi}，已跳过）",
                skipped="min_float_mv_yi",
            )

    min_vr = float(tc.get("min_volume_ratio") or 0)
    if min_vr > 0:
        vols = kline.get("volumes")
        if isinstance(vols, list) and len(vols) >= 22:
            v_last = float(vols[-1])
            v_ma = sum(float(x) for x in vols[-21:-1]) / 20.0
            if v_ma > 0 and (v_last / v_ma) < min_vr:
                return _trend_skip(
                    f"（趋势预警：当日量/20日均量={v_last / v_ma:.2f} 低于 min_volume_ratio={min_vr}，已跳过）",
                    skipped="min_volume_ratio",
                )

    stock_min = max(1, int(tc.get("stock_min_weak_dims", 2)))
    sector_min = max(1, int(tc.get("sector_min_weak_dims", 2)))
    min_pillars = max(1, int(tc.get("min_pillars_weak", 2)))
    atr_note: str | None = None
    atr_cfg = tc.get("atr_tiers")
    if isinstance(atr_cfg, dict) and bool(atr_cfg.get("enabled")):
        lb = max(5, int(atr_cfg.get("lookback", 20)))
        atr_method = str(atr_cfg.get("method", "wilder") or "wilder")
        p_pre = kline.get("precomputed_atr_pct")
        if lb == 20 and p_pre is not None:
            try:
                pct = float(p_pre)
            except (TypeError, ValueError):
                pct = _atr_close_pct(closes, kline, lb, method=atr_method)
        else:
            pct = _atr_close_pct(closes, kline, lb, method=atr_method)
        stock_min, sector_min, min_pillars, atr_note = _pick_atr_tier_dims(
            pct,
            atr_cfg.get("tiers"),
            base_stock_min=stock_min,
            base_sector_min=sector_min,
            base_min_pillars=min_pillars,
        )
        if atr_note:
            if atr_method.strip().lower() in ("simple", "simple_ma", "sma"):
                atr_note = atr_note + "｜ATR=简均TR"
            else:
                atr_note = atr_note + "｜ATR=Wilder"
    idx_weak_max = float(tc.get("index_weak_mult_max", 0.99))
    idx_ret_weak = float(tc.get("index_5d_ret_weak", -0.008))

    st_cnt, st_reasons = _count_ma_pattern_macd_vol(
        price, kline, closes, tc, tag_prefix="个股"
    )
    stock_weak = st_cnt >= stock_min

    market_weak = index_mood_mult < idx_weak_max or (
        index_5d_ret is not None and index_5d_ret < idx_ret_weak
    )
    m_reasons: list[str] = []
    if index_mood_mult < idx_weak_max:
        m_reasons.append("大盘情绪偏弱")
    if index_5d_ret is not None and index_5d_ret < idx_ret_weak:
        m_reasons.append("上证5日走弱")

    sector_eligible = bool(
        sector_bk
        and sector_kline
        and len(sector_closes) >= 40
        and sector_kline.get("opens")
    )
    sec_cnt = 0
    sec_reasons: list[str] = []
    if sector_eligible:
        sk = sector_kline or {}
        sp = float(sector_closes[-1])
        sec_cnt, sec_reasons = _count_ma_pattern_macd_vol(
            sp, sk, sector_closes, tc, tag_prefix="板块"
        )
    sector_weak = sector_eligible and (sec_cnt >= sector_min)

    if sector_eligible:
        pillars_weak = sum([stock_weak, market_weak, sector_weak])
        fire = pillars_weak >= min_pillars
    else:
        fire = stock_weak and market_weak

    reasons = list(dict.fromkeys(st_reasons + m_reasons + sec_reasons))
    if not sector_eligible and sector_bk:
        reasons.append("（板块K线不足，未计板块柱）")

    sector_data_warning: str | None = None
    if not sector_eligible:
        bk_s = str(sector_bk or "").strip()
        if bk_s:
            sector_data_warning = (
                "【数据说明】板块数据不完整：已解析BK但缺少可用板块日K，"
                "当前仅个股技术柱+大盘柱参与判断；板块若实际走弱可能未计入，信号可能不完整。"
            )
        else:
            sector_data_warning = (
                "【数据说明】板块数据缺失：未解析到BK或未配置 sector_index_overrides，"
                "当前仅个股+大盘两柱；请用 --check-bk 或 overrides 补全以启用三柱。"
            )

    weak_pillars = {
        "个股": bool(stock_weak),
        "大盘": bool(market_weak),
        "板块": bool(sector_weak),
    }
    weak_dims_by_pillar = {
        "个股": list(st_reasons),
        "大盘": list(m_reasons),
        "板块": list(sec_reasons),
    }

    summary = (
        f"三柱走弱 {sum([stock_weak, market_weak, sector_weak])}/3 "
        f"｜个股技术{st_cnt}/4(阈{stock_min})={'是' if stock_weak else '否'} "
        f"｜大盘={'是' if market_weak else '否'} "
        f"｜板块{sector_bk or '-'}技术{sec_cnt}/4(阈{sector_min})={'是' if sector_weak else '否'}"
    )
    if atr_note:
        summary += f"｜{atr_note}"
    if not sector_eligible:
        summary += "｜模式：两柱(无有效板块数据时须个股与大盘同时走弱)"
    tail = "；".join(reasons[:10])
    if tail:
        summary += "｜" + tail

    wc = sum([stock_weak, market_weak, sector_weak])
    return TrendSlippageResult(
        fire,
        wc,
        reasons,
        summary,
        (stock_weak, market_weak, sector_weak),
        sector_eligible=sector_eligible,
        weak_pillars=weak_pillars,
        weak_dims_by_pillar=weak_dims_by_pillar,
        sector_data_warning=sector_data_warning,
        skipped_by_filter=None,
    )
