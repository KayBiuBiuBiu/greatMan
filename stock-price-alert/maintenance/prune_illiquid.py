#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchlist 中非持仓标的：近 N 日平均成交额（volume×close 估计，万元）过低且连续多日则移出。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest_picks_performance import code_to_secid, resolve_db_path
from kline_store import open_store_connection
from position_tags import has_position_tag


def _code6(raw: Any) -> str | None:
    s = str(raw).strip()
    if not s.isdigit() or len(s) > 6:
        return None
    return s.zfill(6)


def _avg_amount_wan(conn: Any, secid: str, lookback: int) -> float | None:
    rows = conn.execute(
        """
        SELECT volume, close
        FROM daily_klines
        WHERE secid = ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (str(secid).strip(), int(lookback)),
    ).fetchall()
    if len(rows) < int(lookback):
        return None
    s = 0.0
    for vol, clo in rows:
        v = float(vol or 0.0)
        c = float(clo or 0.0)
        s += v * c / 10000.0
    return s / float(len(rows))


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"streaks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"streaks": {}}
    if not isinstance(data, dict):
        return {"streaks": {}}
    data.setdefault("streaks", {})
    if not isinstance(data["streaks"], dict):
        data["streaks"] = {}
    return data


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_log(path: Path, msg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


def run_watchlist_liquidity_prune(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """由 run_alert 收盘后调用；返回 {"removed": [...], "tweaked": bool}。"""
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    box = oa.get("watchlist_liquidity_prune")
    if not isinstance(box, dict) or not bool(box.get("enabled")):
        return {"removed": [], "tweaked": False}

    if now is None:
        now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    lookback = max(1, int(box.get("lookback_days", 20) or 20))
    min_wan = float(box.get("min_avg_amount_wan", 5000.0) or 0.0)
    need_run = max(1, int(box.get("consecutive_days_below", 5) or 5))

    state_rel = str(box.get("state_path") or "data/liquidity_prune_state.json").strip()
    sp = Path(state_rel)
    if not sp.is_absolute():
        sp = (config_path.parent / sp).resolve()
    state = _load_state(sp)
    streaks: dict[str, Any] = state.setdefault("streaks", {})

    log_rel = str(box.get("log_path") or "data/watchlist_liquidity_prune.log").strip()
    lp = Path(log_rel)
    if not lp.is_absolute():
        lp = (config_path.parent / lp).resolve()

    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        return {"removed": [], "tweaked": False}

    db_path = resolve_db_path(cfg)
    if not db_path.is_file():
        _append_log(lp, f"[liquidity_prune] skip: no db {db_path}")
        return {"removed": [], "tweaked": False}

    removed: list[str] = []
    new_wl: list[Any] = []
    conn = open_store_connection(db_path)
    try:
        for item in wl:
            if not isinstance(item, dict):
                new_wl.append(item)
                continue
            if has_position_tag(item):
                new_wl.append(item)
                continue
            c6 = _code6(item.get("code"))
            if not c6:
                new_wl.append(item)
                continue
            try:
                sid = code_to_secid(c6)
            except Exception:
                new_wl.append(item)
                continue
            avg = _avg_amount_wan(conn, sid, lookback)
            if avg is None:
                new_wl.append(item)
                continue

            prev = streaks.get(c6)
            if not isinstance(prev, dict):
                prev = {"count": 0, "last_day": None}
            cnt = int(prev.get("count", 0) or 0)
            last_day = prev.get("last_day")

            below = avg < min_wan
            if below:
                if last_day != today:
                    cnt = cnt + 1
                streaks[c6] = {"count": cnt, "last_day": today}
                if cnt >= need_run:
                    removed.append(c6)
                    streaks.pop(c6, None)
                    _append_log(
                        lp,
                        f"remove {c6} avg_amt_wan={avg:.1f} < {min_wan} streak={cnt}",
                    )
                    continue
            else:
                streaks[c6] = {"count": 0, "last_day": today}

            new_wl.append(item)
    finally:
        conn.close()

    _save_state(sp, state)

    if not removed:
        return {"removed": [], "tweaked": False}

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["watchlist"] = new_wl
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summ = f"pruned {len(removed)} codes: {','.join(removed)}"
    _append_log(lp, f"[liquidity_prune] wrote config: {summ}")
    if bool(box.get("notify", False)):
        try:
            from email_notify import send_email_alert

            send_email_alert(
                "[watchlist] 流动性剔除",
                summ
                + f"\n规则: 近{lookback}日成交额均值(估) < {min_wan} 万，连续≥{need_run} 日；持仓标签豁免。",
                app_cfg=cfg,
            )
        except Exception:
            pass
    return {"removed": removed, "tweaked": True}
