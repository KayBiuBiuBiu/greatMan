#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日收盘结构化总结：写入 data/daily_summary.json + 可选 history 副本；可按配置发邮件/企微。
由 run_alert ops_automation after_close 在 backtest_alerts 之后调用。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_LOG = logging.getLogger(__name__)

if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


def _z6(code: str) -> str:
    s = str(code or "").strip()
    return s.zfill(6) if s.isdigit() and len(s) <= 6 else ""


def _collect_holdings(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from position_tags import has_position_tag

    out: list[dict[str, Any]] = []
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        return out
    for w in wl:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        c = _z6(str(w.get("code") or ""))
        if not c:
            continue
        hs = int(w.get("hold_shares") or 0)
        if hs <= 0 and not has_position_tag(w):
            continue
        cost = w.get("cost_price")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        out.append(
            {
                "code": c,
                "name": str(w.get("name") or ""),
                "hold_shares": hs,
                "cost_price": cost_f,
                "tags": str(w.get("tags") or ""),
            }
        )
    return sorted(out, key=lambda x: x["code"])


def _collect_quality_watch_from_picks(picks_path: Path) -> tuple[list[dict], list[dict]]:
    quality: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    if not picks_path.is_file():
        return quality, watch
    try:
        j = json.loads(picks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _LOG.warning("daily_summary: daily_picks read failed: %s", e)
        return quality, watch

    def _rows(key: str) -> list[dict[str, Any]]:
        rows = j.get(key)
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            c = _z6(str(row.get("code") or ""))
            if not c:
                continue
            sc = row.get("score")
            try:
                scf = float(sc) if sc is not None else None
            except (TypeError, ValueError):
                scf = None
            out.append(
                {
                    "code": c,
                    "name": str(row.get("name") or ""),
                    "score": scf,
                    "reason_head": str(row.get("reason") or "").split("｜")[0][:120],
                }
            )
        return out

    quality = _rows("优质股") + _rows("优质标的")
    watch = _rows("观察股") + _rows("观察标的")
    return quality, watch


def _collect_afternoon_opportunities(afternoon_path: Path) -> list[dict[str, Any]]:
    if not afternoon_path.is_file():
        return []
    try:
        j = json.loads(afternoon_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = j.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        c = _z6(str(it.get("code") or ""))
        if not c:
            continue
        out.append(
            {
                "code": c,
                "chg_pct": it.get("chg_pct"),
                "intraday_position": it.get("intraday_position"),
                "vol_ratio_proxy": it.get("vol_ratio_proxy"),
                "source_pool": it.get("source_pool"),
            }
        )
    return out


def _collect_backtest_weekly(weekly_path: Path) -> dict[str, Any] | None:
    if not weekly_path.is_file():
        return None
    try:
        j = json.loads(weekly_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return j if isinstance(j, dict) else None


def _resolve_alert_db(cfg: dict[str, Any], root: Path) -> Path | None:
    try:
        from alert_log_store import resolve_alert_db_path

        return resolve_alert_db_path(cfg, root)
    except Exception:
        return None


def _collect_today_signals(
    cfg: dict[str, Any],
    root: Path,
    *,
    day_iso: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """当日 alert_events 摘要（止盈/止损/卖出类关键词）。"""
    dbp = _resolve_alert_db(cfg, root)
    if dbp is None or not dbp.is_file():
        return []
    start = f"{day_iso}T00:00:00"
    end = f"{day_iso}T23:59:59"
    rows: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(dbp), timeout=8.0)
        try:
            cur = conn.execute(
                """
                SELECT alert_type, code, summary, fired_iso
                FROM alert_events
                WHERE fired_iso >= ? AND fired_iso <= ?
                ORDER BY fired_iso DESC
                LIMIT ?
                """,
                (start, end, limit),
            )
            for at, code, summary, fired in cur.fetchall():
                sm = str(summary or "")
                if not any(
                    k in sm
                    for k in (
                        "止盈",
                        "止损",
                        "卖出",
                        "减仓",
                        "take_profit",
                        "stop_loss",
                        "risk_reduce",
                    )
                ) and str(at or "") not in (
                    "risk_stop_take",
                    "position_suggestion",
                ):
                    continue
                rows.append(
                    {
                        "alert_type": str(at or ""),
                        "code": str(code or "").zfill(6),
                        "summary": sm[:200],
                        "fired_iso": str(fired or ""),
                    }
                )
        finally:
            conn.close()
    except Exception as exc:
        _LOG.warning("daily_summary: alert_events query failed: %s", exc)
    return rows


def _collect_health(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"notes": []}
    ks = cfg.get("kline_store") or {}
    db_rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    dbp = Path(db_rel)
    if not dbp.is_absolute():
        dbp = root / dbp
    out["kline_db_path"] = str(dbp)
    if dbp.is_file():
        try:
            m = dbp.stat().st_mtime
            out["kline_db_mtime_iso"] = datetime.fromtimestamp(m).isoformat(
                timespec="seconds"
            )
        except OSError:
            out["kline_db_mtime_iso"] = None
    else:
        out["kline_db_mtime_iso"] = None
        out["notes"].append("kline_db_missing")

    dh = cfg.get("data_health") or {}
    hb = str(dh.get("heartbeat_path") or "").strip()
    if hb:
        hp = Path(hb)
        if not hp.is_absolute():
            hp = root / hp
        out["heartbeat_path"] = str(hp)
        if hp.is_file():
            try:
                raw = json.loads(hp.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    out["heartbeat"] = {
                        k: raw.get(k)
                        for k in ("ts", "status", "lag_days", "notes")
                        if k in raw
                    }
            except (json.JSONDecodeError, OSError):
                out["notes"].append("heartbeat_unreadable")
        else:
            out["notes"].append("heartbeat_missing")

    ph = root / "data" / "picks_history"
    if ph.is_dir():
        out["picks_history_snapshot_count"] = len(list(ph.glob("*.json")))
    else:
        out["picks_history_snapshot_count"] = 0

    return out


def build_daily_summary(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    state: dict[str, Any],
    root: Path,
    now: datetime,
) -> dict[str, Any]:
    day_iso = now.strftime("%Y-%m-%d")
    picks_path = config_path.parent / "daily_picks.json"
    afternoon_path = config_path.parent / "afternoon_picks.json"
    weekly_path = root / "weekly.json"

    quality_rows, watch_rows = _collect_quality_watch_from_picks(picks_path)
    dip_codes = state.get("__last_summary_dip_codes__")
    if not isinstance(dip_codes, list):
        dip_codes = []
    dip_codes = [str(x).strip().zfill(6) for x in dip_codes if str(x).strip().isdigit()]

    q_console = state.get("__last_summary_quality_codes__")
    if isinstance(q_console, list):
        q_console_set = [str(x).strip().zfill(6) for x in q_console if str(x).strip().isdigit()]
    else:
        q_console_set = []

    return {
        "schema_version": 1,
        "date": day_iso,
        "generated_at": now.isoformat(timespec="seconds"),
        "holdings": _collect_holdings(cfg),
        "signals_today": _collect_today_signals(cfg, root, day_iso=day_iso),
        "daily_picks_quality": quality_rows,
        "daily_picks_watch": watch_rows,
        "console_quality_codes_eod": q_console_set,
        "dip_pick_codes_eod": dip_codes,
        "afternoon_opportunities": _collect_afternoon_opportunities(afternoon_path),
        "backtest_weekly_json": _collect_backtest_weekly(weekly_path),
        "health": _collect_health(cfg, root),
    }


def save_daily_summary_json(
    summary: dict[str, Any],
    *,
    out_path: Path,
    history_dir: Path | None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if history_dir is not None:
        history_dir.mkdir(parents=True, exist_ok=True)
        d = str(summary.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        hist_path = history_dir / f"{d}.json"
        try:
            hist_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            _LOG.warning("daily_summary: history write failed: %s", exc)


def format_daily_summary_text(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"【每日总结】{summary.get('date', '')}")
    lines.append(f"生成时间: {summary.get('generated_at', '')}")
    lines.append("")
    lines.append("— 持仓 —")
    for h in summary.get("holdings") or []:
        if isinstance(h, dict):
            lines.append(
                f"  {h.get('code')} {h.get('name')} "
                f"持仓{h.get('hold_shares')} 成本{h.get('cost_price')}"
            )
    lines.append("")
    lines.append("— 当日卖出/止盈相关信号（节选）—")
    sigs = summary.get("signals_today") or []
    if not sigs:
        lines.append("  （无或未启用 alert_events）")
    else:
        for s in sigs[:30]:
            if isinstance(s, dict):
                lines.append(
                    f"  [{s.get('alert_type')}] {s.get('code')} {s.get('summary', '')[:80]}"
                )
    lines.append("")
    lines.append("— 盘前优质（daily_picks）—")
    for r in (summary.get("daily_picks_quality") or [])[:40]:
        if isinstance(r, dict):
            lines.append(f"  {r.get('code')} score={r.get('score')}")
    lines.append("")
    lines.append("— 控制台优质代码（EOD 缓存）—")
    lines.append(
        "  " + ", ".join(summary.get("console_quality_codes_eod") or [])
        or "  （空）"
    )
    lines.append("")
    lines.append("— 低吸优选代码（收盘前监控缓存）—")
    lines.append("  " + ", ".join(summary.get("dip_pick_codes_eod") or []) or "  （空）")
    lines.append("")
    lines.append("— 下午机会 —")
    for a in summary.get("afternoon_opportunities") or []:
        if isinstance(a, dict):
            lines.append(
                f"  {a.get('code')} 涨{a.get('chg_pct')}% "
                f"日内位{a.get('intraday_position')} 量比{a.get('vol_ratio_proxy')}"
            )
    lines.append("")
    lines.append("— backtest_alerts weekly.json —")
    bw = summary.get("backtest_weekly_json")
    if isinstance(bw, dict) and bw:
        lines.append(f"  updated_rows={bw.get('updated_rows')} keys={list(bw.keys())[:8]}")
    else:
        lines.append("  （无）")
    lines.append("")
    lines.append("— 健康度 —")
    h = summary.get("health") or {}
    if isinstance(h, dict):
        lines.append(f"  picks_history 快照数: {h.get('picks_history_snapshot_count')}")
        lines.append(f"  K 线库: {h.get('kline_db_mtime_iso')}")
        if h.get("notes"):
            lines.append(f"  备注: {h.get('notes')}")
    return "\n".join(lines)


def notify_daily_summary(cfg: dict[str, Any], *, subject: str, body: str) -> None:
    try:
        from email_notify import send_email_alert

        send_email_alert(subject, body, app_cfg=cfg)
    except Exception as exc:
        _LOG.warning("daily_summary: notify failed: %s", exc)


def run_daily_summary_after_close(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    state: dict[str, Any],
    root: Path,
    now: datetime,
) -> bool:
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    data_dir = root / "data"
    out_path = data_dir / "daily_summary.json"
    history_dir = data_dir / "daily_summary_history"

    try:
        summary = build_daily_summary(
            cfg=cfg,
            config_path=config_path,
            state=state,
            root=root,
            now=now,
        )
        save_daily_summary_json(summary, out_path=out_path, history_dir=history_dir)
        _LOG.info(
            "daily_summary: wrote %s + history %s.json",
            out_path.name,
            summary.get("date"),
        )
    except Exception as exc:
        _LOG.warning("daily_summary: build/save failed: %s", exc, exc_info=True)
        _emit_ops_line(cfg, f"[每日总结] 生成失败（已跳过）: {exc}")
        return False

    if not bool(oa.get("daily_summary_email_enabled", False)):
        return True
    try:
        text = format_daily_summary_text(summary)
        notify_daily_summary(
            cfg,
            subject=f"[股价监控] 每日总结 {summary.get('date', '')}",
            body=text,
        )
        _emit_ops_line(cfg, "[每日总结] 已尝试发送邮件/企微（见 notifications.remote_channel）")
    except Exception as exc:
        _LOG.warning("daily_summary: notify block failed: %s", exc)
    return True


def _emit_ops_line(_cfg: dict[str, Any], msg: str) -> None:
    _LOG.info("%s", msg)
    print(msg, flush=True)
