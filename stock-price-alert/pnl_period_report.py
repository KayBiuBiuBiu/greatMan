#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月 / 半年 / 年 盈亏汇总：按 data/daily_summary_history/YYYY-MM-DD.json 的 trades 累加已实现，
并取区间内「最后一日」的浮盈、净值为快照（非多日浮盈之和）。
由 run_alert 收盘后 ops_automation 在 daily_summary 写入之后调用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def _diter(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def aggregate_trades_from_history(
    history_dir: Path, start: date, end: date
) -> dict[str, Any]:
    """读取区间内每日总结 JSON，汇总 trades.realized / 末日浮盈与净值。"""
    realized_sum = 0.0
    last_date: str | None = None
    last_unrealized: float | None = None
    last_net: float | None = None
    days_hit = 0
    days_missing = 0
    for d in _diter(start, end):
        p = history_dir / f"{d.isoformat()}.json"
        if not p.is_file():
            days_missing += 1
            continue
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _LOG.warning("pnl_period_report: skip %s: %s", p.name, exc)
            days_missing += 1
            continue
        if not isinstance(j, dict):
            days_missing += 1
            continue
        tr = j.get("trades")
        if not isinstance(tr, dict):
            days_missing += 1
            continue
        try:
            realized_sum += float(tr.get("realized_profit") or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            last_unrealized = float(tr.get("unrealized_profit") or 0.0)
        except (TypeError, ValueError):
            last_unrealized = None
        try:
            last_net = float(tr.get("net_profit") or 0.0)
        except (TypeError, ValueError):
            last_net = None
        last_date = str(j.get("date") or d.isoformat())
        days_hit += 1

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days_with_summary": days_hit,
        "calendar_days_in_range": (end - start).days + 1,
        "days_missing_json": days_missing,
        "realized_profit_sum": round(realized_sum, 2),
        "last_day": last_date,
        "last_day_unrealized": None
        if last_unrealized is None
        else round(float(last_unrealized), 4),
        "last_day_net": None if last_net is None else round(float(last_net), 2),
    }


def format_pnl_period_email(*, title: str, agg: dict[str, Any]) -> str:
    lines = [title, ""]
    lines.append(
        f"区间：{agg.get('start', '')} ～ {agg.get('end', '')}  "
        f"（有总结 {agg.get('days_with_summary', 0)} 日，缺文件 {agg.get('days_missing_json', 0)} 日）"
    )
    lines.append("")
    lines.append(
        f"· 区间内各日「已实现」之和：{agg.get('realized_profit_sum', 0)} 元"
        "（= 各日 trades.realized_profit 累加，与台账日结一致）"
    )
    lu = agg.get("last_day_unrealized")
    ln = agg.get("last_day_net")
    ld = agg.get("last_day")
    if lu is not None or ln is not None:
        lines.append("")
        lines.append(
            f"· 区间末日（{ld or '—'}）快照："
            f"浮盈估 {lu if lu is not None else '—'} 元；"
            f"当日净值口径 net {ln if ln is not None else '—'} 元"
        )
        lines.append(
            "  （浮盈/净值为该日收盘总结快照，不是多日相加；与「已实现之和」不可简单相加理解成区间总收益。）"
        )
    lines.append("")
    lines.append("数据来自 data/daily_summary_history/；未跑每日总结的日子无 JSON 则计入缺文件。")
    return "\n".join(lines)


def _prev_month_bounds(today: date) -> tuple[date, date]:
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev, last_prev


def _month_key(d0: date) -> str:
    return d0.strftime("%Y-%m")


@dataclass(frozen=True)
class _Due:
    state_key: str
    state_value: str
    subject_suffix: str
    title: str
    start: date
    end: date


def _due_reports(now: datetime, state: dict[str, Any], oa: dict[str, Any]) -> list[_Due]:
    """在「应发尚未发」时返回待发送列表（同一收盘可多条）。"""
    catch = max(1, min(10, int(oa.get("pnl_period_report_catchup_days", 5) or 5)))
    today = now.date()
    out: list[_Due] = []

    # —— 上月（每月 1 日，或次月前 catch 个工作日内补发）——
    if today.day == 1 or (today.day <= catch and now.weekday() < 5):
        p0, p1 = _prev_month_bounds(today)
        mk = _month_key(p0)
        if state.get("__pnl_report_month__") != mk:
            out.append(
                _Due(
                    state_key="__pnl_report_month__",
                    state_value=mk,
                    subject_suffix=f"月结盈亏 {mk}",
                    title=f"【月结盈亏】{mk}",
                    start=p0,
                    end=p1,
                )
            )

    y = today.year
    # —— 半年报 H1：1–6 月，7 月 1 日起（含 catch 日）——
    if today.month == 7 and (today.day == 1 or (today.day <= catch and now.weekday() < 5)):
        h1_key = f"{y}-H1"
        if state.get("__pnl_report_h1__") != h1_key:
            out.append(
                _Due(
                    state_key="__pnl_report_h1__",
                    state_value=h1_key,
                    subject_suffix=f"半年报 {y}年1-6月",
                    title=f"【半年报 · 上半年】{y}年 1 月 1 日 — 6 月 30 日",
                    start=date(y, 1, 1),
                    end=date(y, 6, 30),
                )
            )

    # —— 下半年 H2 + 年报：次年 1 月（含 catch）——
    if today.month == 1 and (today.day == 1 or (today.day <= catch and now.weekday() < 5)):
        py = y - 1
        h2_key = f"{py}-H2"
        if state.get("__pnl_report_h2__") != h2_key:
            out.append(
                _Due(
                    state_key="__pnl_report_h2__",
                    state_value=h2_key,
                    subject_suffix=f"半年报 {py}年7-12月",
                    title=f"【半年报 · 下半年】{py}年 7 月 1 日 — 12 月 31 日",
                    start=date(py, 7, 1),
                    end=date(py, 12, 31),
                )
            )
        yr_key = str(py)
        if state.get("__pnl_report_year__") != yr_key:
            out.append(
                _Due(
                    state_key="__pnl_report_year__",
                    state_value=yr_key,
                    subject_suffix=f"年结盈亏 {yr_key}年",
                    title=f"【年结盈亏】{yr_key}年 1 月 1 日 — 12 月 31 日",
                    start=date(py, 1, 1),
                    end=date(py, 12, 31),
                )
            )

    return out


def maybe_run_pnl_period_reports(
    *,
    cfg: dict[str, Any],
    root: Path,
    state: dict[str, Any],
    now: datetime,
    oa: dict[str, Any],
    state_path: Path,
) -> None:
    """收盘后调用：按配置发送月/半年/年盈亏汇总邮件，并更新 state。"""
    if not bool(oa.get("pnl_period_report_enabled", True)):
        return
    try:
        from daily_summary import notify_daily_summary
    except Exception as exc:
        _LOG.warning("pnl_period_report: import notify failed: %s", exc)
        return

    history_dir = root / "data" / "daily_summary_history"
    if not history_dir.is_dir():
        _LOG.info("pnl_period_report: history dir missing, skip")
        return

    email_on = bool(oa.get("pnl_period_report_email_enabled", False))
    due_list = _due_reports(now, state, oa)
    if not due_list:
        return

    dirty = False
    for due in due_list:
        agg = aggregate_trades_from_history(history_dir, due.start, due.end)
        body = format_pnl_period_email(title=due.title, agg=agg)
        if email_on:
            try:
                notify_daily_summary(
                    cfg,
                    subject=f"[股价监控] {due.subject_suffix}",
                    body=body,
                )
                _LOG.info(
                    "pnl_period_report: sent %s realized_sum=%s days=%s",
                    due.subject_suffix,
                    agg.get("realized_profit_sum"),
                    agg.get("days_with_summary"),
                )
            except Exception as exc:
                _LOG.warning("pnl_period_report: notify failed %s: %s", due.subject_suffix, exc)
                continue
        else:
            _LOG.info(
                "pnl_period_report: (email off) %s realized_sum=%s days=%s",
                due.subject_suffix,
                agg.get("realized_profit_sum"),
                agg.get("days_with_summary"),
            )

        state[due.state_key] = due.state_value
        dirty = True

        out_dir = root / "data" / "pnl_period_reports"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            slug = due.subject_suffix.replace(" ", "_")
            fn = f"{now.strftime('%Y-%m-%d')}_{slug}.json"
            (out_dir / fn).write_text(
                json.dumps(
                    {"due": due.subject_suffix, "aggregate": agg, "body": body},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            _LOG.warning("pnl_period_report: write json failed: %s", exc)

    if dirty:
        try:
            from run_alert import save_state

            save_state(state_path, state)
        except Exception as exc:
            _LOG.warning("pnl_period_report: save_state failed: %s", exc)
