#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记录「下午机会」列表按日出现次数；盘前选股时对 score 加小分（上限 cap），提高次日入选概率。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _hits_path(config_parent: Path, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p.resolve()
    return (config_parent / p).resolve()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": 1, "by_day": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": 1, "by_day": {}}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "by_day": {}}
    raw.setdefault("by_day", {})
    if not isinstance(raw["by_day"], dict):
        raw["by_day"] = {}
    return raw


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prune_old_days(by_day: dict[str, Any], *, retain_days: int, today: datetime) -> None:
    if retain_days <= 0:
        return
    cutoff = (today.date() - timedelta(days=retain_days)).isoformat()
    stale = [d for d in list(by_day.keys()) if str(d) < cutoff]
    for d in stale:
        del by_day[d]


def record_afternoon_opportunity_hits(
    config_parent: Path,
    codes: list[str],
    date_iso: str,
    *,
    state_rel: str = "data/afternoon_repeat_hits.json",
    retain_calendar_days: int = 45,
) -> None:
    """某日写入下午机会 codes 后调用：按日记一条（去重）。"""
    path = _hits_path(config_parent, state_rel)
    data = _load(path)
    by_day: dict[str, Any] = data["by_day"]
    day = str(date_iso).strip()[:10]
    if len(day) != 10:
        day = datetime.now().strftime("%Y-%m-%d")
    seen: set[str] = set()
    clean: list[str] = []
    for c in codes:
        s = str(c or "").strip()
        if not s.isdigit() or len(s) > 6:
            continue
        z = s.zfill(6)
        if z in seen:
            continue
        seen.add(z)
        clean.append(z)
    by_day[day] = clean
    _prune_old_days(
        by_day,
        retain_days=max(7, int(retain_calendar_days)),
        today=datetime.strptime(day, "%Y-%m-%d"),
    )
    _save(path, data)


def afternoon_repeat_score_bonus(
    code: str,
    *,
    config_parent: Path,
    box: dict[str, Any],
    today: datetime | None = None,
) -> float:
    if not isinstance(box, dict) or not bool(box.get("enabled")):
        return 0.0
    if today is None:
        today = datetime.now()
    try:
        lb = max(1, int(box.get("lookback_calendar_days", 15) or 15))
    except (TypeError, ValueError):
        lb = 15
    try:
        ppd = float(box.get("points_per_distinct_day", 0.08) or 0.08)
    except (TypeError, ValueError):
        ppd = 0.08
    try:
        mx = float(box.get("max_bonus", 0.35) or 0.35)
    except (TypeError, ValueError):
        mx = 0.35
    mx = max(0.0, min(2.0, mx))
    ppd = max(0.0, min(0.5, ppd))

    rel = str(box.get("state_path") or "data/afternoon_repeat_hits.json").strip()
    path = _hits_path(config_parent, rel)
    data = _load(path)
    by_day = data.get("by_day")
    if not isinstance(by_day, dict):
        return 0.0

    c6 = str(code or "").strip().zfill(6)
    if len(c6) != 6 or not c6.isdigit():
        return 0.0

    hits = 0
    end_d = today.date()
    for i in range(lb):
        d = (end_d - timedelta(days=i)).isoformat()
        row = by_day.get(d)
        if not isinstance(row, list):
            continue
        if c6 in {str(x).strip().zfill(6) for x in row if str(x).strip().isdigit()}:
            hits += 1

    bonus = min(mx, hits * ppd)
    return round(bonus, 3)
