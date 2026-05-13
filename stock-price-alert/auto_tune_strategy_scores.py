#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据终端采纳与 signal_log 统计，自动调整 strategy_signal.min_score_by_strategy。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def maybe_run_auto_tune_strategy_scores(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    root: Path,
    state: dict[str, Any],
    now: datetime | None = None,
) -> None:
    """收盘后由 ops_automation 调用：回填收益 + 按 run_on 调分。"""
    from signal_operation_feedback import (
        backfill_buy_eval_returns,
        feedback_enabled,
        feedback_section,
        run_min_score_tune_from_feedback,
    )
    run_on = str(oa.get("run_on", "weekly_friday") or "weekly_friday").strip().lower()
    try:
        backfill_buy_eval_returns(cfg, root, now=now)
    except Exception as exc:
        _LOG.warning("auto_tune_strategy_scores: backfill failed: %s", exc)
    if run_on == "weekly_friday" and now.weekday() != 4:
        return
    tune_key = f"opfb_tune_{run_on}_{now.strftime('%Y-%m-%d')}"
    if state.get("__op_feedback_tune_key__") == tune_key:
        return
    try:
        run_min_score_tune_from_feedback(
            cfg, config_path=config_path, root=root, now=now
        )
        state["__op_feedback_tune_key__"] = tune_key
    except Exception as exc:
        _LOG.warning("auto_tune_strategy_scores: tune failed: %s", exc)
