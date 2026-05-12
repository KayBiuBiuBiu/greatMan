#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""午休窗口（默认 11:30–13:00）：优质股展示过滤、策略临近提示、持仓浮盈快照、可选流动性标记。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time
from typing import Any

from position_tags import has_position_tag
from quant_core.strategies import precompute_signal_proximity_hints

_LOG = logging.getLogger(__name__)

TRADING_END_AM = dt_time(11, 30)
TRADING_START_PM = dt_time(13, 0)


def is_lunch_recess() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return TRADING_END_AM < t < TRADING_START_PM


def _midday_box(cfg: dict[str, Any]) -> dict[str, Any]:
    m = cfg.get("midday_ops")
    return m if isinstance(m, dict) else {}


def should_poll_during_lunch(cfg: dict[str, Any]) -> bool:
    box = _midday_box(cfg)
    return (
        bool(box.get("enabled"))
        and bool(box.get("poll_during_lunch", True))
        and is_lunch_recess()
    )


def _parse_hhmm(s: str) -> dt_time:
    parts = str(s or "11:35").strip().split(":")
    h = int(parts[0]) if parts else 11
    m = int(parts[1]) if len(parts) > 1 else 0
    return dt_time(max(0, min(23, h)), max(0, min(59, m)))


def _past_refresh_hhmm(box: dict[str, Any]) -> bool:
    return datetime.now().time() >= _parse_hhmm(str(box.get("run_refresh_after_hhmm") or "11:35"))


def _today_iso() -> str:
    return date.today().isoformat()


def intraday_position_from_ohlc(q: dict[str, Any]) -> float | None:
    """与 RealtimeQuoteHub 一致的日内位置：(P-L)/(H-L)。"""
    px = float(q.get("price") or 0.0)
    hi = float(q.get("high") or 0.0)
    lo = float(q.get("low") or 0.0)
    if px <= 0 or hi <= lo + 1e-9:
        return None
    return max(0.0, min(1.0, (px - lo) / (hi - lo)))


def maybe_refresh_quality_console_codes(
    cfg: dict[str, Any],
    state: dict[str, Any],
    *,
    base_qcodes: set[str],
    watch: list[dict[str, Any]],
    prefetched_quotes: dict[tuple[str, str], dict[str, Any]],
    normalize_stock_code: Any,
    valid_code: Any,
    infer_market: Any,
) -> None:
    """
    午休且过配置时间后执行一次：按批量行情 OHLC 计算日内位置，剔除过高标的；
    结果写入 state['__midday_quality_codes__']，供控制台「今日优质股」分区（不写 daily_picks.json）。
    """
    box = _midday_box(cfg)
    if not bool(box.get("enabled")):
        return
    if not is_lunch_recess() or not _past_refresh_hhmm(box):
        return
    if state.get("__midday_refresh_date__") == _today_iso():
        return

    max_pos = float(box.get("max_intraday_position", 0.85) or 0.85)
    max_pos = max(0.5, min(0.999, max_pos))

    watch_by: dict[str, dict[str, Any]] = {}
    for w in watch:
        if not isinstance(w, dict):
            continue
        raw = str(w.get("code") or "").strip()
        nc = normalize_stock_code(raw) if callable(normalize_stock_code) else None
        if nc and (not callable(valid_code) or valid_code(nc)):
            watch_by[str(nc)] = w

    final_codes: set[str] = set()
    dropped: list[str] = []

    for c in sorted(base_qcodes):
        if c not in watch_by:
            final_codes.add(c)
            continue
        rule = watch_by[c]
        mkt = str(rule.get("market") or infer_market(c) or "sh").strip().lower()
        q = prefetched_quotes.get((c, mkt)) if prefetched_quotes else None
        if not isinstance(q, dict) or float(q.get("price") or 0.0) <= 0:
            final_codes.add(c)
            continue
        pos = intraday_position_from_ohlc(q)
        if pos is None:
            final_codes.add(c)
            continue
        if pos > max_pos:
            dropped.append(f"{c} 日内位置{pos:.2f}>{max_pos:.2f}")
        else:
            final_codes.add(c)

    if not final_codes and base_qcodes:
        final_codes = set(base_qcodes)
        print(
            "\n[午休刷新] 过滤后为空，已回退为盘前优质股全表（避免无标的可展示）。",
            flush=True,
        )

    state["__midday_refresh_date__"] = _today_iso()
    state["__midday_quality_codes__"] = {
        "date": _today_iso(),
        "codes": sorted(final_codes),
        "dropped": dropped,
        "max_intraday_position": max_pos,
    }
    if dropped:
        _LOG.info(
            "midday_ops: 优质股午休过滤剔除 %s 只: %s",
            len(dropped),
            "; ".join(dropped[:12]) + ("…" if len(dropped) > 12 else ""),
        )
        print(
            f"\n[午休刷新] 已按日内位置>{max_pos:.2f} 从「今日优质股」展示集中剔除 {len(dropped)} 只"
            f"（未改磁盘 daily_picks.json）。",
            flush=True,
        )


def maybe_mark_liquidity_warnings(
    cfg: dict[str, Any],
    state: dict[str, Any],
    *,
    watch: list[dict[str, Any]],
    normalize_stock_code: Any,
) -> None:
    """可选：AkShare 全市场一次，估算等价 30 分钟成交额是否低于阈值。"""
    box = _midday_box(cfg)
    if not bool(box.get("enabled")) or not bool(box.get("liquidity_use_akshare_spot", False)):
        return
    if not is_lunch_recess() or not _past_refresh_hhmm(box):
        return
    if state.get("__midday_liquidity_mark_date__") == _today_iso():
        return

    thr = float(box.get("liquidity_warn_equiv_30m_wan", 2000.0) or 0.0)
    if thr <= 0:
        return

    try:
        import akshare as ak  # type: ignore[import-not-found]

        df = ak.stock_zh_a_spot_em()
    except Exception as exc:
        _LOG.warning("midday_ops liquidity akshare failed: %s", exc)
        return

    rows = df.to_dict(orient="records")
    amt_by_code: dict[str, float] = {}
    for row in rows:
        c = str(row.get("代码") or "").strip().zfill(6)
        if len(c) != 6:
            continue
        raw_amt = row.get("成交额")
        try:
            amt_yuan = float(raw_amt or 0.0)
        except (TypeError, ValueError):
            continue
        if amt_yuan > 0:
            amt_by_code[c] = amt_yuan

    now = datetime.now()
    open_am = datetime.combine(now.date(), dt_time(9, 30))
    elapsed_min = max(20.0, (now - open_am).total_seconds() / 60.0)
    equiv_30_factor = 30.0 / elapsed_min

    warned_msgs: list[str] = []
    warn_codes: list[str] = []
    for w in watch:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        if has_position_tag(w):
            continue
        c = normalize_stock_code(str(w.get("code") or "").strip())
        if not c:
            continue
        amt_yuan = amt_by_code.get(c)
        if amt_yuan is None or amt_yuan <= 0:
            continue
        session_wan = amt_yuan / 10000.0
        equiv_30_wan = session_wan * equiv_30_factor
        if equiv_30_wan < thr:
            warn_codes.append(c)
            warned_msgs.append(
                f"{c} 估等价30分成交额≈{equiv_30_wan:.0f}万(<{thr:.0f}万)"
            )

    state["__midday_liquidity_mark_date__"] = _today_iso()
    state["__midday_liquidity_warn_codes__"] = {
        "date": _today_iso(),
        "codes": warn_codes,
        "messages": warned_msgs,
    }
    if warned_msgs:
        print(
            f"\n[午休·流动性] 未持仓 watchlist {len(warned_msgs)} 只成交额偏弱（估算），"
            f"下午不再计入「今日优质股」展示: " + " | ".join(warned_msgs[:8])
            + (" …" if len(warned_msgs) > 8 else ""),
            flush=True,
        )


def liquidity_warn_codes(state: dict[str, Any]) -> set[str]:
    raw = state.get("__midday_liquidity_warn_codes__")
    if not isinstance(raw, dict) or raw.get("date") != _today_iso():
        return set()
    codes = raw.get("codes")
    if isinstance(codes, list) and codes:
        return {str(c).strip().zfill(6) for c in codes if str(c).strip().isdigit()}
    msgs = raw.get("messages")
    if not isinstance(msgs, list):
        return set()
    out: set[str] = set()
    for m in msgs:
        s = str(m).strip()
        if len(s) >= 6 and s[:6].isdigit():
            out.add(s[:6])
    return out


def effective_console_quality_codes(
    base: set[str],
    state: dict[str, Any],
) -> set[str]:
    """合并午休日内位置过滤 + 流动性预警剔除；与 daily_picks 文件求交。"""
    out = set(base)
    ent = state.get("__midday_quality_codes__")
    if isinstance(ent, dict) and ent.get("date") == _today_iso():
        lc = ent.get("codes")
        if isinstance(lc, list) and lc:
            cand: set[str] = set()
            for x in lc:
                s = str(x).strip()
                if s.isdigit() and len(s) <= 6:
                    cand.add(s.zfill(6))
            inter = out & cand
            if inter:
                out = inter
    out -= liquidity_warn_codes(state)
    return out


def maybe_emit_midday_console_report(
    cfg: dict[str, Any],
    state: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    effective_quality_codes: set[str],
    normalize_stock_code: Any,
) -> None:
    """持仓：策略临近价提示；持仓∩优质：开盘→现价粗略浮盈。"""
    box = _midday_box(cfg)
    if not bool(box.get("enabled")):
        return
    if not is_lunch_recess():
        return
    if state.get("__midday_report_date__") == _today_iso():
        return
    if not _past_refresh_hhmm(box):
        return

    ss = cfg.get("strategy_signal") or {}
    ms = ss.get("min_score_by_strategy") if isinstance(ss, dict) else None
    floors = ms if isinstance(ms, dict) else None

    up_pct = float(box.get("precompute_up_pct", 2.0) or 0.0)
    down_pct = float(box.get("precompute_down_pct", 2.0) or 0.0)

    lines: list[str] = []

    for pack in items:
        if not isinstance(pack, dict) or not pack.get("tagged"):
            continue
        rule = pack.get("rule") or {}
        if not isinstance(rule, dict):
            continue
        q = pack.get("q") or {}
        kl = pack.get("kline")
        if not isinstance(q, dict) or not isinstance(kl, dict):
            continue
        price = float(q.get("price") or 0.0)
        if price <= 0:
            continue
        code = normalize_stock_code(str(q.get("code") or rule.get("code") or ""))
        if not code:
            continue
        hints = precompute_signal_proximity_hints(
            price,
            kl,
            min_score_by_strategy=floors,
            up_pct=up_pct,
            down_pct=down_pct,
        )
        for h in hints[:2]:
            lines.append(f"{code} {h}")

        if code in effective_quality_codes:
            op = float(q.get("open") or 0.0)
            if op > 0:
                pnl = (price - op) / op * 100.0
                lines.append(
                    f"{code} （优质∩持仓）开盘→现价约 {pnl:+.2f}%（粗算，非佣金）"
                )

    state["__midday_report_date__"] = _today_iso()
    if not lines:
        return
    print("\n---------- 【午休复盘摘要】（当日上午快照，仅供参考）----------", flush=True)
    for ln in lines[:40]:
        print(ln, flush=True)
    if len(lines) > 40:
        print(f"… 另有 {len(lines) - 40} 条省略", flush=True)
