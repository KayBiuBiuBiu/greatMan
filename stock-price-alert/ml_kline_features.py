# -*- coding: utf-8 -*-
"""
日 K 特征：兼容两套列名。
- FEATURE_COLUMNS + enrich_ohlcv：旧版 6 列模型
- TREND_FEATURE_COLUMNS + compute_trend_aligned_features：与趋势预警子维度更贴近的 9 列模型
"""

from __future__ import annotations

FEATURE_COLUMNS = ("ma5", "ma20", "ret1", "vol_ratio", "atr", "macd_hist")

TREND_FEATURE_COLUMNS = (
    "ma5_below_ma20",
    "close_below_ma20",
    "close_below_ma60",
    "vol_spike",
    "atr_pct",
    "macd_bearish",
    "macd_death_cross",
    "high_upper_shadow",
    "vol_ratio",
)


def enrich_ohlcv(df):
    """
    输入含 trade_date, open, high, low, close, volume 的 DataFrame（单票、任意顺序）。
    返回按 trade_date 升序、带旧版技术指标列的副本（不含 label）。
    """
    import pandas as pd

    out = df.sort_values("trade_date").copy()
    c = out["close"].astype(float)
    out["ma5"] = c.rolling(5).mean()
    out["ma20"] = c.rolling(20).mean()
    out["ret1"] = c.pct_change(1)
    vol = out["volume"].astype(float)
    vol_ma20 = vol.rolling(20).mean()
    out["vol_ratio"] = vol / (vol_ma20 + 1e-6)
    high = out["high"].astype(float)
    low = out["low"].astype(float)
    high_low = high - low
    high_close = (high - c.shift()).abs()
    low_close = (low - c.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14).mean()
    exp1 = c.ewm(span=12, adjust=False).mean()
    exp2 = c.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    sig = macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd - sig
    return out


def compute_trend_aligned_features(df):
    """
    与趋势下滑相关子维度对齐的一组离散/连续特征（单票 OHLCV）。
    返回含 trade_date + TREND_FEATURE_COLUMNS，不含 label。
    """
    import pandas as pd

    out = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = out["close"].astype(float)
    o = out["open"].astype(float)
    h = out["high"].astype(float)
    lo = out["low"].astype(float)
    v = out["volume"].astype(float)

    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    vol_ma20 = v.rolling(20).mean()
    vol_ratio = v / (vol_ma20 + 1e-6)

    high_low = h - lo
    high_close = (h - c.shift()).abs()
    low_close = (lo - c.shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    exp12 = c.ewm(span=12, adjust=False).mean()
    exp26 = c.ewm(span=26, adjust=False).mean()
    macd = exp12 - exp26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    oc_max = pd.concat([o, c], axis=1).max(axis=1)
    upper_shadow = (h - oc_max) / (h - lo + 1e-6)

    feat = pd.DataFrame(
        {
            "trade_date": out["trade_date"],
            "ma5_below_ma20": (ma5 < ma20).astype("float64"),
            "close_below_ma20": (c < ma20).astype("float64"),
            "close_below_ma60": (c < ma60).astype("float64"),
            "vol_spike": (vol_ratio > 1.5).astype("float64"),
            "atr_pct": atr / (c + 1e-12),
            "macd_bearish": (macd_hist < 0).astype("float64"),
            "macd_death_cross": (
                (macd < macd_signal) & (macd.shift(1) >= macd_signal.shift(1))
            ).astype("float64"),
            "high_upper_shadow": (upper_shadow > 0.5).astype("float64"),
            "vol_ratio": vol_ratio,
        }
    )
    return feat


def add_forward_down_label(
    df,
    *,
    forward_days: int = 5,
    threshold_pct: float = -3.0,
):
    """
    未来 forward_days 个交易日收盘相对当前收盘收益率 < threshold_pct% 则 label=1。
    基于旧版 enrich_ohlcv 特征列。
    """
    out = enrich_ohlcv(df)
    thr = float(threshold_pct) / 100.0
    c = out["close"].astype(float)
    fwd = c.shift(-int(forward_days)) / c - 1.0
    lab = (fwd < thr).astype("float64")
    lab = lab.where(fwd.notna(), float("nan"))
    out["label"] = lab
    return out


def build_trend_frame_with_label(
    df,
    *,
    forward_days: int = 5,
    threshold_pct: float = -3.0,
):
    """趋势对齐特征 + 正确的前向收益标签（非 ret5.shift）。"""
    base = df.sort_values("trade_date").reset_index(drop=True).copy()
    c = base["close"].astype(float)
    feat = compute_trend_aligned_features(base)
    thr = float(threshold_pct) / 100.0
    fwd = c.shift(-int(forward_days)) / c - 1.0
    lab = (fwd < thr).astype("float64")
    lab = lab.where(fwd.notna(), float("nan"))
    feat = feat.copy()
    feat["label"] = lab.values
    return feat
