from __future__ import annotations

import akshare as ak
import baostock as bs
import json
import logging
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from ml_forward4_sector_strength import (
    build_excess_frac_by_stock_code,
    precompute_sector_excess_vs_sh,
    sector_strength_adjust_gate_thresholds,
    sector_strength_row_meta,
)
from ml_forward4 import FORWARD_UP_HORIZON_TRADING_DAYS
from ml_forward4_select_resolve import (
    effective_select_thresholds,
    resolve_ml_forward4_for_daily_select,
)
from position_tags import has_position_tag
from quant_core.strategies import evaluate_all_strategies
from sw_member_cache import load_stock_to_sw_map

_BS_LOGIN_OK = False
# Baostock / AkShare 非线程安全；仅在使用这些回退路径时串行化
_FALLBACK_KLINE_LOCK = threading.Lock()
_SELECTOR_RUN_CFG: dict[str, Any] | None = None


def _begin_selector_kline_run(cfg: dict[str, Any] | None) -> None:
    global _SELECTOR_RUN_CFG
    _SELECTOR_RUN_CFG = cfg if isinstance(cfg, dict) else None
    _load_df_cached.cache_clear()


def _end_selector_kline_run() -> None:
    global _SELECTOR_RUN_CFG
    _SELECTOR_RUN_CFG = None
    _load_df_cached.cache_clear()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_code_to_sw_l1(cfg: dict[str, Any] | None) -> dict[str, str]:
    """6 位代码 → 申万一级 ts_code（801xxx.SI），来自 stock_to_sw.json。"""
    try:
        from quote_tushare import configure_tushare_from_sources, resolved_stock_to_sw_path

        configure_tushare_from_sources(
            (cfg or {}).get("sources") if isinstance(cfg, dict) else None
        )
        path = resolved_stock_to_sw_path(_project_root())
    except Exception:
        path = _project_root() / "data" / "stock_to_sw.json"
    return load_stock_to_sw_map(path)


def _row_score(row: dict) -> float:
    try:
        return float(row.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


_DEFAULT_SW_L1_POOL: dict[str, Any] = {
    "enabled": False,
    "picks_per_industry": 1,
    "max_stocks": 28,
    "min_score": None,
    # 板块强度分档（需 Tushare 申万/指数日 K）；失败时回退为均匀 picks_per_industry
    "strength_tiers_enabled": False,
    "strength_lookback_days": 5,
    "use_relative_to_index": True,
    "strength_benchmark_ts_code": "000001.SH",
    "strength_fetch_sleep_sec": 0.06,
    "top_third_picks": 2,
    "mid_third_picks": 1,
    "bottom_third_max_picks": 1,
    "bottom_tier_min_score": None,
    "bottom_tier_min_score_delta": 0.5,
    "unmapped_strength_tier": "bottom",
}


def _tier_sizes_three_way(n: int) -> tuple[int, int, int]:
    """前/中/后 约各占 1/3 的个数（总和为 n）。"""
    if n <= 0:
        return 0, 0, 0
    a = n // 3
    b = n // 3
    c = n - a - b
    return a, b, c


def _rank_sw_l1_strength_tiers(
    unique_sw: list[str],
    box: dict[str, Any],
    cfg: dict[str, Any] | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """
    按行业近 n 日收益（可选减基准指数）排序，划分 top/mid/bottom 三档。
    返回 tier_by_sw；meta 含 degraded、preview 等。
    """
    from quote_tushare import (
        configure_tushare_from_sources,
        sh_index_n_day_return_pct,
        sw_l1_n_day_return_pct,
    )

    configure_tushare_from_sources(
        (cfg or {}).get("sources") if isinstance(cfg, dict) else None
    )
    n_day = max(1, int(box.get("strength_lookback_days", 5) or 5))
    use_rel = bool(box.get("use_relative_to_index", True))
    bench_code = str(box.get("strength_benchmark_ts_code") or "000001.SH").strip()
    sleep_sec = float(box.get("strength_fetch_sleep_sec", 0.06) or 0)

    bench = (
        sh_index_n_day_return_pct(n=n_day, ts_code=bench_code) if use_rel else None
    )
    use_rel_eff = bool(use_rel and bench is not None)

    scored: list[tuple[str, float | None, float | None]] = []
    for sw in unique_sw:
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        r = sw_l1_n_day_return_pct(sw, n=n_day)
        metric = (
            (float(r) - float(bench))
            if use_rel_eff and r is not None and bench is not None
            else r
        )
        scored.append((sw, r, metric))

    valid_n = sum(1 for _s, _a, m in scored if m is not None)
    need_valid = max(2, min(5, max(1, len(unique_sw) // 3)))
    degraded = len(unique_sw) > 0 and valid_n < need_valid

    meta: dict[str, Any] = {
        "benchmark_n_day_pct": None if bench is None else round(float(bench), 4),
        "benchmark_ts_code": bench_code,
        "lookback_days": n_day,
        "use_relative_effective": use_rel_eff,
        "valid_industry_returns": valid_n,
        "degraded": degraded,
        "preview": [],
    }

    tier_by_sw: dict[str, str] = {}
    if degraded or not scored:
        return tier_by_sw, meta

    scored.sort(
        key=lambda t: (t[2] is not None, t[2] if t[2] is not None else -1e18),
        reverse=True,
    )
    nt, nm, nb = _tier_sizes_three_way(len(scored))
    for i, (sw, r_abs, met) in enumerate(scored):
        if i < nt:
            tier_by_sw[sw] = "top"
        elif i < nt + nm:
            tier_by_sw[sw] = "mid"
        else:
            tier_by_sw[sw] = "bottom"
        if len(meta["preview"]) < 16:
            rel_v = None
            if met is not None and r_abs is not None and bench is not None:
                rel_v = round(float(r_abs) - float(bench), 4)
            meta["preview"].append(
                {
                    "sw_l1": sw,
                    "tier": tier_by_sw[sw],
                    "n_day_pct": None if r_abs is None else round(float(r_abs), 4),
                    "rel_bench_pct": rel_v,
                    "sort_metric": None if met is None else round(float(met), 4),
                }
            )

    meta["tier_counts"] = {"top": nt, "mid": nm, "bottom": nb}
    return tier_by_sw, meta


def _bucket_strength_tier(
    sw_key: str,
    tier_by_sw: dict[str, str],
    unmapped_default: str,
) -> str:
    if sw_key == "__UNMAPPED__":
        u = str(unmapped_default or "bottom").strip().lower()
        return u if u in ("top", "mid", "bottom") else "bottom"
    return tier_by_sw.get(sw_key, "mid")


def _quota_for_tier(tier: str, box: dict[str, Any]) -> int:
    if tier == "top":
        return max(0, int(box.get("top_third_picks", 2) or 0))
    if tier == "mid":
        return max(0, int(box.get("mid_third_picks", 1) or 0))
    return max(0, int(box.get("bottom_third_max_picks", 1) or 0))


def diversify_quality_by_sw_l1(
    quality_rows: list[dict],
    *,
    qs: dict[str, Any],
    top_n_per_strategy: int,
    cfg: dict[str, Any] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    在已通过 _classify 的「优质股」集合上，按申万一级（801xxx.SI）分组：
    - 默认：每组取 picks_per_industry，第一名低于 min_score 则跳过该组；再按 max_stocks 截断。
    - strength_tiers_enabled：按行业近 n 日强弱分三档，名额 top>mid>bottom；末档需更高分才入选。
    """
    th = qs if isinstance(qs, dict) else {}
    raw_box = th.get("sw_l1_pool")
    box: dict[str, Any] = (
        {**_DEFAULT_SW_L1_POOL, **raw_box}
        if isinstance(raw_box, dict)
        else dict(_DEFAULT_SW_L1_POOL)
    )
    if not bool(box.get("enabled", False)):
        out = sorted(quality_rows, key=_score_sort_key)[: max(1, int(top_n_per_strategy or 20))]
        return out, {"mode": "legacy_top_n", "top_n": int(top_n_per_strategy or 20)}

    picks_pi = max(1, int(box.get("picks_per_industry", 1) or 1))
    max_stocks = max(1, int(box.get("max_stocks", 25) or 25))
    min_score_raw = box.get("min_score", None)
    if min_score_raw is None:
        min_score = float(th.get("score_min_quality", 7.0) or 7.0)
    else:
        min_score = float(min_score_raw)

    btm_raw = box.get("bottom_tier_min_score", None)
    if btm_raw is None:
        bottom_tier_min_score = min_score + float(
            box.get("bottom_tier_min_score_delta", 0.5) or 0.0
        )
    else:
        bottom_tier_min_score = float(btm_raw)

    buckets: dict[str, list[dict]] = {}
    for row in quality_rows:
        if not isinstance(row, dict):
            continue
        sw = str(row.get("sw_l1") or "").strip().upper()
        if not sw:
            sw = "__UNMAPPED__"
        buckets.setdefault(sw, []).append(row)

    tier_by_sw: dict[str, str] = {}
    strength_meta: dict[str, Any] = {}
    use_strength_cfg = bool(box.get("strength_tiers_enabled", False))
    use_strength = False
    if use_strength_cfg:
        unique_sw = sorted(
            {k for k in buckets.keys() if k and k != "__UNMAPPED__"},
            key=lambda x: x,
        )
        if unique_sw:
            tier_by_sw, strength_meta = _rank_sw_l1_strength_tiers(unique_sw, box, cfg)
            use_strength = not bool(strength_meta.get("degraded"))
        else:
            use_strength = True
            strength_meta = {
                "note": "no_sw_l1_codes_in_pool",
                "degraded": False,
            }

    unmapped_tier = str(box.get("unmapped_strength_tier") or "bottom")

    picked: list[dict] = []
    skipped_industries = 0
    for sw_key, group in buckets.items():
        group_sorted = sorted(group, key=_row_score, reverse=True)
        if not group_sorted:
            continue
        top1 = _row_score(group_sorted[0])
        tier = _bucket_strength_tier(sw_key, tier_by_sw, unmapped_tier)

        if use_strength:
            quota = _quota_for_tier(tier, box)
            if tier == "bottom":
                if top1 < bottom_tier_min_score or top1 < min_score:
                    continue
                eff_quota = min(quota, 1)
            else:
                if top1 < min_score:
                    skipped_industries += 1
                    continue
                eff_quota = quota
        else:
            if top1 < min_score:
                skipped_industries += 1
                continue
            eff_quota = picks_pi

        if eff_quota <= 0:
            continue

        take = group_sorted[:eff_quota]
        take = [r for r in take if _row_score(r) >= min_score]
        for r in take:
            rr = dict(r)
            if use_strength:
                rr["sw_l1_strength_tier"] = tier
            picked.append(rr)

    picked.sort(key=_row_score, reverse=True)
    trimmed = 0
    if len(picked) > max_stocks:
        trimmed = len(picked) - max_stocks
        picked = picked[:max_stocks]

    stats: dict[str, Any] = {
        "mode": "sw_l1_diversified_strength"
        if use_strength
        else "sw_l1_diversified",
        "picks_per_industry": picks_pi,
        "max_stocks": max_stocks,
        "min_score": min_score,
        "bottom_tier_min_score": bottom_tier_min_score,
        "industry_buckets": len(buckets),
        "skipped_industries_below_min": skipped_industries,
        "trimmed_lowest": trimmed,
        "final_count": len(picked),
        "strength_tiers_enabled": bool(box.get("strength_tiers_enabled", False)),
        "strength_active": use_strength,
    }
    if use_strength_cfg and strength_meta:
        stats["strength"] = strength_meta
    return picked, stats


_DEFAULT_CLUSTER_POOL: dict[str, Any] = {
    "enabled": False,
    # True：在申万去重之后聚类；False：先聚类再申万去重
    "after_sw_l1": True,
    "n_clusters": 12,
    "picks_per_cluster": 1,
    "max_stocks": 28,
    "min_score": None,
    "random_state": None,
    "features": [
        "volatility_20d",
        "momentum_20d",
        "momentum_5d",
        "volume_ratio_5_20",
        "range_pct_20d",
    ],
}


def technical_features_from_df(df: pd.DataFrame | None) -> dict[str, float] | None:
    """
    从日 OHLCV 提取用于聚类的技术特征（波动、动量、量比、振幅等）。
    需足够历史长度（约 65 根以上）。
    """
    if df is None or len(df) < 65:
        return None
    try:
        close = df["close"].astype(float)
        vol = df["volume"].astype(float)
        ret = close.pct_change()
        vol20 = float(ret.iloc[-20:].std(ddof=0) or 0.0)
        mom20 = float(close.iloc[-1] / max(close.iloc[-21], 1e-12) - 1.0)
        mom5 = float(close.iloc[-1] / max(close.iloc[-6], 1e-12) - 1.0)
        v5 = float(vol.iloc[-5:].mean())
        if len(vol) >= 25:
            v_prev = float(vol.iloc[-25:-5].mean())
        else:
            v_prev = float(vol.iloc[:-5].mean()) if len(vol) > 5 else v5
        vol_ratio = float(v5 / v_prev) if v_prev > 1e-9 else 1.0
        tail = df.tail(20)
        hi = float(tail["high"].astype(float).max())
        lo = float(tail["low"].astype(float).min())
        lc = float(close.iloc[-1])
        range_pct = float((hi - lo) / lc) if lc > 1e-9 else 0.0
        out = {
            "volatility_20d": vol20,
            "momentum_20d": mom20,
            "momentum_5d": mom5,
            "volume_ratio_5_20": vol_ratio,
            "range_pct_20d": range_pct,
        }
        for _k, _v in list(out.items()):
            if _v != _v or abs(_v) > 1e6:
                out[_k] = 0.0
        return out
    except Exception:
        return None


def _cluster_random_state(cfg: dict[str, Any] | None, box: dict[str, Any]) -> int:
    import hashlib

    rs = box.get("random_state", None)
    if rs is not None:
        try:
            return int(rs)
        except (TypeError, ValueError):
            pass
    seed_s = str((cfg or {}).get("daily_select_sample_seed") or "").strip()
    if seed_s:
        h = hashlib.md5(seed_s.encode("utf-8")).hexdigest()
        return int(h[:8], 16) % (2**31)
    return 42


def cluster_pick_quality_rows(
    quality_rows: list[dict],
    *,
    qs: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    对优质股按技术特征做 K-means，每个簇内按 score 取前 picks_per_cluster；
    再按 max_stocks 截断。无 sklearn / 特征不足时回退为原列表。
    """
    th = qs if isinstance(qs, dict) else {}
    raw_box = th.get("cluster_pool")
    box: dict[str, Any] = (
        {**_DEFAULT_CLUSTER_POOL, **raw_box}
        if isinstance(raw_box, dict)
        else dict(_DEFAULT_CLUSTER_POOL)
    )
    if not bool(box.get("enabled", False)):
        return quality_rows, {"mode": "off"}

    min_score_raw = box.get("min_score", None)
    if min_score_raw is None:
        min_score = float(th.get("score_min_quality", 7.0) or 7.0)
    else:
        min_score = float(min_score_raw)

    feat_names = box.get("features")
    if not isinstance(feat_names, list) or not feat_names:
        feat_names = list(_DEFAULT_CLUSTER_POOL["features"])

    eligible: list[dict] = []
    for r in quality_rows:
        if not isinstance(r, dict):
            continue
        tf = r.get("tech_features")
        if isinstance(tf, dict) and tf:
            eligible.append(r)

    stats: dict[str, Any] = {
        "mode": "kmeans",
        "n_clusters_requested": int(box.get("n_clusters", 12) or 12),
        "picks_per_cluster": max(1, int(box.get("picks_per_cluster", 1) or 1)),
        "eligible_with_features": len(eligible),
        "input_count": len(quality_rows),
    }

    if len(eligible) < 2:
        stats["mode"] = "degraded_too_few_features"
        stats["note"] = "含 tech_features 的优质股不足，跳过聚类"
        return quality_rows, stats

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
    except Exception as e:
        stats["mode"] = "degraded_no_sklearn"
        stats["error"] = str(e)
        return quality_rows, stats

    X_list: list[list[float]] = []
    for r in eligible:
        tf = r.get("tech_features") or {}
        row_v: list[float] = []
        for name in feat_names:
            v = float(tf.get(name, 0.0) or 0.0)
            if v != v:
                v = 0.0
            row_v.append(v)
        X_list.append(row_v)
    X = np.asarray(X_list, dtype=float)
    n = X.shape[0]
    k_req = max(2, int(box.get("n_clusters", 12) or 12))
    k = min(k_req, n)
    picks_pc = max(1, int(box.get("picks_per_cluster", 1) or 1))
    rs = _cluster_random_state(cfg, box)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = KMeans(n_clusters=k, random_state=rs, n_init=10)
    labels = model.fit_predict(Xs)

    by_label: dict[int, list[dict]] = {}
    for lab, row in zip(labels.tolist(), eligible):
        by_label.setdefault(int(lab), []).append(row)

    picked: list[dict] = []
    for lab in sorted(by_label.keys()):
        grp = sorted(by_label[lab], key=_row_score, reverse=True)
        if not grp or _row_score(grp[0]) < min_score:
            continue
        take = grp[:picks_pc]
        take = [r for r in take if _row_score(r) >= min_score]
        for r in take:
            out = dict(r)
            out["kmeans_cluster"] = int(lab)
            out.pop("tech_features", None)
            picked.append(out)

    picked.sort(key=_row_score, reverse=True)
    max_stocks = max(1, int(box.get("max_stocks", 28) or 28))
    trimmed = 0
    if len(picked) > max_stocks:
        trimmed = len(picked) - max_stocks
        picked = picked[:max_stocks]

    stats.update(
        {
            "n_clusters_used": k,
            "clusters_nonempty": len(by_label),
            "final_count": len(picked),
            "trimmed_lowest": trimmed,
            "feature_names": list(feat_names),
        }
    )
    return picked, stats


def _score_sort_key(row: dict) -> tuple[float, float]:
    """按分数降序；同分用随机次序打破平局，避免 JSON/展示里按代码挤成一片 000/002。"""
    try:
        s = float(row.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        s = 0.0
    return (-s, random.random())


def _ensure_bs_login() -> bool:
    global _BS_LOGIN_OK
    if _BS_LOGIN_OK:
        return True
    try:
        lg = bs.login()
        _BS_LOGIN_OK = getattr(lg, "error_code", "") == "0"
    except Exception:
        _BS_LOGIN_OK = False
    return _BS_LOGIN_OK


def _safe_bs_logout() -> None:
    global _BS_LOGIN_OK
    if not _BS_LOGIN_OK:
        return
    try:
        bs.logout()
    except Exception:
        pass
    _BS_LOGIN_OK = False


def _normalize_kline_df(df):
    if df is None or df.empty:
        return None
    out = df.copy().rename(
        columns={
            "日期": "date",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
        }
    )
    for col in ("close", "high", "low", "volume"):
        if col not in out.columns:
            return None
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["close", "high", "low", "volume"])
    return out


def _selector_quant_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    qs = (cfg or {}).get("quant_selector") if isinstance(cfg, dict) else None
    return qs if isinstance(qs, dict) else {}


def _code_to_secid_tushare(code: str) -> str | None:
    c = str(code).strip().zfill(6)
    if len(c) != 6 or not c.isdigit():
        return None
    if c.startswith("6"):
        return f"1.{c}"
    return f"0.{c}"


def _kline_store_db_path(cfg: dict[str, Any] | None) -> Path | None:
    """启用中的 kline_store SQLite 路径；未启用或文件不存在则 None。"""
    ks = (cfg or {}).get("kline_store") if isinstance(cfg, dict) else None
    if not isinstance(ks, dict) or not bool(ks.get("enabled")):
        return None
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    dbp = Path(rel)
    if not dbp.is_absolute():
        dbp = _project_root() / dbp
    return dbp if dbp.is_file() else None


def _sqlite_last_bar_fresh(last_trade_date: str, max_stale_calendar_days: int) -> bool:
    """最新一根日 K 的 trade_date 距今天历日是否在允许范围内（与 sync 增量逻辑一致）。"""
    from datetime import date

    try:
        last = date.fromisoformat(str(last_trade_date).strip()[:10])
    except ValueError:
        return False
    age = (date.today() - last).days
    return age <= max(0, int(max_stale_calendar_days))


def _tushare_ohlcv_rows_to_df(
    rows: list[tuple[str, float, float, float, float, float]],
) -> pd.DataFrame | None:
    if not rows:
        return None
    raw = pd.DataFrame(
        [
            {
                "日期": str(r[0])[:10],
                "开盘": r[1],
                "最高": r[2],
                "最低": r[3],
                "收盘": r[4],
                "成交量": r[5],
            }
            for r in rows
        ]
    )
    return _normalize_kline_df(raw)


def load_df(code: str, *, lookback: int = 60, cfg: dict[str, Any] | None = None):
    qs = _selector_quant_cfg(cfg)
    use_ts = bool(qs.get("use_tushare_for_daily", True))
    if use_ts:
        try:
            from kline_store import read_last_trade_date_for_secid, read_ohlcv_tail_rows
            from quote_eastmoney import resolve_ut
            from quote_tushare import (
                configure_tushare_from_sources,
                fetch_stock_kline_rows_pro_bar,
                merge_stock_rows_with_rt_k,
                stock_rt_k_enabled,
            )

            configure_tushare_from_sources(
                (cfg or {}).get("sources") if isinstance(cfg, dict) else None
            )
            secid = _code_to_secid_tushare(code)
            if secid:
                want = max(40, int(lookback))
                src = (cfg or {}).get("sources") if isinstance(cfg, dict) else {}
                ut = resolve_ut(
                    (src.get("quote_ut") or src.get("eastmoney_ut") or "ea")
                    if isinstance(src, dict)
                    else "ea"
                )
                try:
                    max_stale = int(qs.get("max_stale_calendar_days", 2) or 2)
                except (TypeError, ValueError):
                    max_stale = 2
                max_stale = max(0, max_stale)

                if bool(qs.get("use_sqlite_cache", True)):
                    dbp = _kline_store_db_path(cfg)
                    if dbp is not None:
                        last_dt = read_last_trade_date_for_secid(dbp, secid)
                        if last_dt and _sqlite_last_bar_fresh(last_dt, max_stale):
                            rows = read_ohlcv_tail_rows(
                                dbp,
                                secid,
                                lmt=want,
                                min_rows=max(80, min(want, 252 + 70)),
                            )
                            if rows:
                                rt_on = bool(
                                    qs.get("tushare_rt_k_enabled", True)
                                ) and stock_rt_k_enabled()
                                if rt_on and want <= 400:
                                    rows = merge_stock_rows_with_rt_k(
                                        secid, rows, ut=ut
                                    )
                                df = _tushare_ohlcv_rows_to_df(rows)
                                if df is not None:
                                    df = df.tail(max(lookback, 60)).copy()
                                    if len(df) >= 30:
                                        return df

                rows = fetch_stock_kline_rows_pro_bar(secid, want)
                if rows:
                    rt_on = bool(qs.get("tushare_rt_k_enabled", True)) and stock_rt_k_enabled()
                    if rt_on and want <= 400:
                        rows = merge_stock_rows_with_rt_k(secid, rows, ut=ut)
                    df = _tushare_ohlcv_rows_to_df(rows)
                    if df is not None:
                        df = df.tail(max(lookback, 60)).copy()
                        if len(df) >= 30:
                            return df
        except Exception:
            pass

    if not use_ts:
        try:
            if _ensure_bs_login():
                with _FALLBACK_KLINE_LOCK:
                    code_prefix = "sh." + code if code.startswith("6") else "sz." + code
                    rs = bs.query_history_k_data_plus(
                        code=code_prefix,
                        start_date="2018-01-01",
                        fields="date,close,high,low,volume",
                        frequency="d",
                        adjustflag="3",
                    )
                    rows = []
                    while (rs.error_code == "0") and rs.next():
                        rows.append(rs.get_row_data())
                    df = pd.DataFrame(rows, columns=rs.fields if rows else [])
                    df = _normalize_kline_df(df)
                    if df is not None:
                        df = df.tail(max(lookback, 60)).copy()
                        if len(df) >= 30:
                            return df
        except Exception:
            pass

    try:
        with _FALLBACK_KLINE_LOCK:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily", adjust="qfq"
            ).tail(max(lookback, 60))
        df = _normalize_kline_df(df)
        if df is not None and len(df) >= 30:
            return df
    except Exception:
        pass
    return None


@lru_cache(maxsize=8192)
def _load_df_cached(code: str, lookback: int = 60) -> pd.DataFrame | None:
    """LRU 缓存 load_df；须配合 _begin_selector_kline_run(cfg) 注入 config。"""
    return load_df(code, lookback=lookback, cfg=_SELECTOR_RUN_CFG)


def get_real_score(
    code: str,
    df: pd.DataFrame | None = None,
    cfg: dict[str, Any] | None = None,
    financial_factors: dict[str, Any] | None = None,
    margin_factors: dict[str, Any] | None = None,
    top_inst_factors: dict[str, Any] | None = None,
) -> float:
    k = df if df is not None else load_df(code, lookback=120, cfg=cfg)
    if k is None or len(k) < 30:
        return 3.0
    try:
        close = float(k["close"].iloc[-1])
        ma20 = float(k["close"].rolling(20).mean().iloc[-1])
        ma60 = float(k["close"].rolling(60).mean().iloc[-1])
        trend = 8 if (close > ma20 > ma60) else (5 if close > ma20 else 2)

        high = float(k["high"].max())
        low = float(k["low"].min())
        box_pos = (close - low) / (high - low) if high != low else 0.5
        box = 7 if 0.2 < box_pos < 0.6 else 4

        volatility = float(k["close"].pct_change().std())
        vol = 6 if 0.02 < volatility < 0.08 else 3

        vol5 = float(k["volume"].rolling(5).mean().iloc[-1])
        vol20 = float(k["volume"].rolling(20).mean().iloc[-1])
        volume = 7 if vol5 > vol20 * 1.2 else 4

        qs = _selector_quant_cfg(cfg)
        fw = qs.get("factor_weights") if isinstance(qs, dict) else None
        weights = fw if isinstance(fw, dict) else {}
        w_trend = _float_cfg(weights, "trend", 3.0)
        w_box = _float_cfg(weights, "box_position", 2.0)
        w_vol = _float_cfg(weights, "volatility", 2.0)
        w_volume = _float_cfg(weights, "volume_ratio", 2.0)
        denom = max(1e-9, w_trend + w_box + w_vol + w_volume)
        total = (
            trend * w_trend
            + box * w_box
            + vol * w_vol
            + volume * w_volume
        ) / denom
        total += _factor_bonus(
            code,
            qs,
            weights,
            cfg=cfg,
            financial_factors=financial_factors,
            margin_factors=margin_factors,
            top_inst_factors=top_inst_factors,
        )
        return round(min(total, 10.0), 1)
    except Exception:
        return 3.0


def _float_cfg(box: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(box.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _as_float_or_none(v: Any) -> float | None:
    if v is None or str(v).strip() in ("", "nan", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cached_factor(
    code: str,
    enabled: bool,
    provided: dict[str, Any] | None,
    loader_name: str,
) -> dict[str, Any]:
    if not enabled:
        return {}
    if isinstance(provided, dict):
        return provided
    try:
        from quote_tushare import (
            fetch_financial_factors,
            fetch_margin_factor,
            fetch_moneyflow_individual,
            fetch_moneyflow_industry,
            fetch_top_inst_factor,
        )

        loaders = {
            "financial": fetch_financial_factors,
            "margin": fetch_margin_factor,
            "top_inst": fetch_top_inst_factor,
            "moneyflow": fetch_moneyflow_individual,
            "industry_moneyflow": fetch_moneyflow_industry,
        }
        if loader_name == "industry_moneyflow":
            from quote_tushare import load_stock_to_sw_map_for_factors

            sw_map = load_stock_to_sw_map_for_factors(_project_root())
            sw = str(sw_map.get(str(code).strip().zfill(6)[-6:] or "") or "").strip().upper()
            if not sw:
                return {}
            return fetch_moneyflow_industry(sw, cache_only=True) or {}
        return loaders[loader_name](code, cache_only=True) or {}
    except Exception:
        return {}


def _factor_bonus(
    code: str,
    qs: dict[str, Any],
    weights: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    financial_factors: dict[str, Any] | None,
    margin_factors: dict[str, Any] | None,
    top_inst_factors: dict[str, Any] | None,
) -> float:
    max_bonus = max(0.0, _float_cfg(weights, "max_bonus", 3.0))
    if max_bonus <= 0:
        return 0.0

    bonus = 0.0
    fin = _cached_factor(
        code,
        bool(qs.get("enable_financial_factors", False)),
        financial_factors,
        "financial",
    )
    if fin:
        roe = _as_float_or_none(fin.get("roe_ttm"))
        rev = _as_float_or_none(fin.get("revenue_yoy"))
        if roe is not None and roe >= _float_cfg(weights, "roe_min", 0.08):
            bonus += 1.0
        if rev is not None and rev >= _float_cfg(weights, "revenue_yoy_min", 0.10):
            bonus += 1.0

    margin = _cached_factor(
        code,
        bool(qs.get("enable_margin_factors", False)),
        margin_factors,
        "margin",
    )
    mchg = _as_float_or_none(margin.get("margin_change_pct_5d")) if margin else None
    if mchg is not None and mchg >= _float_cfg(weights, "margin_change_pct_threshold", 0.03):
        bonus += 1.0

    top = _cached_factor(
        code,
        bool(qs.get("enable_top_inst_factors", False)),
        top_inst_factors,
        "top_inst",
    )
    inst = _as_float_or_none(top.get("inst_buy_net")) if top else None
    if inst is not None and inst >= _float_cfg(weights, "inst_buy_net_threshold", 1_000_000.0):
        bonus += 1.0

    if bool(qs.get("enable_moneyflow_factors", True)):
        mf = _cached_factor(code, True, None, "moneyflow")
        net5 = _as_float_or_none(mf.get("net_main_5d")) if mf else None
        if net5 is not None:
            t1 = _float_cfg(weights, "moneyflow_individual_threshold1", 5e7)
            t2 = _float_cfg(weights, "moneyflow_individual_threshold2", 2e8)
            if net5 > t2:
                bonus += _float_cfg(weights, "moneyflow_individual_bonus2", 2.0)
            elif net5 > t1:
                bonus += _float_cfg(weights, "moneyflow_individual_bonus1", 1.0)

    if bool(qs.get("enable_industry_moneyflow_factors", True)):
        imf = _cached_factor(code, True, None, "industry_moneyflow")
        in5 = _as_float_or_none(imf.get("net_main_5d")) if imf else None
        if in5 is not None:
            t1 = _float_cfg(weights, "moneyflow_industry_threshold1", 5e8)
            t2 = _float_cfg(weights, "moneyflow_industry_threshold2", 2e9)
            if in5 > t2:
                bonus += _float_cfg(weights, "moneyflow_industry_bonus2", 2.0)
            elif in5 > t1:
                bonus += _float_cfg(weights, "moneyflow_industry_bonus1", 1.0)

    if bool(qs.get("enable_hot_stock_factors", True)):
        try:
            from quote_tushare import is_hot_stock

            if is_hot_stock(code, cache_only=True):
                bonus += _float_cfg(weights, "hot_stock_bonus", 1.0)
                try:
                    from run_alert import stock_is_dual_hot_resonance

                    _cfg = cfg if isinstance(cfg, dict) else {}
                    if stock_is_dual_hot_resonance(code, _cfg):
                        bonus += _float_cfg(weights, "hot_stock_extra_bonus", 1.0)
                except Exception:
                    pass
        except Exception:
            pass

    if bool(qs.get("enable_hot_concept_factors", True)):
        try:
            from quote_tushare import is_hot_concept_stock

            if is_hot_concept_stock(code, cache_only=True):
                bonus += _float_cfg(weights, "hot_concept_bonus", 1.0)
        except Exception:
            pass

    if bool(qs.get("enable_broker_recommend_factors", True)):
        try:
            from quote_tushare import get_broker_recommend_count

            cnt = get_broker_recommend_count(code, cache_only=True)
            c2 = int(_float_cfg(weights, "broker_recommend_count2", 5))
            c1 = int(_float_cfg(weights, "broker_recommend_count1", 2))
            if cnt >= c2:
                bonus += _float_cfg(weights, "broker_recommend_bonus2", 2.0)
            elif cnt >= c1:
                bonus += _float_cfg(weights, "broker_recommend_bonus1", 1.0)
        except Exception:
            pass

    return min(max_bonus, bonus)


_SELL_STRATEGY_ACTIONS = frozenset({"risk_reduce", "stop_loss_alert", "sell_range_high"})


def held_stock_codes_from_cfg(cfg: dict[str, Any] | None) -> frozenset[str]:
    """watchlist 中带「持仓」类标签的六位代码，用于选股过滤豁免（监控仍由 run_alert 侧保留）。"""
    out: set[str] = set()
    if not isinstance(cfg, dict):
        return frozenset()
    for w in cfg.get("watchlist") or []:
        if not isinstance(w, dict) or not has_position_tag(w):
            continue
        c = str(w.get("code") or "").strip().zfill(6)
        if len(c) == 6 and c.isdigit():
            out.add(c)
    return frozenset(out)


def _select_candidate_filters_box(th: dict[str, Any]) -> dict[str, Any]:
    raw = th.get("select_candidate_filters")
    return raw if isinstance(raw, dict) else {}


def _range_position_in_window(df: pd.DataFrame, n: int) -> float | None:
    """(收盘 - N 日最低) / (N 日最高 - N 日最低)；无效区间返回 None。"""
    if df is None or len(df) < n:
        return None
    t = df.tail(int(n))
    lo = float(t["low"].min())
    hi = float(t["high"].max())
    close = float(t["close"].iloc[-1])
    if hi <= lo:
        return None
    return (close - lo) / (hi - lo)


def _kline_dict_for_strategies(df: pd.DataFrame) -> dict[str, Any] | None:
    if df is None or len(df) < 20:
        return None
    seg = df.tail(60) if len(df) >= 60 else df
    close = seg["close"]
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    low20 = float(seg["low"].tail(20).min())
    high20 = float(seg["high"].tail(20).max())
    return {"ma5": ma5, "ma20": ma20, "low20": low20, "high20": high20}


def _max_strategy_sell_side_score(
    price: float,
    kline: dict[str, Any],
    min_score_by_strategy: dict[str, float] | None,
) -> float:
    sigs = evaluate_all_strategies(
        price, kline, min_score_by_strategy=min_score_by_strategy
    )
    mx = 0.0
    for s in sigs:
        if s.action in _SELL_STRATEGY_ACTIONS:
            mx = max(mx, float(s.score))
    return mx


def _strategy_min_score_by_strategy(cfg: dict[str, Any]) -> dict[str, float] | None:
    ss = cfg.get("strategy_signal") if isinstance(cfg.get("strategy_signal"), dict) else {}
    raw = ss.get("min_score_by_strategy")
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out or None


def _select_candidate_filter_demote_reason(
    *,
    code: str,
    df: pd.DataFrame | None,
    cfg: dict[str, Any],
    th: dict[str, Any],
    prior_bucket: str,
    prior_reason: str,
    held_codes: frozenset[str],
) -> str | None:
    """若应降为淘汰，返回 reason 字符串；否则 None。"""
    box = _select_candidate_filters_box(th)
    if not bool(box.get("enabled")):
        return None
    c6 = str(code).strip().zfill(6)
    if bool(box.get("skip_if_has_position_tag", True)) and c6 in held_codes:
        return None
    if df is None:
        return None
    try:
        n_day = int(box.get("range_lookback_days", 20))
    except (TypeError, ValueError):
        n_day = 20
    n_day = max(5, min(252, n_day))
    try:
        pos_max = float(box.get("range_position_max", 0.7))
    except (TypeError, ValueError):
        pos_max = 0.7
    try:
        sell_max = float(box.get("strategy_sell_score_max", 70.0))
    except (TypeError, ValueError):
        sell_max = 70.0

    rp = _range_position_in_window(df, n_day)
    if rp is not None and rp > pos_max:
        return (
            f"选股过滤·区间偏高｜近{n_day}日位置 {rp:.2f}＞{pos_max:.2f}｜"
            f"原{prior_bucket}：{prior_reason}"
        )

    kl = _kline_dict_for_strategies(df)
    if kl is None:
        return None
    price = float(df["close"].iloc[-1])
    ms = _strategy_min_score_by_strategy(cfg)
    sell_mx = _max_strategy_sell_side_score(price, kl, ms)
    if sell_mx >= sell_max:
        logging.getLogger(__name__).info(
            "[选股过滤·卖出分] %s 剔除 %s 候选：卖出侧参考分 %.1f≥阈值 %.1f",
            c6,
            prior_bucket,
            sell_mx,
            sell_max,
        )
        return (
            f"选股过滤·卖出侧参考分偏高｜max(策略卖出信号分)={sell_mx:.1f}≥{sell_max:.1f}｜"
            f"原{prior_bucket}：{prior_reason}"
        )
    return None


def _run_backtest_on_df(df: pd.DataFrame, years: int) -> dict:
    use_n = max(120, 252 * int(years) + 70)
    x = df.tail(use_n).copy()
    if len(x) < 80:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "样本不足"}
    x["ma20"] = x["close"].rolling(20).mean()
    x["ma60"] = x["close"].rolling(60).mean()
    x = x.dropna().reset_index(drop=True)
    if len(x) < 40:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "样本不足"}

    trades: list[float] = []
    for i in range(1, len(x)):
        ma20_prev = float(x["ma20"].iloc[i - 1])
        ma60_prev = float(x["ma60"].iloc[i - 1])
        ma20_now = float(x["ma20"].iloc[i])
        ma60_now = float(x["ma60"].iloc[i])
        if not (ma20_prev < ma60_prev and ma20_now > ma60_now):
            continue
        buy = float(x["close"].iloc[i])
        if buy <= 0:
            continue
        decided = False
        for j in range(i + 1, min(i + 20, len(x))):
            pct = (float(x["close"].iloc[j]) / buy - 1.0) * 100.0
            if pct >= 8.0:
                trades.append(8.0)
                decided = True
                break
            if pct <= -4.0:
                trades.append(-4.0)
                decided = True
                break
        if not decided:
            last_j = min(i + 20, len(x) - 1)
            pct = (float(x["close"].iloc[last_j]) / buy - 1.0) * 100.0
            trades.append(round(pct, 2))

    if not trades:
        return {"profit": 0.0, "win": 0.0, "trades": 0, "note": "无交易信号"}
    profit = round(sum(trades), 2)
    win = round(100.0 * len([t for t in trades if t > 0]) / len(trades), 1)
    return {"profit": profit, "win": win, "trades": len(trades), "note": "OK"}


def _classify(
    score: float,
    bt1: dict,
    bt3: dict,
    bt5: dict,
    *,
    th: dict[str, float],
) -> tuple[str, str]:
    p1 = float(bt1.get("profit", 0.0))
    w1 = float(bt1.get("win", 0.0))
    p3 = float(bt3.get("profit", 0.0))
    p5 = float(bt5.get("profit", 0.0))
    sq = float(th.get("score_min_quality", 7.0))
    sw = float(th.get("score_min_watch", 6.0))
    p1_min = float(th.get("profit_1y_min", 0.0))
    w1_min = float(th.get("win_1y_min", 50.0))
    p3_floor = float(th.get("profit_3y_floor", -8.0))
    if score >= sq and p1 >= p1_min and w1 >= w1_min and p3 >= p3_floor:
        return "优质股", "因子与回测双重达标"
    if score >= sw and p1 >= -3 and w1 >= 40 and p3 >= -15:
        return "观察股", "基本达标，建议继续跟踪"
    if score < 4.5:
        return "淘汰股", "当前因子偏弱"
    if w1 < 35:
        return "淘汰股", "短期胜率过低"
    if p3 < -20 or p5 < -30:
        return "淘汰股", "中长期回测回撤过大"
    return "淘汰股", "历史回测不达标"


# 低于此条数认为缓存不可用，回退 AkShare 合并列表
_MIN_STOCK_BASIC_CACHE_CODES = 500


def _load_universe_codes_and_names(
    cfg: dict[str, Any] | None,
) -> tuple[list[str], dict[str, str], str]:
    """
    全市场 A 股代码与名称（选股宇宙）。
    默认读本地 data/stock_basic_cache.json（Tushare stock_basic 快照，毫秒级）；
    未启用、文件缺失或条数过少时回退 AkShare 上交所+深交所接口。
    返回 (sorted_codes, code->name, source)，source 为 "stock_basic_cache" 或 "akshare_fallback"。
    """
    qs = _selector_quant_cfg(cfg)
    if bool(qs.get("use_stock_basic_cache_universe", True)):
        try:
            from quote_tushare import (
                configure_tushare_from_sources,
                resolved_stock_basic_cache_path,
            )
            from stock_basic_cache import load_stock_basic_cache

            configure_tushare_from_sources(
                (cfg or {}).get("sources") if isinstance(cfg, dict) else None
            )
            path = resolved_stock_basic_cache_path(_project_root())
            blob = load_stock_basic_cache(path)
            stocks = blob.get("stocks")
            if isinstance(stocks, list) and stocks:
                codes_set: set[str] = set()
                name_map: dict[str, str] = {}
                for row in stocks:
                    if not isinstance(row, dict):
                        continue
                    sym = str(row.get("symbol") or "").strip()
                    if len(sym) == 6 and sym.isdigit():
                        codes_set.add(sym)
                        nm = str(row.get("name") or "").strip()
                        if nm:
                            name_map[sym] = nm
                codes = sorted(codes_set)
                if len(codes) >= _MIN_STOCK_BASIC_CACHE_CODES:
                    return codes, name_map, "stock_basic_cache"
        except Exception:
            pass

    df_sh = ak.stock_info_sh_name_code("主板A股")
    try:
        df_sz = ak.stock_info_sz_name_code("A股")
    except Exception:
        df_sz = ak.stock_info_sz_name_code("A股列表")

    stock_list = [str(r["证券代码"]).strip() for _, r in df_sh.iterrows()]
    for _, r in df_sz.iterrows():
        c = str(r.get("证券代码") or r.get("A股代码") or "").strip()
        if c:
            stock_list.append(c)
    codes = sorted(set(stock_list))
    name_map: dict[str, str] = {}
    try:
        df_name = ak.stock_info_a_code_name()
        name_map = {
            str(x["code"]).strip(): str(x["name"]).strip()
            for _, x in df_name.iterrows()
        }
    except Exception:
        pass
    return codes, name_map, "akshare_fallback"


def _split_codes_by_board(codes: list[str]) -> tuple[list[str], list[str], list[str]]:
    """按板块拆分代码。全市场 sorted 后取前 N 只会全是 000/002 等 0 字头，300/301 与 6 字头永远进不了样本。"""
    cy: list[str] = []
    sh: list[str] = []
    sz: list[str] = []
    for raw in codes:
        c = str(raw).strip()
        if len(c) != 6 or not c.isdigit():
            continue
        if c.startswith(("300", "301")):
            cy.append(c)
        elif c.startswith("6"):
            sh.append(c)
        else:
            sz.append(c)
    cy.sort()
    sh.sort()
    sz.sort()
    return cy, sh, sz


def _filter_out_star_board_if_requested(
    stock_list: list[str],
    cfg_sel: dict[str, Any],
) -> list[str]:
    """688/689 科创板；与 stock_scanner 口径一致。"""
    qs = cfg_sel.get("quant_selector") if isinstance(cfg_sel, dict) else None
    if not isinstance(qs, dict) or not bool(qs.get("exclude_star_board", False)):
        return stock_list
    out = [c for c in stock_list if not str(c).strip().startswith(("688", "689"))]
    return out


def _allocate_proportional(sizes: list[int], max_n: int) -> list[int]:
    """把 max_n 按 sizes 比例拆成整数份（最大余额法），与 sizes 等长。"""
    total = sum(sizes)
    if total <= 0 or max_n <= 0:
        return [0] * len(sizes)
    n = min(max_n, total)
    exact = [n * s / total for s in sizes]
    floors = [int(x) for x in exact]
    rem = n - sum(floors)
    order = sorted(
        range(len(sizes)),
        key=lambda i: exact[i] - floors[i],
        reverse=True,
    )
    for k in range(rem):
        floors[order[k]] += 1
    return floors


def _proportional_random_sample(
    sz_c: list[str],
    sh_c: list[str],
    cy_c: list[str],
    max_n: int,
    *,
    rng: random.Random,
) -> list[str]:
    """
    三板块按全市场只数比例分配扫描名额，板内随机抽样；打分后全局排序，不强制每板都进优质名单。
    """
    pools = (sz_c, sh_c, cy_c)
    sizes = [len(p) for p in pools]
    total = sum(sizes)
    if total == 0:
        return []
    n = min(max_n, total)
    alloc = _allocate_proportional(sizes, n)
    alloc = [min(alloc[i], sizes[i]) for i in range(3)]
    short = n - sum(alloc)
    spare = [sizes[i] - alloc[i] for i in range(3)]
    si = 0
    while short > 0 and sum(spare) > 0:
        i = si % 3
        si += 1
        if spare[i] <= 0:
            continue
        alloc[i] += 1
        spare[i] -= 1
        short -= 1

    out: list[str] = []
    for pool, k in zip(pools, alloc):
        if k <= 0:
            continue
        if k >= len(pool):
            out.extend(pool)
        else:
            out.extend(rng.sample(pool, k))
    return out


def _summarize_ml_forward4_rows(rows: list[dict]) -> dict[str, Any]:
    nums = [
        float(r["ml_forward4_up_prob"])
        for r in rows
        if isinstance(r, dict)
        and isinstance(r.get("ml_forward4_up_prob"), (int, float))
    ]
    return {
        "rows": len(rows),
        "with_prob": len(nums),
        "mean_up_prob": round(sum(nums) / len(nums), 4) if nums else None,
    }


def _attach_ml_forward4_select(
    cfg: dict[str, Any],
    code: str,
    df: pd.DataFrame | None,
    row: dict[str, Any],
) -> None:
    """选股阶段：写入 ml_forward4_up_prob（与监控端同一 NB 模型）。"""
    mf4 = cfg.get("ml_forward4") if isinstance(cfg, dict) else None
    if not isinstance(mf4, dict) or not bool(mf4.get("enabled", False)):
        return
    try:
        from ml_forward4 import (
            compute_forward4_features_for_secid,
            compute_forward4_features_from_ohlcv_df,
            load_forward4_model_cached,
            predict_forward4_up_probability,
            resolve_forward4_model_path,
        )
    except Exception:
        row["ml_forward4_up_prob"] = None
        row["ml_forward4_err"] = "import"
        return
    root = _project_root()
    mpath = resolve_forward4_model_path(cfg, root)
    model = load_forward4_model_cached(mpath)
    if not isinstance(model, dict):
        row["ml_forward4_up_prob"] = None
        row["ml_forward4_err"] = "no_model"
        return
    try:
        min_r = int(mf4.get("min_bars_infer", 80))
    except (TypeError, ValueError):
        min_r = 80
    anchor: str | None = None
    if df is not None and not df.empty:
        if "trade_date" in df.columns:
            anchor = str(df["trade_date"].iloc[-1])[:10]
        elif "date" in df.columns:
            anchor = str(df["date"].iloc[-1])[:10]
    feats = None
    try:
        feats = compute_forward4_features_from_ohlcv_df(
            df,
            anchor_trade_date=anchor,
            min_rows=min_r,
        )
    except Exception:
        feats = None
    if feats is None:
        sid = _code_to_secid_tushare(str(code).strip())
        dbp = _kline_store_db_path(cfg if isinstance(cfg, dict) else None)
        if sid and dbp is not None and dbp.is_file():
            try:
                from kline_store import (
                    init_schema,
                    open_store_connection,
                    read_last_trade_date_for_secid,
                )

                conn = open_store_connection(dbp)
                try:
                    init_schema(conn)
                    ad_use = (anchor or "").strip()[:10]
                    if len(ad_use) != 10:
                        ad_use = (read_last_trade_date_for_secid(dbp, sid) or "")[
                            :10
                        ]
                    if len(ad_use) == 10:
                        feats = compute_forward4_features_for_secid(
                            conn, sid, ad_use, min_rows=min_r
                        )
                finally:
                    conn.close()
            except Exception:
                feats = None
    if feats is None:
        row["ml_forward4_up_prob"] = None
        if df is None or df.empty:
            row["ml_forward4_err"] = "no_kline"
        return
    try:
        p = predict_forward4_up_probability(model, feats)
    except Exception:
        row["ml_forward4_up_prob"] = None
        row["ml_forward4_err"] = "predict"
        return
    if p is None:
        row["ml_forward4_up_prob"] = None
        return
    row["ml_forward4_up_prob"] = round(float(p), 4)
    row.pop("ml_forward4_err", None)


def _opt_ml_forward4_prob_threshold(mf4: dict[str, Any], key: str) -> float | None:
    if key not in mf4:
        return None
    v = mf4.get(key)
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x < 0.0 or x > 1.0:
        return None
    return x


def _apply_ml_forward4_select_gate(
    cfg: dict[str, Any],
    bucket: str,
    row: dict[str, Any],
    *,
    gate_mins: tuple[float | None, float | None] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    在已写入 ml_forward4_up_prob 后：可选将优质→观察、观察→淘汰（不处理已淘汰）。
    无有效概率时仅当 select_strict_no_prob 为 True 才降档。
    gate_mins：每股覆盖 (优质门槛, 观察门槛)，任一为 None 时该维仍读配置。
    """
    mf4 = cfg.get("ml_forward4") if isinstance(cfg, dict) else None
    if not isinstance(mf4, dict) or not bool(mf4.get("enabled", False)):
        return bucket, row
    if not bool(mf4.get("select_gate_enabled", False)):
        return bucket, row
    qmin = _opt_ml_forward4_prob_threshold(mf4, "select_min_up_prob_quality")
    wmin = _opt_ml_forward4_prob_threshold(mf4, "select_min_up_prob_watch")
    if gate_mins is not None:
        gq, gw = gate_mins
        if gq is not None:
            qmin = gq
        if gw is not None:
            wmin = gw
    if qmin is None and wmin is None:
        return bucket, row
    strict_np = bool(mf4.get("select_strict_no_prob", False))

    def _prob() -> float | None:
        v = row.get("ml_forward4_up_prob")
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return None

    p = _prob()

    def _below(th: float | None) -> bool:
        if th is None:
            return False
        if p is None:
            return strict_np
        return p < th

    if bucket == "优质股" and _below(qmin):
        row.pop("tech_features", None)
        extra = (
            f"｜ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨估{p * 100:.1f}%<{qmin * 100:.1f}%（优质降观察）"
            if p is not None and qmin is not None
            else f"｜ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨无有效估（优质降观察）"
        )
        row["reason"] = str(row.get("reason") or "") + extra
        row["ml_forward4_gate"] = "quality_to_watch"
        return "观察股", row

    if bucket == "观察股" and _below(wmin):
        tail = (
            f"｜ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨估{p * 100:.1f}%<{wmin * 100:.1f}%（观察降淘汰）"
            if p is not None and wmin is not None
            else f"｜ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨无有效估（观察降淘汰）"
        )
        rej: dict[str, Any] = {
            "code": row.get("code"),
            "name": row.get("name"),
            "score": row.get("score"),
            "reason": str(row.get("reason") or "") + tail,
        }
        for k in ("sw_l1", "backtest", "ml_forward4_up_prob", "ml_forward4_err"):
            if k in row:
                rej[k] = row[k]
        rej["ml_forward4_gate"] = "watch_to_reject"
        return "淘汰股", rej

    return bucket, row


def _sector_ml_gate_bundle(
    cfg: dict[str, Any],
    code: str,
    sw_l1: str,
    sector_excess_frac_by_code: dict[str, float] | None,
) -> tuple[tuple[float | None, float | None] | None, dict[str, Any] | None]:
    """板块强度修正后的 (gate_mins, row_meta)；无修正时 (None, None)。"""
    if not sector_excess_frac_by_code:
        return None, None
    mf4 = cfg.get("ml_forward4") if isinstance(cfg, dict) else None
    if not isinstance(mf4, dict):
        return None, None
    ex = sector_excess_frac_by_code.get(str(code).strip())
    if ex is None:
        return None, None
    base_q = _opt_ml_forward4_prob_threshold(mf4, "select_min_up_prob_quality")
    base_w = _opt_ml_forward4_prob_threshold(mf4, "select_min_up_prob_watch")
    adj = sector_strength_adjust_gate_thresholds(mf4, float(ex))
    if adj is None:
        return None, None
    meta = sector_strength_row_meta(
        mf4,
        float(ex),
        q_before=base_q,
        w_before=base_w,
        q_after=adj[0],
        w_after=adj[1],
        sw_l1=str(sw_l1 or ""),
    )
    return adj, meta if meta else None


def _eval_one_daily_select_stock(
    code: str,
    *,
    cfg: dict[str, Any],
    name_map: dict[str, str],
    code_to_sw: dict[str, str],
    th: dict[str, Any],
    lookback: int,
    per_stock_sleep_sec: float,
    sector_excess_frac_by_code: dict[str, float] | None = None,
    held_codes: frozenset[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """单只：拉 K 线、打分、回测、分类。返回 (bucket, row)，bucket 为 优质股/观察股/淘汰股。"""
    # 使用 LRU 缓存版本自动缓存同一轮选股中的重复访问
    df = _load_df_cached(code, lookback=lookback)
    score = get_real_score(code, df=df, cfg=cfg)
    cdir = cfg.get("__selector_config_parent__") if isinstance(cfg, dict) else None
    if cdir:
        qs0 = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
        arb = qs0.get("afternoon_repeat_boost")
        if isinstance(arb, dict) and bool(arb.get("enabled")):
            try:
                from afternoon_repeat_boost import afternoon_repeat_score_bonus

                b = afternoon_repeat_score_bonus(
                    code,
                    config_parent=Path(str(cdir)),
                    box=arb,
                )
                if b > 0:
                    score = round(min(10.0, float(score) + float(b)), 1)
            except Exception:
                pass
    name = name_map.get(code, f"股票{code}")
    bt1 = (
        _run_backtest_on_df(df, 1)
        if df is not None
        else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
    )
    bt3 = (
        _run_backtest_on_df(df, 3)
        if df is not None
        else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
    )
    bt5 = (
        _run_backtest_on_df(df, 5)
        if df is not None
        else {"profit": 0, "win": 0, "trades": 0, "note": "无数据"}
    )
    bucket, reason = _classify(score, bt1, bt3, bt5, th=th)
    sw_l1 = code_to_sw.get(code, "") or ""
    _held = held_codes if held_codes is not None else frozenset()
    if bucket in ("优质股", "观察股"):
        demote_reason = _select_candidate_filter_demote_reason(
            code=code,
            df=df,
            cfg=cfg,
            th=th,
            prior_bucket=bucket,
            prior_reason=reason,
            held_codes=_held,
        )
        if demote_reason:
            rej_f: dict[str, Any] = {
                "code": code,
                "name": name,
                "score": score,
                "reason": demote_reason,
            }
            _attach_ml_forward4_select(cfg, code, df, rej_f)
            bucket, rej_f = _apply_ml_forward4_select_gate(cfg, "淘汰股", rej_f)
            if per_stock_sleep_sec > 0:
                time.sleep(per_stock_sleep_sec)
            return bucket, rej_f
    if bucket == "淘汰股":
        rej: dict[str, Any] = {
            "code": code,
            "name": name,
            "score": score,
            "reason": reason,
        }
        _attach_ml_forward4_select(cfg, code, df, rej)
        bucket, rej = _apply_ml_forward4_select_gate(cfg, bucket, rej)
        if per_stock_sleep_sec > 0:
            time.sleep(per_stock_sleep_sec)
        return bucket, rej
    row: dict[str, Any] = {
        "code": code,
        "name": name,
        "score": score,
        "sw_l1": sw_l1,
        "backtest": {"1y": bt1, "3y": bt3, "5y": bt5},
        "reason": reason,
    }
    if bucket == "优质股":
        cp_cfg = th.get("cluster_pool") if isinstance(th.get("cluster_pool"), dict) else {}
        if bool(cp_cfg.get("enabled")):
            tf = technical_features_from_df(df)
            if tf is not None:
                row["tech_features"] = tf
    gate_mins, sec_meta = _sector_ml_gate_bundle(
        cfg, code, sw_l1, sector_excess_frac_by_code
    )
    _attach_ml_forward4_select(cfg, code, df, row)
    bucket, row = _apply_ml_forward4_select_gate(
        cfg, bucket, row, gate_mins=gate_mins
    )
    if sec_meta:
        row["ml_forward4_sector_strength"] = sec_meta
    if per_stock_sleep_sec > 0:
        time.sleep(per_stock_sleep_sec)
    return bucket, row


def _daily_select_max_workers_effective(qs: dict[str, Any]) -> int:
    raw = qs.get("daily_select_max_workers", 6)
    try:
        w = int(raw)
    except (TypeError, ValueError):
        w = 6
    return max(1, min(32, w))


def run_daily_selector(
    cfg, limit=250, top_n_per_strategy=30, *, config_parent: Path | str | None = None
):
    cfg_base = cfg if isinstance(cfg, dict) else {}
    cfg_in: dict[str, Any] = dict(cfg_base)
    if config_parent is not None:
        cfg_in["__selector_config_parent__"] = str(Path(config_parent).resolve())
    mf4_resolved, mood_tier_sel = resolve_ml_forward4_for_daily_select(cfg_in)
    if mf4_resolved is not None:
        cfg_sel: dict[str, Any] = dict(cfg_in)
        cfg_sel["ml_forward4"] = mf4_resolved
    else:
        cfg_sel = cfg_in

    _begin_selector_kline_run(cfg_sel)
    try:
        return _run_daily_selector_body(
            cfg_sel,
            limit=limit,
            top_n_per_strategy=top_n_per_strategy,
            mf4_resolved=mf4_resolved,
            mood_tier_sel=mood_tier_sel,
        )
    finally:
        _end_selector_kline_run()


def _run_daily_selector_body(
    cfg_sel: dict[str, Any],
    *,
    limit=250,
    top_n_per_strategy=30,
    mf4_resolved=None,
    mood_tier_sel=None,
):
    stock_list, name_map, universe_src = _load_universe_codes_and_names(cfg_sel)
    _pre_kcb = len(stock_list)
    stock_list = _filter_out_star_board_if_requested(stock_list, cfg_sel)
    if len(stock_list) < _pre_kcb:
        print(
            f"🚫 已剔除科创板 {_pre_kcb - len(stock_list)} 只（quant_selector.exclude_star_board）",
            flush=True,
        )
    if universe_src == "stock_basic_cache":
        print(f"✅ 全市场 {len(stock_list)} 只（stock_basic 本地缓存）")
    else:
        print("⏳ 全市场列表（AkShare 回退，无可用本地 stock_basic 缓存）…")
        print(f"✅ 全市场 {len(stock_list)} 只")

    n_univ = len(stock_list)
    try:
        lim_raw = int(limit) if limit is not None else 0
    except (TypeError, ValueError):
        lim_raw = 0
    if lim_raw <= 0:
        max_scan = n_univ
    else:
        max_scan = max(60, min(lim_raw, n_univ))
    cy_c, sh_c, sz_c = _split_codes_by_board(stock_list)
    seed_s = str(cfg_sel.get("daily_select_sample_seed") or "").strip()
    if seed_s:
        rng = random.Random(seed_s)
    else:
        rng = random.Random(datetime.now().strftime("%Y%m%d"))
    # 三板块按比例抽样 + 统一打分排序；优质/观察名单纯看分数与回测，不保证每板都有
    test_list = _proportional_random_sample(sz_c, sh_c, cy_c, max_scan, rng=rng)
    if max_scan >= n_univ:
        print(f"🔎 评分+回测样本：{len(test_list)} 只（全市场 {n_univ} 只，未设数量上限）")
    else:
        print(f"🔎 评分+回测样本：{len(test_list)} 只（扫描上限 {max_scan}，全市场共 {n_univ} 只）")

    mf4_box0 = cfg_sel.get("ml_forward4") if isinstance(cfg_sel, dict) else None
    if (
        mood_tier_sel
        and isinstance(mf4_box0, dict)
        and bool(mf4_box0.get("select_gate_enabled"))
    ):
        eff0 = effective_select_thresholds(mf4_box0)
        qv = eff0["select_min_up_prob_quality"]
        wv = eff0["select_min_up_prob_watch"]
        qs_thr = "—" if qv is None else f"{qv:.2f}"
        ws_thr = "—" if wv is None else f"{wv:.2f}"
        print(
            f"🎚 ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨门槛（情绪档 {mood_tier_sel}）：优质≥{qs_thr} 观察≥{ws_thr}",
            flush=True,
        )

    quality: list[dict] = []
    watch: list[dict] = []
    reject: list[dict] = []

    qs = cfg_sel.get("quant_selector") if isinstance(cfg_sel, dict) else {}
    th = qs if isinstance(qs, dict) else {}
    held_sel_codes = held_stock_codes_from_cfg(
        cfg_sel if isinstance(cfg_sel, dict) else None
    )
    code_to_sw = _load_code_to_sw_l1(cfg_sel if isinstance(cfg_sel, dict) else None)

    sector_excess_frac_by_code: dict[str, float] | None = None
    sector_strength_summary: dict[str, Any] = {"enabled": False}
    mf4_for_ss = cfg_sel.get("ml_forward4") if isinstance(cfg_sel, dict) else None
    ss_box = (
        mf4_for_ss.get("sector_strength")
        if isinstance(mf4_for_ss, dict)
        else None
    )
    if (
        isinstance(mf4_for_ss, dict)
        and bool(mf4_for_ss.get("enabled", False))
        and bool(mf4_for_ss.get("select_gate_enabled", False))
        and isinstance(ss_box, dict)
        and bool(ss_box.get("enabled", False))
    ):
        dbp_ss = _kline_store_db_path(cfg_sel)
        if dbp_ss is not None and dbp_ss.is_file():
            try:
                lb = max(1, int(ss_box.get("lookback_days", 5) or 5))
            except (TypeError, ValueError):
                lb = 5
            bench = str(
                ss_box.get("index_benchmark_ts_code") or "000001.SH"
            ).strip()
            sw_set: set[str] = set()
            for c in test_list:
                sw = (code_to_sw.get(str(c).strip()) or "").strip().upper()
                if sw.endswith(".SI"):
                    sw_set.add(sw)
            excess_sw, bench_ret = precompute_sector_excess_vs_sh(
                cfg_sel,
                dbp_ss,
                sw_set,
                lookback_days=lb,
                index_ts_code=bench,
            )
            if bench_ret is None:
                sector_strength_summary = {
                    "enabled": True,
                    "skipped": True,
                    "reason": "no_benchmark_bars",
                }
                sector_excess_frac_by_code = None
            else:
                sector_excess_frac_by_code = build_excess_frac_by_stock_code(
                    test_list, code_to_sw, excess_sw
                )
                try:
                    thr_ss = float(ss_box.get("outperform_threshold", 0.012) or 0.012)
                except (TypeError, ValueError):
                    thr_ss = 0.012
                n_strong = sum(
                    1
                    for c in test_list
                    if sector_excess_frac_by_code.get(str(c).strip()) is not None
                    and sector_excess_frac_by_code[str(c).strip()] >= thr_ss
                )
                n_weak = sum(
                    1
                    for c in test_list
                    if sector_excess_frac_by_code.get(str(c).strip()) is not None
                    and sector_excess_frac_by_code[str(c).strip()] <= -thr_ss
                )
                sector_strength_summary = {
                    "enabled": True,
                    "lookback_days": lb,
                    "index_benchmark_ts_code": bench,
                    "benchmark_n_day_return_frac": (
                        round(float(bench_ret), 8) if bench_ret is not None else None
                    ),
                    "sw_with_excess": len(excess_sw),
                    "codes_with_excess_frac": len(sector_excess_frac_by_code),
                    "n_strong_vs_benchmark": n_strong,
                    "n_weak_vs_benchmark": n_weak,
                }
                br_s = f"{float(bench_ret) * 100:.2f}%"
                print(
                    f"📊 板块强度修正：{len(sector_excess_frac_by_code)}/{len(test_list)} 只有超额"
                    f"｜强势≥{thr_ss * 100:.1f}% {n_strong}｜弱势≤-{thr_ss * 100:.1f}% {n_weak}"
                    f"｜基准 {bench} {lb}日 {br_s}",
                    flush=True,
                )
        else:
            sector_strength_summary = {
                "enabled": True,
                "skipped": True,
                "reason": "no_kline_db",
            }

    try:
        per_sleep = float(th.get("per_stock_sleep_sec", 0.0) or 0.0)
    except (TypeError, ValueError):
        per_sleep = 0.0
    per_sleep = max(0.0, per_sleep)
    workers = _daily_select_max_workers_effective(th)
    lookback_sel = 252 * 5 + 80
    _scf = _select_candidate_filters_box(th)
    if bool(_scf.get("enabled")):
        try:
            _rl = int(_scf.get("range_lookback_days", 20))
        except (TypeError, ValueError):
            _rl = 20
        try:
            _pm = float(_scf.get("range_position_max", 0.7))
        except (TypeError, ValueError):
            _pm = 0.7
        try:
            _sm = float(_scf.get("strategy_sell_score_max", 70.0))
        except (TypeError, ValueError):
            _sm = 70.0
        _sk = "开" if bool(_scf.get("skip_if_has_position_tag", True)) else "关"
        print(
            f"🧹 选股候选过滤：近{_rl}日区间位置≤{_pm:.2f}｜"
            f"策略卖出侧参考分＜{_sm:.1f}（达阈值同等淘汰）｜持仓标签豁免{_sk}（{len(held_sel_codes)} 只）",
            flush=True,
        )
    if workers > 1:
        print(
            f"⚙️ 选股并发 {workers} 线程，每股停顿 {per_sleep}s",
            flush=True,
        )

    n_total = len(test_list)
    prog_every = max(50, min(200, n_total // 20 or 50))
    t0 = time.monotonic()
    prog_lock = threading.Lock()
    progress_state = {"done": 0}

    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # type: ignore[misc, assignment]

    use_bar = bool(th.get("progress_bar", True)) and tqdm is not None
    pbar: Any = None
    heartbeat_stop: threading.Event | None = None
    heartbeat_th: threading.Thread | None = None

    def _emit_line(msg: str) -> None:
        if pbar is not None:
            tqdm.write(msg)
        else:
            print(msg, flush=True)

    def _should_log_progress(done: int) -> bool:
        if done >= n_total:
            return True
        if done <= 10:
            return True
        if done <= 50 and done % 5 == 0:
            return True
        return done % prog_every == 0

    def _progress_line(done: int) -> None:
        elapsed = time.monotonic() - t0
        rate = done / elapsed if elapsed > 0 else 0.0
        eta = (n_total - done) / rate if rate > 0 else 0.0
        _emit_line(
            f"   … 选股进度 {done}/{n_total}（约 {rate:.1f} 只/秒，"
            f"剩余约 {eta / 60:.1f} 分钟）"
        )

    if use_bar:
        pbar = tqdm(
            total=n_total,
            desc="选股",
            unit="只",
            dynamic_ncols=True,
            mininterval=0.3,
            smoothing=0.05,
        )
        _emit_line(f"   … 共 {n_total} 只（下方进度条显示速率与 ETA）")
    else:
        _emit_line(
            f"   … 开始拉取 K 线（共 {n_total} 只；每 10 秒刷新状态，"
            f"本地库命中会更快）"
        )

        def _heartbeat_loop() -> None:
            while heartbeat_stop is not None and not heartbeat_stop.wait(10.0):
                with prog_lock:
                    done = int(progress_state["done"])
                if done >= n_total:
                    break
                elapsed = time.monotonic() - t0
                if done <= 0:
                    _emit_line(
                        f"   … 选股进行中 0/{n_total}（已运行 {elapsed:.0f} 秒，"
                        f"正在拉取首批 K 线…）"
                    )
                else:
                    rate = done / elapsed if elapsed > 0 else 0.0
                    eta = (n_total - done) / rate if rate > 0 else 0.0
                    _emit_line(
                        f"   … 选股进行中 {done}/{n_total}（约 {rate:.1f} 只/秒，"
                        f"剩余约 {eta / 60:.1f} 分钟）"
                    )

        heartbeat_stop = threading.Event()
        heartbeat_th = threading.Thread(
            target=_heartbeat_loop,
            name="selector-progress-heartbeat",
            daemon=True,
        )
        heartbeat_th.start()

    def _tick_progress(n: int = 1) -> None:
        if pbar is not None:
            pbar.update(n)
            return
        with prog_lock:
            progress_state["done"] += n
            done = int(progress_state["done"])
        if _should_log_progress(done):
            _progress_line(done)

    try:
        if workers <= 1:
            for i, code in enumerate(test_list):
                bucket, row = _eval_one_daily_select_stock(
                    code,
                    cfg=cfg_sel if isinstance(cfg_sel, dict) else {},
                    name_map=name_map,
                    code_to_sw=code_to_sw,
                    th=th,
                    lookback=lookback_sel,
                    per_stock_sleep_sec=per_sleep,
                    sector_excess_frac_by_code=sector_excess_frac_by_code,
                    held_codes=held_sel_codes,
                )
                if bucket == "优质股":
                    quality.append(row)
                elif bucket == "观察股":
                    watch.append(row)
                else:
                    reject.append(row)
                _tick_progress(1)
        else:
            results: list[tuple[int, str, dict[str, Any]]] = []

            # 批处理：分组提交任务，每组内并行，组间序列
            # 这样可以减少一次性创建的任务数，避免任务队列堆积
            batch_size = max(20, min(100, workers * 5))
            n_batches = (n_total + batch_size - 1) // batch_size

            for batch_idx in range(n_batches):
                batch_start = batch_idx * batch_size
                batch_end = min(batch_start + batch_size, n_total)
                batch_codes = [(i, test_list[i]) for i in range(batch_start, batch_end)]
                if pbar is None and (
                    batch_idx == 0
                    or batch_idx == n_batches - 1
                    or (batch_idx + 1) % 10 == 0
                ):
                    _emit_line(
                        f"   … 批次 {batch_idx + 1}/{n_batches}："
                        f"第 {batch_start + 1}–{batch_end} 只"
                    )

                def _worker(ic: tuple[int, str]) -> tuple[int, str, dict[str, Any]]:
                    idx, code = ic
                    b, r = _eval_one_daily_select_stock(
                        code,
                        cfg=cfg_sel if isinstance(cfg_sel, dict) else {},
                        name_map=name_map,
                        code_to_sw=code_to_sw,
                        th=th,
                        lookback=lookback_sel,
                        per_stock_sleep_sec=per_sleep,
                        sector_excess_frac_by_code=sector_excess_frac_by_code,
                        held_codes=held_sel_codes,
                    )
                    return idx, b, r

                with ThreadPoolExecutor(max_workers=workers) as ex:
                    batch_futures = [ex.submit(_worker, ic) for ic in batch_codes]
                    for fut in as_completed(batch_futures):
                        idx, bucket, row = fut.result()
                        results.append((idx, bucket, row))
                        _tick_progress(1)

            results.sort(key=lambda t: t[0])
            for _idx, bucket, row in results:
                if bucket == "优质股":
                    quality.append(row)
                elif bucket == "观察股":
                    watch.append(row)
                else:
                    reject.append(row)
    finally:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
            if heartbeat_th is not None:
                heartbeat_th.join(timeout=0.5)
        if pbar is not None:
            pbar.close()
        if use_bar and tqdm is not None:
            tqdm.write("")
        sys.stdout.flush()
        sys.stderr.flush()
        _safe_bs_logout()

    def _post_status(msg: str) -> None:
        line = f"   … {msg}"
        if use_bar and tqdm is not None:
            tqdm.write(line)
        else:
            print(line, flush=True)

    print(flush=True)
    _post_status("全市场扫描 100% 完成，正在汇总优质/观察股（约 1～3 分钟）…")

    _cp = th.get("cluster_pool") if isinstance(th.get("cluster_pool"), dict) else {}
    _cluster_on = bool(_cp.get("enabled"))
    _cluster_after_sw = bool(_cp.get("after_sw_l1", True))
    cluster_stats: dict[str, Any] = {"mode": "off"}
    cfg_d = cfg_sel if isinstance(cfg_sel, dict) else None

    if _cluster_on and not _cluster_after_sw:
        _post_status("技术特征 K-means 聚类（优质股预筛）…")
        quality, cluster_stats = cluster_pick_quality_rows(
            quality, qs=th, cfg=cfg_d
        )

    _post_status(
        f"申万一级行业去重（候选优质 {len(quality)} 只）…"
    )
    quality, sw_l1_stats = diversify_quality_by_sw_l1(
        quality,
        qs=th,
        top_n_per_strategy=top_n_per_strategy,
        cfg=cfg_d,
    )

    if _cluster_on and _cluster_after_sw:
        _post_status("技术特征 K-means 聚类（行业去重后）…")
        quality, cluster_stats = cluster_pick_quality_rows(
            quality, qs=th, cfg=cfg_d
        )

    if sw_l1_stats.get("mode") in ("sw_l1_diversified", "sw_l1_diversified_strength"):
        st = sw_l1_stats.get("strength") or {}
        st_note = ""
        if sw_l1_stats.get("strength_active"):
            st_note = f"，板块强度分档（{st.get('lookback_days')} 日）"
        print(
            f"📊 优质股申万一级去重：{sw_l1_stats.get('final_count')} 只"
            f"（分组 {sw_l1_stats.get('industry_buckets')}，"
            f"低于门槛整组跳过 {sw_l1_stats.get('skipped_industries_below_min')}，"
            f"超上限剔除最低分 {sw_l1_stats.get('trimmed_lowest')} 只{st_note}）",
            flush=True,
        )
    if cluster_stats.get("mode") == "kmeans":
        print(
            f"🎯 技术特征 K-means：{cluster_stats.get('final_count', len(quality))} 只"
            f"（簇数 {cluster_stats.get('n_clusters_used', '-')}"
            f"，特征样本 {cluster_stats.get('eligible_with_features', '-')}）",
            flush=True,
        )

    mf4_on = bool((cfg_sel.get("ml_forward4") or {}).get("enabled"))
    mf4_box = cfg_sel.get("ml_forward4") if isinstance(cfg_sel, dict) else None
    gate_enabled = (
        mf4_on
        and isinstance(mf4_box, dict)
        and bool(mf4_box.get("select_gate_enabled"))
    )
    f4_select_summary: dict[str, Any] = {
        "enabled": mf4_on,
        "label": f"close[T+{FORWARD_UP_HORIZON_TRADING_DAYS}]>close[T] 为 1",
        "scan_pool_with_prob": 0,
        "scan_pool_mean_up_prob": None,
        "quality": _summarize_ml_forward4_rows(quality),
        "watch": _summarize_ml_forward4_rows(watch),
        "gate": {
            "enabled": gate_enabled,
            "demote_quality_to_watch": sum(
                1
                for r in watch
                if isinstance(r, dict) and r.get("ml_forward4_gate") == "quality_to_watch"
            ),
            "demote_watch_to_reject": sum(
                1
                for r in reject
                if isinstance(r, dict) and r.get("ml_forward4_gate") == "watch_to_reject"
            ),
        },
        "select_mood_tier": mood_tier_sel,
        "select_thresholds_effective": effective_select_thresholds(
            mf4_box if isinstance(mf4_box, dict) else {}
        ),
        "sector_strength": sector_strength_summary,
    }
    if mf4_on:
        pool_rows = quality + watch + reject
        pr = [
            float(r["ml_forward4_up_prob"])
            for r in pool_rows
            if isinstance(r, dict)
            and isinstance(r.get("ml_forward4_up_prob"), (int, float))
        ]
        f4_select_summary["scan_pool_with_prob"] = len(pr)
        f4_select_summary["scan_pool_mean_up_prob"] = (
            round(sum(pr) / len(pr), 4) if pr else None
        )
        qm = f4_select_summary["quality"].get("mean_up_prob")
        wm = f4_select_summary["watch"].get("mean_up_prob")
        sm = f4_select_summary.get("scan_pool_mean_up_prob")
        print(
            f"📈 ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨（选股）：扫描均估 {sm if sm is not None else '—'}"
            f"｜有效 {f4_select_summary['scan_pool_with_prob']}/{len(test_list)}"
            f"｜优质均 {qm if qm is not None else '—'}"
            f"｜观察均 {wm if wm is not None else '—'}",
            flush=True,
        )
    if gate_enabled:
        g = f4_select_summary.get("gate") or {}
        print(
            f"🧱 ML·{FORWARD_UP_HORIZON_TRADING_DAYS}日收涨门槛：优质→观察 {g.get('demote_quality_to_watch', 0)} 只"
            f"｜观察→淘汰 {g.get('demote_watch_to_reject', 0)} 只",
            flush=True,
        )

    watch = sorted(watch, key=_score_sort_key)[: max(top_n_per_strategy, 20)]
    _post_status(f"排序观察/淘汰列表（淘汰 {len(reject)} 只）…")
    reject = sorted(reject, key=_score_sort_key)
    _post_status(
        f"汇总完成：优质 {len(quality)}｜观察 {len(watch)}｜淘汰 {len(reject)}"
    )

    try:
        _ms_out = int(th.get("max_stale_calendar_days", 2) or 2)
    except (TypeError, ValueError):
        _ms_out = 2
    _ms_out = max(0, _ms_out)

    out_th = {
        "score_min": float(th.get("score_min_quality", 7.0)),
        "score_min_watch": float(th.get("score_min_watch", 6.0)),
        "profit_1y_min": float(th.get("profit_1y_min", 0.0)),
        "win_1y_min": float(th.get("win_1y_min", 50.0)),
        "profit_3y_floor": float(th.get("profit_3y_floor", -8.0)),
        "use_tushare_for_daily": bool(th.get("use_tushare_for_daily", True)),
        "tushare_rt_k_enabled": bool(th.get("tushare_rt_k_enabled", True)),
        "use_sqlite_cache": bool(th.get("use_sqlite_cache", True)),
        "max_stale_calendar_days": _ms_out,
        "per_stock_sleep_sec": float(per_sleep),
        "daily_select_max_workers": int(workers),
        "sw_l1_pool": sw_l1_stats,
        "cluster_pool": cluster_stats,
    }
    for r in quality:
        if isinstance(r, dict):
            r.pop("tech_features", None)
    cfg_sel.pop("__selector_config_parent__", None)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scan_total": len(stock_list),
        "scan_used": len(test_list),
        "ml_forward4_select": f4_select_summary,
        "thresholds": out_th,
        "优质股": quality,
        "观察股": watch,
        "淘汰股": reject,
        "优质标的": quality,  # 兼容老键名
        "观察标的": watch,
        "淘汰标的": reject,
        "stocks": quality,  # 兼容旧读取
        "msg": "✅ 全自动联动完成：因子评分+历史回测双过滤",
    }


def save_daily_selector_result(result, output_path: Path):
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

