"""AkShare 资金/北向/龙虎榜类特征 → 固定维度浮点向量，供 GaussianNB 管线使用。

对齐说明：
- 使用行情/资金数据中 **截止日期 ≤ anchor_trade_date** 的行情行，降低未来函数；
- 北向明细若长期停更（东财改版等），仅用已有最近数据并打 warning；
- 所有异常退化为默认值，不向调用方抛出。

配置（ml_filter）：
- ``external_flow_features_enabled``：默认 False；为 True 时训练/推断都会附加下列特征。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_LOG = logging.getLogger(__name__)

# 导出给训练一致性校验 / 文档
EXTERNAL_FLOW_FEATURE_KEYS: tuple[str, ...] = (
    "ext_fund_main_net_pct_mean",
    "ext_fund_super_net_pct_mean",
    "ext_north_mv_chg_ratio",
    "ext_on_lhb",
    "ext_lhb_net_buy_wan",
)


def external_flow_feature_defaults() -> dict[str, float]:
    return {k: 0.0 for k in EXTERNAL_FLOW_FEATURE_KEYS}


def clear_external_flow_caches() -> None:
    """测试或长进程热更新后可手动清空 LRU。"""
    _cached_lhb_dates.cache_clear()
    _cached_lhb_buy_detail.cache_clear()


def _normalize_code6(code: str) -> str:
    s = "".join(c for c in str(code).strip() if c.isdigit())
    if len(s) >= 6:
        return s[-6:]
    return s.zfill(6)


def _anchor_to_date(anchor_trade_date: str) -> datetime | None:
    s = str(anchor_trade_date).strip().replace("/", "-")[:10]
    if len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _ak_market(code6: str) -> str:
    if len(code6) == 6 and code6.startswith("6"):
        return "sh"
    return "sz"


def _cached_fund_flow_aggs(code6: str, anchor: str, days: int) -> tuple[float, float]:
    """(主力净流入-净占比 均值, 超大单净流入-净占比 均值)，窗口为 anchor 当日及此前共 days 个交易日。"""
    try:
        import akshare as ak
    except ImportError:
        _LOG.warning("AkShare 未安装，资金流特征不可用")
        return 0.0, 0.0
    anchor_d = _anchor_to_date(anchor)
    if not anchor_d:
        return 0.0, 0.0
    mkt = _ak_market(code6)
    try:
        df = ak.stock_individual_fund_flow(stock=_normalize_code6(code6), market=mkt)
    except Exception:
        _LOG.debug("fund_flow fetch failed code=%s", code6, exc_info=True)
        return 0.0, 0.0
    if df.empty or "日期" not in df.columns:
        return 0.0, 0.0
    dc = pd.to_datetime(df["日期"], errors="coerce")
    sub = df.loc[dc <= pd.Timestamp(anchor_d)].tail(max(3, days))
    if sub.empty:
        return 0.0, 0.0
    # 仅用「净占比」列，避免「净额」量级过大撑爆朴素贝叶斯方差
    if "主力净流入-净占比" not in sub.columns:
        return 0.0, 0.0
    main_v = float(
        pd.to_numeric(sub["主力净流入-净占比"], errors="coerce").fillna(0.0).mean()
    )
    sup_v = 0.0
    if "超大单净流入-净占比" in sub.columns:
        sup_v = float(
            pd.to_numeric(sub["超大单净流入-净占比"], errors="coerce")
            .fillna(0.0)
            .mean()
        )
    return float(main_v), float(sup_v)


def _cached_hsgt_table(code6: str) -> pd.DataFrame | None:
    try:
        import akshare as ak
    except ImportError:
        return None
    sym6 = _normalize_code6(code6).zfill(6)
    try:
        df = ak.stock_hsgt_individual_em(symbol=sym6)
    except Exception:
        _LOG.debug("hsgt individual fetch failed code=%s", sym6, exc_info=True)
        return None
    return df if isinstance(df, pd.DataFrame) else None


def _north_chg_ratio(
    code6: str,
    anchor: str,
    days: int = 5,
    cfg: dict[str, Any] | None = None,
) -> float:
    """
    北向持仓「最近若干行」市值变化之和 / 均值市值。
    东财 RPT_MUTUAL_HOLDSTOCKNDATE_STA 曾长期停更：若数据末日远早于锚定日，则返回 0，
    避免把陈旧序列当作「当前北向」喂给模型（资金流 ext_fund_* 仍独立可用）。
    """
    anchor_d = _anchor_to_date(anchor)
    if not anchor_d:
        return 0.0
    mf = (cfg or {}).get("ml_filter") if isinstance(cfg, dict) else None
    if not isinstance(mf, dict):
        mf = {}
    try:
        max_lag = max(30, min(800, int(mf.get("external_flow_north_max_lag_days", 120))))
    except (TypeError, ValueError):
        max_lag = 120
    warn_stale = bool(mf.get("external_flow_warn_stale_north", False))

    df = _cached_hsgt_table(code6)
    if df is None or df.empty or "持股日期" not in df.columns:
        return 0.0
    dc = pd.to_datetime(df["持股日期"], errors="coerce")
    mx = dc.max()
    anchor_ts = pd.Timestamp(anchor_d)
    if pd.notna(mx) and mx < anchor_ts - timedelta(days=max_lag):
        msg = (
            "北向个股持股数据滞后于锚定日，ext_north_mv_chg_ratio 已置 0 "
            "(code=%s data_last=%s anchor=%s lag_days>=%s；"
            "东财接口停更时可依赖 ext_fund_* 或关闭 external_flow_features)"
        )
        args_w = (code6, str(mx.date()), anchor[:10], max_lag)
        if warn_stale:
            _LOG.info(msg, *args_w)
        else:
            _LOG.debug(msg, *args_w)
        return 0.0

    df2 = df.loc[dc <= anchor_ts].copy()
    if df2.shape[0] < 3:
        return 0.0
    mv = pd.to_numeric(df2.get("持股市值"), errors="coerce")
    chg = pd.to_numeric(df2.get("今日持股市值变化"), errors="coerce")
    tail = df2.tail(min(max(days, 3), 20))
    if tail.empty:
        return 0.0
    mv_tail = mv.loc[tail.index]
    chg_tail = chg.loc[tail.index]
    sum_chg = float(chg_tail.fillna(0).sum())
    mean_mv = float(mv_tail.replace(0.0, float("nan")).mean())
    if mean_mv <= 1e-6:
        denom = abs(float(mv_tail.iloc[-1])) if mv_tail.notna().any() else 0.0
    else:
        denom = mean_mv
    ratio = sum_chg / max(1.0, denom)
    return float(ratio)


@lru_cache(maxsize=256)
def _cached_lhb_dates(code6: str) -> frozenset[str]:
    """该股票历史上的龙虎榜交易日（YYYY-MM-DD）。"""
    try:
        import akshare as ak
    except ImportError:
        return frozenset()
    sym = _normalize_code6(code6).zfill(6)
    try:
        df = ak.stock_lhb_stock_detail_date_em(symbol=sym)
    except Exception:
        _LOG.debug("lhb dates fetch failed code=%s", sym, exc_info=True)
        return frozenset()
    if df.empty or "交易日" not in df.columns:
        return frozenset()
    out: set[str] = set()
    for x in df["交易日"]:
        ds = pd.to_datetime(x, errors="coerce")
        if pd.isna(ds):
            continue
        out.add(ds.strftime("%Y-%m-%d"))
    return frozenset(out)


def _anchor_yyyymmdd(anchor: str) -> str:
    d = anchor[:10].replace("-", "")
    return d if len(d) == 8 else ""


@lru_cache(maxsize=256)
def _cached_lhb_buy_detail(code6: str, yyyymmdd: str) -> float:
    """龙虎榜买方净额合计（元人民币），若无数据返回 0。"""
    if len(yyyymmdd) != 8:
        return 0.0
    try:
        import akshare as ak
    except ImportError:
        return 0.0
    sym = _normalize_code6(code6).zfill(6)
    try:
        df = ak.stock_lhb_stock_detail_em(symbol=sym, date=yyyymmdd, flag="买入")
    except Exception:
        _LOG.debug(
            "lhb detail fetch failed code=%s date=%s", code6, yyyymmdd, exc_info=True
        )
        return 0.0
    if df.empty:
        return 0.0
    if df.empty or "净额" not in df.columns:
        return 0.0
    return float(pd.to_numeric(df["净额"], errors="coerce").fillna(0).sum())


def compute_external_flow_features(
    *,
    cfg: dict[str, Any],
    code: str,
    anchor_trade_date: str,
    root: Path | None = None,
) -> dict[str, float]:
    """
    计算固定 EXTERNAL_FLOW_FEATURE_KEYS；失败则全 0。

    Parameters
    ----------
    root :
        预留参数（与历史签名一致；当前实现未使用）。
    """
    _ = root
    out = external_flow_feature_defaults()
    mf = cfg.get("ml_filter") if isinstance(cfg, dict) else None
    if not isinstance(mf, dict) or not bool(mf.get("external_flow_features_enabled")):
        return out
    c6 = _normalize_code6(code)
    if len(c6) != 6 or not c6.isdigit():
        return out
    try:
        days = max(3, min(60, int(mf.get("external_flow_days", 10))))
    except (TypeError, ValueError):
        days = 10

    anchor_s = anchor_trade_date.strip()[:10]
    fm, fs = _cached_fund_flow_aggs(c6, anchor_s, days)
    out["ext_fund_main_net_pct_mean"] = fm
    out["ext_fund_super_net_pct_mean"] = fs
    out["ext_north_mv_chg_ratio"] = _north_chg_ratio(
        c6, anchor_s, days=min(10, days), cfg=cfg
    )

    lhb_set = _cached_lhb_dates(c6)
    am = anchor_s if len(anchor_s) == 10 else ""
    ext_on = 1.0 if am and am in lhb_set else 0.0
    # 龙虎榜_sparse：仅在上榜日用明细，否则金额为 0
    net_buy = 0.0
    if ext_on > 0.5:
        ymd = _anchor_yyyymmdd(anchor_trade_date)
        net_buy = _cached_lhb_buy_detail(c6, ymd)
    out["ext_on_lhb"] = ext_on
    out["ext_lhb_net_buy_wan"] = net_buy / 10000.0
    return out


def extra_flow_features_stub(
    *,
    cfg: dict[str, Any],
    code: str,
    anchor_trade_date: str,
    root: Path | None = None,
) -> dict[str, float]:
    """与 compute_external_flow_features 等价，保留旧函数名供外部调用。"""
    return compute_external_flow_features(
        cfg=cfg, code=code, anchor_trade_date=anchor_trade_date, root=root
    )
