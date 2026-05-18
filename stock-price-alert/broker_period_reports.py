#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收盘后按日历触发券商交割单月报 / 半年报 / 年报（周报由 weekly_report.py 每周一负责）。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Due:
    period: str
    state_key: str
    state_value: str


def _due_broker_period_reports(now: datetime, state: dict[str, Any], oa: dict[str, Any]) -> list[_Due]:
    catch = max(1, min(10, int(oa.get("broker_period_report_catchup_days", 5) or 5)))
    today = now.date()
    out: list[_Due] = []

    if today.month == 1 and (today.day == 1 or (today.day <= catch and now.weekday() < 5)):
        yr = str(today.year - 1)
        if state.get("__broker_report_annual__") != yr:
            out.append(_Due("annual", "__broker_report_annual__", yr))
        h2k = f"{today.year - 1}-H2"
        if state.get("__broker_report_h2__") != h2k:
            out.append(_Due("h2", "__broker_report_h2__", h2k))

    if today.month == 7 and (today.day == 1 or (today.day <= catch and now.weekday() < 5)):
        h1k = f"{today.year}-H1"
        if state.get("__broker_report_h1__") != h1k:
            out.append(_Due("h1", "__broker_report_h1__", h1k))

    if today.day == 1 or (today.day <= catch and now.weekday() < 5):
        mk = today.replace(day=1) - timedelta(days=1)
        mkey = mk.strftime("%Y-%m")
        if state.get("__broker_report_month__") != mkey:
            out.append(_Due("monthly", "__broker_report_month__", mkey))

    return out


def maybe_run_broker_period_reports(
    *,
    cfg: dict[str, Any],
    root: Path,
    state: dict[str, Any],
    now: datetime,
    oa: dict[str, Any],
    state_path: Path,
) -> None:
    if not bool(oa.get("broker_period_report_enabled", True)):
        return
    from weekly_report import run_broker_period_report

    due_list = _due_broker_period_reports(now, state, oa)
    if not due_list:
        return

    dirty = False
    for due in due_list:
        try:
            run_broker_period_report(
                period=due.period,
                cfg=cfg,
                root=root,
                as_of=now.date(),
                send=bool(oa.get("broker_period_report_email_enabled", True)),
            )
            state[due.state_key] = due.state_value
            dirty = True
            _LOG.info("broker_period_report: done %s %s", due.period, due.state_value)
        except Exception as exc:
            _LOG.warning("broker_period_report %s failed: %s", due.period, exc)

    if dirty and state_path.is_file():
        try:
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            _LOG.warning("broker_period_reports: state save failed: %s", exc)
