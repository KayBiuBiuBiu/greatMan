#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下午机会：午休（11:30–13:00）用上午实时行情，从盘前「优质股、观察股」与 config watchlist 并集中筛选，
写入 afternoon_picks.json；13:00 后控制台【下午机会·新增】展示（关键指标由 run_alert 附加行输出）。

量比说明：用近 5 根已完结日 K 的日均成交量 ×（开盘至当前分钟 / 全日约 240 分钟）估算「同时段」期望量，
再与当前半日成交量（默认 AkShare 全表现货量）对比；为工程近似，非交易所精确分时切片。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any

from midday_ops import intraday_position_from_ohlc, is_lunch_recess

_LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _box(cfg: dict[str, Any]) -> dict[str, Any]:
    b = cfg.get("afternoon_refresh")
    return b if isinstance(b, dict) else {}


def _parse_hhmm(s: str) -> dt_time:
    parts = str(s or "11:35").strip().split(":")
    h = int(parts[0]) if parts else 11
    m = int(parts[1]) if len(parts) > 1 else 0
    return dt_time(max(0, min(23, h)), max(0, min(59, m)))


def _today_iso() -> str:
    return date.today().isoformat()


def _load_picks_pools(picks_path: Path) -> dict[str, set[str]]:
    out = {
        "quality": set(),
        "watch": set(),
        "reject": set(),
    }
    if not picks_path.is_file():
        return out
    try:
        j = json.loads(picks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return out

    def _pull(key: str) -> set[str]:
        rows = j.get(key)
        s: set[str] = set()
        if not isinstance(rows, list):
            return s
        for row in rows:
            if not isinstance(row, dict):
                continue
            c = str(row.get("code") or "").strip()
            if c.isdigit() and len(c) <= 6:
                s.add(c.zfill(6))
        return s

    out["quality"] = _pull("优质股") | _pull("优质标的")
    out["watch"] = _pull("观察股") | _pull("观察标的")
    out["reject"] = _pull("淘汰股") | _pull("淘汰标的")
    return out


def _watchlist_codes(cfg: dict[str, Any], normalize_stock_code: Any) -> set[str]:
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        return set()
    s: set[str] = set()
    for w in wl:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if nc:
            s.add(nc)
    return s


def _chg_pct(q: dict[str, Any]) -> float | None:
    cr = q.get("change_pct")
    if cr is not None:
        try:
            return float(cr)
        except (TypeError, ValueError):
            pass
    pc = float(q.get("pre_close") or 0.0)
    px = float(q.get("price") or 0.0)
    if pc > 0 and px > 0:
        return (px - pc) / pc * 100.0
    return None


def _quote_for(
    code: str,
    market: str,
    prefetched: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    m = str(market or "sh").strip().lower()
    q = prefetched.get((code, m))
    return dict(q) if isinstance(q, dict) else None


def _avg_volume_5d_completed(
    code: str, market: str, *, ut: str
) -> float | None:
    """最近 5 根已完结日 K 的成交量均值。"""
    try:
        from quote_eastmoney import get_stock_kline_data
    except Exception:
        return None
    kl = get_stock_kline_data(
        code, market, ut=str(ut), lmt=20, return_closes=False
    )
    if not isinstance(kl, dict):
        return None
    vols = kl.get("volumes")
    if not isinstance(vols, list) or len(vols) < 6:
        return None
    tail = vols[:-1][-5:]
    if not tail:
        return None
    try:
        return sum(float(v or 0.0) for v in tail) / 5.0
    except (TypeError, ValueError):
        return None


def _minutes_since_morning_open() -> float:
    now = datetime.now()
    if now.weekday() >= 5:
        return 120.0
    open_am = datetime.combine(now.date(), dt_time(9, 30))
    if now < open_am:
        return 30.0
    return max(30.0, (now - open_am).total_seconds() / 60.0)


def _vol_ratio_proxy(
    today_vol: float,
    avg5_completed: float,
    *,
    full_day_minutes: float = 240.0,
) -> float | None:
    if today_vol <= 0 or avg5_completed <= 0:
        return None
    elapsed = _minutes_since_morning_open()
    expected = avg5_completed * (elapsed / full_day_minutes)
    if expected <= 1e-9:
        return None
    return today_vol / expected


def _strategy_sell_score_max_from_cfg(cfg: dict[str, Any]) -> float:
    qs = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
    scf = (
        qs.get("select_candidate_filters")
        if isinstance(qs.get("select_candidate_filters"), dict)
        else {}
    )
    try:
        return float(scf.get("strategy_sell_score_max", 70.0))
    except (TypeError, ValueError):
        return 70.0


def _afternoon_exempt_sell_score(
    code: str,
    cfg: dict[str, Any],
    watch_by: dict[str, dict[str, Any]],
) -> bool:
    """仅真实持股豁免下午机会卖出分过滤（与 run_alert 控制台逻辑一致）。"""
    _ = cfg
    r = watch_by.get(code)
    if isinstance(r, dict) and int(r.get("hold_shares") or 0) > 0:
        return True
    return False


def _afternoon_max_sell_strategy_score(
    code: str,
    market: str,
    ut: str,
    quote: dict[str, Any],
    cfg: dict[str, Any],
) -> float | None:
    try:
        from quote_eastmoney import get_stock_kline_data
        from quant_core.selector import (
            _max_strategy_sell_side_score,
            _strategy_min_score_by_strategy,
        )
    except Exception:
        return None
    kl_raw = get_stock_kline_data(
        code, market, ut=str(ut), lmt=120, return_closes=True
    )
    if not isinstance(kl_raw, dict):
        return None
    kline_pure = {x: y for x, y in kl_raw.items() if x != "closes"}
    px = float(quote.get("price") or 0)
    if px <= 0:
        return None
    try:
        return float(
            _max_strategy_sell_side_score(
                px,
                kline_pure,
                _strategy_min_score_by_strategy(cfg),
            )
        )
    except Exception:
        return None


def _akshare_volume_by_code() -> dict[str, float] | None:
    try:
        import akshare as ak  # type: ignore[import-not-found]

        df = ak.stock_zh_a_spot_em()
    except Exception as exc:
        _LOG.debug("afternoon_selector akshare spot: %s", exc)
        return None
    out: dict[str, float] = {}
    for row in df.to_dict(orient="records"):
        c = str(row.get("代码") or "").strip().zfill(6)
        if len(c) != 6:
            continue
        v = row.get("成交量")
        try:
            fv = float(v or 0.0)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            out[c] = fv
    return out if out else None


def refresh_afternoon_picks(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    state: dict[str, Any],
    prefetched_quotes: dict[tuple[str, str], dict[str, Any]],
    watch: list[dict[str, Any]],
    normalize_stock_code: Any,
    valid_code: Any,
    infer_market: Any,
) -> bool:
    """
    午休过 trigger_time 后当日执行一次：从「优质∪观察∪watchlist」中按涨幅/量比/日内位置筛选，
    写入 afternoon_picks.json。返回是否成功写入。
    """
    try:
        from run_alert import merge_full_config

        cfg = merge_full_config(dict(cfg))
    except Exception:
        pass
    box = _box(cfg)
    if not bool(box.get("enabled")):
        return False
    if not is_lunch_recess():
        return False
    if datetime.now().time() < _parse_hhmm(str(box.get("trigger_time") or "11:35")):
        return False
    if state.get("__afternoon_picks_refresh_date__") == _today_iso():
        return False

    picks_path = config_path.parent / "daily_picks.json"
    pools = _load_picks_pools(picks_path)
    candidate_pool: set[str] = set(
        pools["quality"] | pools["watch"] | _watchlist_codes(cfg, normalize_stock_code)
    )

    src = cfg.get("sources") if isinstance(cfg.get("sources"), dict) else {}
    ut = str((src.get("quote") or {}).get("ut") or "").strip() or None
    if not ut:
        try:
            from quote_eastmoney import DEFAULT_UT

            ut = DEFAULT_UT
        except Exception:
            ut = "fa5fd1943c7b386f172d6893dbfba10b"

    watch_by: dict[str, dict[str, Any]] = {}
    for w in watch:
        if not isinstance(w, dict):
            continue
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if nc and (not callable(valid_code) or valid_code(nc)):
            watch_by[nc] = w

    max_picks = max(1, int(box.get("max_picks", 20) or 20))
    try:
        min_chg = float(box.get("min_chg_pct", 2.0) or 2.0)
    except (TypeError, ValueError):
        min_chg = 2.0
    try:
        max_chg = float(box.get("max_chg_pct", 5.0) or 5.0)
    except (TypeError, ValueError):
        max_chg = 5.0
    if max_chg < min_chg:
        min_chg, max_chg = max_chg, min_chg
    try:
        min_vr = float(box.get("min_vol_ratio", 1.5) or 1.5)
    except (TypeError, ValueError):
        min_vr = 1.5
    try:
        max_intra = float(box.get("max_intraday_position", 0.7) or 0.7)
    except (TypeError, ValueError):
        max_intra = 0.7
    max_intra = max(0.05, min(0.99, max_intra))

    vol_map = (
        _akshare_volume_by_code() if bool(box.get("use_akshare_volume", True)) else None
    )

    def _mkt(c: str) -> str:
        r = watch_by.get(c)
        if isinstance(r, dict):
            return str(r.get("market") or infer_market(c) or "sh").strip().lower()
        return str(infer_market(c) or "sh").strip().lower()

    metrics_by_code: dict[str, dict[str, Any]] = {}

    for c in sorted(candidate_pool):
        mkt = _mkt(c)
        q = _quote_for(c, mkt, prefetched_quotes)
        if q is None or float(q.get("price") or 0.0) <= 0:
            continue
        chg = _chg_pct(q)
        pos = intraday_position_from_ohlc(q)
        tvol = float(vol_map.get(c, 0.0) or 0.0) if vol_map else 0.0
        avg5 = _avg_volume_5d_completed(c, mkt, ut=str(ut))
        vr = _vol_ratio_proxy(tvol, avg5) if tvol > 0 and avg5 else None
        src_pool = "watchlist"
        if c in pools["quality"]:
            src_pool = "quality"
        elif c in pools["watch"]:
            src_pool = "watch"
        metrics_by_code[c] = {
            "chg_pct": chg,
            "intraday_position": pos,
            "vol_ratio_proxy": vr,
            "volume_spot": tvol if tvol > 0 else None,
            "source_pool": src_pool,
            "_prefetch_quote": q,
        }

    sell_thr = _strategy_sell_score_max_from_cfg(cfg)
    eligible: list[tuple[str, float]] = []
    for c, m in metrics_by_code.items():
        chg = m.get("chg_pct")
        pos = m.get("intraday_position")
        vr = m.get("vol_ratio_proxy")
        if chg is None:
            continue
        if not (min_chg <= float(chg) <= max_chg):
            continue
        if pos is None:
            continue
        if float(pos) >= max_intra:
            continue
        if vr is None:
            continue
        if float(vr) <= min_vr:
            continue
        if not _afternoon_exempt_sell_score(c, cfg, watch_by):
            pq = m.get("_prefetch_quote")
            if isinstance(pq, dict) and float(pq.get("price") or 0) > 0:
                smx = _afternoon_max_sell_strategy_score(
                    c, _mkt(c), str(ut), pq, cfg
                )
                if smx is not None and smx >= sell_thr:
                    _LOG.debug(
                        "[下午机会过滤] 股票 %s 卖出分 %s >= 阈值 %s，已排除",
                        c,
                        smx,
                        sell_thr,
                    )
                    continue
        eligible.append((c, float(vr)))

    eligible.sort(key=lambda x: -x[1])
    new_codes = [c for c, _ in eligible[:max_picks]]
    new_set = set(new_codes)

    items: list[dict[str, Any]] = []
    for c in new_codes:
        row = dict(metrics_by_code[c])
        row["code"] = c
        row["role"] = "afternoon_opportunity"
        items.append(row)

    out_path = config_path.parent / "afternoon_picks.json"
    qd_codes: list[str] = []
    if bool(box.get("pm_use_afternoon_quality_pool", False)):
        qd_codes = sorted(new_set)

    payload = {
        "schema_version": 2,
        "anchor_date": _today_iso(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "afternoon_new_codes": new_codes,
        "opportunity_codes": new_codes,
        "quality_display_codes": qd_codes,
        "items": items,
        "params": {
            "min_chg_pct": min_chg,
            "max_chg_pct": max_chg,
            "min_vol_ratio": min_vr,
            "max_intraday_position": max_intra,
            "max_picks": max_picks,
            "vol_ratio_method": (
                "近5日完结日K均量×(开盘至当前分钟/240)为期望半日量，"
                "与现货成交量比；非交易所精确分时"
            ),
        },
    }
    try:
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _LOG.warning("afternoon_picks write failed: %s", exc)
        return False

    try:
        qs = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
        arb = qs.get("afternoon_repeat_boost")
        if isinstance(arb, dict) and bool(arb.get("enabled")):
            from afternoon_repeat_boost import record_afternoon_opportunity_hits

            record_afternoon_opportunity_hits(
                config_path.parent,
                new_codes,
                date_iso=_today_iso(),
                state_rel=str(arb.get("state_path") or "data/afternoon_repeat_hits.json"),
                retain_calendar_days=int(arb.get("retain_calendar_days") or 45),
            )
    except Exception:
        _LOG.debug("afternoon_repeat_boost record", exc_info=True)

    state["__afternoon_picks_refresh_date__"] = _today_iso()
    print(
        f"\n[下午机会] 已写 {out_path.name}：候选池 {len(candidate_pool)} 只｜"
        f"满足条件 {len(new_codes)} 只（涨幅 {min_chg:.1f}%～{max_chg:.1f}%｜"
        f"量比>{min_vr:.2f}｜日内位置<{max_intra:.2f}）",
        flush=True,
    )
    return True


def load_afternoon_picks(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def afternoon_anchor_matches_today(path: Path) -> bool:
    j = load_afternoon_picks(path)
    if not isinstance(j, dict):
        return False
    return str(j.get("anchor_date") or "") == _today_iso()


def _opportunity_code_list(j: dict[str, Any]) -> list[str]:
    raw = j.get("afternoon_new_codes")
    if not isinstance(raw, list):
        raw = j.get("opportunity_codes")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if s.isdigit() and len(s) <= 6:
            out.append(s.zfill(6))
    return out


def load_afternoon_opportunity_metrics_by_code(path: Path) -> dict[str, dict[str, Any]]:
    """当日 afternoon_picks.json 中机会列表各 code → items 行（供控制台附加指标）。"""
    j = load_afternoon_picks(path)
    if not isinstance(j, dict):
        return {}
    if str(j.get("anchor_date") or "") != _today_iso():
        return {}
    allow = set(_opportunity_code_list(j))
    if not allow:
        return {}
    out: dict[str, dict[str, Any]] = {}
    rows = j.get("items")
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        c = str(row.get("code") or "").strip().zfill(6)
        if len(c) == 6 and c.isdigit() and c in allow:
            out[c] = row
    return out


def quality_codes_for_pm_display(
    afternoon_path: Path,
    *,
    now: datetime,
    cfg: dict[str, Any],
) -> set[str] | None:
    """可选：pm_use_afternoon_quality_pool 为 true 时，13:00+ 用文件中 quality_display_codes 替换优质展示底集。"""
    box = _box(cfg)
    if not bool(box.get("enabled")):
        return None
    if not bool(box.get("pm_use_afternoon_quality_pool", False)):
        return None
    if now.weekday() >= 5:
        return None
    if now.time() < dt_time(13, 0):
        return None
    if not afternoon_anchor_matches_today(afternoon_path):
        return None
    j = load_afternoon_picks(afternoon_path)
    if not isinstance(j, dict):
        return None
    raw = j.get("quality_display_codes")
    if not isinstance(raw, list) or not raw:
        return None
    out: set[str] = set()
    for x in raw:
        s = str(x).strip()
        if s.isdigit() and len(s) <= 6:
            out.add(s.zfill(6))
    return out if out else None


def afternoon_new_codes_for_pm(
    afternoon_path: Path,
    *,
    now: datetime,
    cfg: dict[str, Any],
) -> set[str]:
    box = _box(cfg)
    if not bool(box.get("enabled")):
        return set()
    if now.weekday() >= 5 or now.time() < dt_time(13, 0):
        return set()
    if not afternoon_anchor_matches_today(afternoon_path):
        return set()
    j = load_afternoon_picks(afternoon_path)
    if not isinstance(j, dict):
        return set()
    return set(_opportunity_code_list(j))
