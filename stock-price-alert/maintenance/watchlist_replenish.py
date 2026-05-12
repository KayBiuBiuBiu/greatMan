#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchlist 低于目标数量时，从 daily_picks 优质/观察高分行自动补入（不删不改已有项）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _code6(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s.isdigit() or len(s) > 6:
        return None
    return s.zfill(6)


def _infer_market(code: str) -> str:
    c = code.zfill(6)
    if c.startswith(("5", "6", "9")):
        return "sh"
    return "sz"


def _rows_from_picks(j: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in keys:
        rows = j.get(k)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                out.append(row)
    return out


def run_watchlist_auto_replenish(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    box = oa.get("watchlist_auto_replenish")
    if not isinstance(box, dict) or not bool(box.get("enabled")):
        return {"added": 0, "tweaked": False}

    if now is None:
        now = datetime.now()
    min_cnt = max(1, int(box.get("min_watchlist_count", 50) or 50))
    target = max(min_cnt, int(box.get("target_count", 50) or 50))
    max_add = max(1, int(box.get("max_add_per_run", 15) or 15))
    try:
        min_q = float(box.get("min_quality_score", 6.5) or 6.5)
    except (TypeError, ValueError):
        min_q = 6.5
    try:
        min_w = float(box.get("min_watch_score", 6.0) or 6.0)
    except (TypeError, ValueError):
        min_w = 6.0
    note = str(box.get("note") or "自动补充(优质/观察)").strip() or "自动补充(优质/观察)"

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    wl = raw.get("watchlist")
    if not isinstance(wl, list):
        return {"added": 0, "tweaked": False}

    existing: set[str] = set()
    n_enabled = 0
    for w in wl:
        if not isinstance(w, dict) or not bool(w.get("enabled", True)):
            continue
        c = _code6(w.get("code"))
        if c:
            existing.add(c)
        n_enabled += 1

    if n_enabled >= min_cnt:
        return {"added": 0, "tweaked": False, "watchlist_count": n_enabled}

    picks_path = config_path.parent / "daily_picks.json"
    if not picks_path.is_file():
        return {"added": 0, "tweaked": False, "reason": "no_daily_picks"}

    try:
        j = json.loads(picks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"added": 0, "tweaked": False, "reason": "daily_picks_unreadable"}

    quality_rows = _rows_from_picks(j, "优质股", "优质标的")
    watch_rows = _rows_from_picks(j, "观察股", "观察标的")

    def _score(row: dict[str, Any]) -> float:
        try:
            return float(row.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    quality_rows = [r for r in quality_rows if _score(r) >= min_q]
    watch_rows = [r for r in watch_rows if _score(r) >= min_w]
    quality_rows.sort(key=_score, reverse=True)
    watch_rows.sort(key=_score, reverse=True)

    candidates: list[dict[str, Any]] = quality_rows + watch_rows

    from stock_scanner import _watch_template

    added_n = 0
    new_entries: list[dict[str, Any]] = []
    for row in candidates:
        if n_enabled + added_n >= target:
            break
        if added_n >= max_add:
            break
        c = _code6(row.get("code"))
        if not c or c in existing:
            continue
        ent = _watch_template(note)
        ent["code"] = c
        ent["name"] = str(row.get("name") or c)
        ent["market"] = _infer_market(c)
        new_entries.append(ent)
        existing.add(c)
        added_n += 1

    if not new_entries:
        return {
            "added": 0,
            "tweaked": False,
            "watchlist_count": n_enabled,
            "reason": "no_candidates",
        }

    raw["watchlist"] = wl + new_entries
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if bool(box.get("notify", False)):
        try:
            from email_notify import send_email_alert

            send_email_alert(
                "[股价监控] watchlist 自动补充",
                f"新增 {added_n} 只（目标≥{target}，原启用 {n_enabled}）。\n"
                f"来源: {picks_path.name} 优质/观察（门槛 优质≥{min_q} 观察≥{min_w}）。",
                app_cfg=cfg,
            )
        except Exception:
            pass

    return {
        "added": added_n,
        "tweaked": True,
        "watchlist_count": n_enabled + added_n,
    }
