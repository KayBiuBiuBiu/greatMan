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
from math import isfinite
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_LOG = logging.getLogger(__name__)

if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))


def _z6(code: str) -> str:
    s = str(code or "").strip()
    return s.zfill(6) if s.isdigit() and len(s) <= 6 else ""


def _load_symbol_to_name(root: Path) -> dict[str, str]:
    """stock_basic_cache.json：symbol(6) -> name。"""
    try:
        from stock_basic_cache import default_cache_path, load_stock_basic_cache
    except Exception:
        return {}
    data = load_stock_basic_cache(default_cache_path(root))
    out: dict[str, str] = {}
    for row in data.get("stocks") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip()
        if not sym.isdigit() or len(sym) > 6:
            continue
        k = sym.zfill(6)
        nm = str(row.get("name") or "").strip()
        if nm:
            out[k] = nm
    return out


def _stock_display_name(
    code: str, watchlist_name: str, symbol_to_name: dict[str, str]
) -> str:
    """展示名：watchlist 名称 > 全市场缓存 > 代码（避免空白）。"""
    c = _z6(str(code or ""))
    wn = str(watchlist_name or "").strip()
    if wn:
        return wn
    if c and c in symbol_to_name:
        return symbol_to_name[c]
    return c or "未知"


def _padded_label(label: str, width: int) -> str:
    s = str(label or "")
    if len(s) >= width:
        return s[:width]
    return s + " " * (width - len(s))


def _report_stock_label(name: str | None, code: str | None) -> str:
    """日报正文：有证券简称且不同于代码时显示 名称(代码)，否则仅代码。"""
    c = _z6(str(code or "")) or str(code or "").strip()
    n = str(name or "").strip()
    if n and c and n != c:
        return f"{n}({c})"
    return c or n or "未知"


# 邮件/企微正文里「名称(代码)」列大致定宽（中文按字符数）
_REPORT_STOCK_COL_WIDTH = 22


def _collect_holdings(
    cfg: dict[str, Any], root: Path | None = None
) -> list[dict[str, Any]]:
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
    rows = sorted(out, key=lambda x: x["code"])
    if root is not None:
        sym = _load_symbol_to_name(root)
        for row in rows:
            row["name"] = _stock_display_name(
                str(row.get("code") or ""), str(row.get("name") or ""), sym
            )
    return rows


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


def _position_cli_entries_for_day(config_path: Path, day_iso: str) -> list[dict[str, Any]]:
    path = config_path.parent / "data" / "position_cli_log.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _LOG.warning("daily_summary: position_cli_log read failed: %s", e)
        return []
    if not isinstance(raw, list):
        return []
    prefix = str(day_iso).strip()[:10]
    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        t = str(row.get("time") or "").strip()
        if len(t) < 10 or t[:10] != prefix:
            continue
        out.append(row)
    return out


def _partition_trades_from_position_cli(
    entries: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    与 run_alert stdin 一致：
    - hold / buy / add → buys（写入或加仓股数/成本）
    - unhold / sell_clear → sells（清仓并删 config）
    - pause / sell（旧语义已迁至 pause）→ sell_monitor_pauses（仅暂停监控）
    - sell_partial / reduce → 计入 sells（减仓流水）
    - hold_watch → hold_watch_only（未改仓位）
    """
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    pauses: list[dict[str, Any]] = []
    watch_only: list[dict[str, Any]] = []
    for entry in entries:
        k = str(entry.get("kind") or "").strip().lower()
        c = _z6(str(entry.get("code") or ""))
        if not c:
            continue
        base: dict[str, Any] = {
            "time": entry.get("time"),
            "code": c,
            "name": str(entry.get("name") or ""),
        }
        if k in ("hold", "buy", "add"):
            buys.append(
                {
                    **base,
                    "hold_shares": entry.get("hold_shares"),
                    "cost_price": entry.get("cost_price"),
                    "note": entry.get("note"),
                }
            )
        elif k in ("unhold", "sell_clear"):
            sells.append(
                {
                    **base,
                    "removed_rows": entry.get("removed_rows"),
                    "note": entry.get("note"),
                }
            )
        elif k in ("sell_partial", "reduce"):
            sells.append({**base, "removed_rows": None, "note": entry.get("note")})
        elif k in ("sell", "pause"):
            pauses.append({**base, "note": entry.get("note")})
        elif k in ("hold_watch", "holdwatch"):
            watch_only.append({**base, "note": entry.get("note")})
    return buys, sells, pauses, watch_only


def _cli_operation_kind_label_cn(kind: str) -> str:
    """position_cli_log.kind → 邮件/JSON 用的简短中文标签。"""
    k = str(kind or "").strip().lower()
    return {
        "buy": "买入",
        "add": "加仓",
        "hold": "录仓",
        "reduce": "减持",
        "sell_partial": "减持",
        "unhold": "清仓",
        "sell_clear": "清仓",
        "sell": "暂停监控",
        "pause": "暂停监控",
        "hold_watch": "入监控池",
        "holdwatch": "入监控池",
    }.get(k, k or "操作")


def _collect_position_operations_today(
    config_path: Path, day_iso: str
) -> list[dict[str, Any]]:
    """当日终端持仓类指令流水（data/position_cli_log.json），按时间升序。"""
    entries = _position_cli_entries_for_day(config_path, day_iso)
    entries = sorted(entries, key=lambda r: str(r.get("time") or ""))
    out: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        k = str(row.get("kind") or "").strip().lower()
        c = _z6(str(row.get("code") or ""))
        if not c:
            continue
        item: dict[str, Any] = {
            "time": row.get("time"),
            "kind": k,
            "label": _cli_operation_kind_label_cn(k),
            "code": c,
            "name": str(row.get("name") or "").strip(),
        }
        for key in (
            "hold_shares",
            "cost_price",
            "cmd_shares",
            "cmd_cost",
            "removed_rows",
            "note",
        ):
            if key not in row:
                continue
            val = row.get(key)
            if val is None:
                continue
            if key == "cost_price" or key == "cmd_cost":
                try:
                    item[key] = round(float(val), 6)
                except (TypeError, ValueError):
                    item[key] = val
            elif key in ("hold_shares", "cmd_shares", "removed_rows"):
                try:
                    item[key] = int(val)
                except (TypeError, ValueError):
                    item[key] = val
            else:
                item[key] = val
        out.append(item)
    return out


def _format_position_operation_mail_line(entry: dict[str, Any]) -> str:
    """单行正文：时间 + 类型 + 标的 + 数量/成本等。"""
    ts = str(entry.get("time") or "").strip()
    hms = ts[11:19] if len(ts) >= 19 else ts
    lab = str(entry.get("label") or "")
    raw_c = str(entry.get("code") or "").strip()
    code = raw_c.zfill(6) if raw_c.isdigit() and len(raw_c) <= 6 else raw_c[:10]
    nm = str(entry.get("name") or "").strip()[:10]
    head = f"  {hms}  [{lab}] {code}"
    if nm:
        head += f" {nm}"
    k = str(entry.get("kind") or "").lower()
    tail_parts: list[str] = []
    hs = entry.get("hold_shares")
    cp = entry.get("cost_price")
    csr = entry.get("cmd_shares")
    cco = entry.get("cmd_cost")
    rr = entry.get("removed_rows")
    note = str(entry.get("note") or "").strip()
    if k in ("hold", "buy", "add"):
        if csr is not None and cco is not None:
            tail_parts.append(f"指令 {csr} 股 @{cco}")
        if hs is not None and cp is not None:
            tail_parts.append(f"录后 {hs} 股 成本 {cp}")
        elif hs is not None:
            tail_parts.append(f"录后 {hs} 股")
        elif cp is not None:
            tail_parts.append(f"成本 {cp}")
    elif k in ("reduce", "sell_partial"):
        if hs is not None and cp is not None:
            tail_parts.append(f"余 {hs} 股 成本 {cp}")
        elif hs is not None:
            tail_parts.append(f"余 {hs} 股")
    elif k in ("unhold", "sell_clear"):
        if rr is not None:
            tail_parts.append(f"删 config {rr} 行")
    elif k in ("hold_watch", "holdwatch"):
        tail_parts.append("未改仓位")
    tail = "  ".join(tail_parts) if tail_parts else ""
    if note:
        tail = (tail + " ｜ " if tail else "") + note[:100]
    return head + (f"  {tail}" if tail else "")


def _unrealized_holdings_yuan(
    cfg: dict[str, Any], root: Path, day_iso: str
) -> tuple[float, list[str], list[dict[str, Any]]]:
    """持仓按「summary 当日及以前最近一根」日 K 收盘相对成本估浮盈（元）。

    返回 (合计浮盈, 说明 notes, 各标的明细：code/name/float_pnl_est/...)。
    """
    notes: list[str] = []
    positions: list[dict[str, Any]] = []
    ks = cfg.get("kline_store") or {}
    db_rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    dbp = Path(db_rel)
    if not dbp.is_absolute():
        dbp = root / dbp
    if not dbp.is_file():
        notes.append("no_local_kline_db_unrealized_uses_tushare_only")
    try:
        from account_pnl_daily import nominal_last_two_closes
        from backtest_picks_performance import code_to_secid
    except Exception as exc:
        _LOG.warning("daily_summary: code_to_secid import failed: %s", exc)
        notes.append("unrealized_skipped_secid_import")
        return 0.0, notes, positions

    total = 0.0
    n_used = 0
    any_qfq_basis = False
    conn: sqlite3.Connection | None = None
    if dbp.is_file():
        try:
            conn = sqlite3.connect(str(dbp), timeout=8.0)
        except OSError as exc:
            _LOG.warning("daily_summary: unrealized sqlite open failed: %s", exc)
            notes.append("unrealized_kline_db_open_failed")
    try:
        for h in _collect_holdings(cfg, root):
            hs = int(h.get("hold_shares") or 0)
            if hs <= 0:
                continue
            cost = h.get("cost_price")
            if cost is None:
                continue
            try:
                cost_f = float(cost)
            except (TypeError, ValueError):
                continue
            if not isfinite(cost_f) or cost_f <= 0:
                continue
            code = str(h.get("code") or "").strip()
            if not code:
                continue
            code6 = _z6(code) or code
            try:
                sid = code_to_secid(code)
            except Exception:
                continue
            cl, _prev_unused, basis = nominal_last_two_closes(conn, sid, day_iso)
            if basis == "qfq_db":
                any_qfq_basis = True
            if cl is None:
                continue
            pnl = (cl - cost_f) * float(hs)
            total += pnl
            n_used += 1
            disp = str(h.get("name") or "").strip() or code6
            positions.append(
                {
                    "code": code6,
                    "name": disp,
                    "hold_shares": hs,
                    "float_pnl_est": round(float(pnl), 2),
                }
            )
    finally:
        if conn is not None:
            conn.close()
    if n_used > 0:
        notes.append(
            "浮盈估：trade_date≤总结日 的最近收盘；优先 Tushare daily（不复权），"
            "否则本地日K前复权（与券商绝对金额可能偏差）。"
        )
        if any_qfq_basis:
            notes.append("部分持仓浮盈仍以前复权日K估算（未拉到不复权日线时）。")
    if n_used == 0 and _collect_holdings(cfg, root):
        notes.append("unrealized_no_eligible_holdings_row")
    return float(total), notes, positions


def _collect_trades_summary(
    cfg: dict[str, Any], root: Path, day_iso: str, config_path: Path
) -> dict[str, Any]:
    """
    当日买卖与盈亏摘要（写入 daily_summary）。
    - buys：终端 hold <代码> <股数> <成本>（data/position_cli_log.json）
    - sells：unhold 删除 + sell_partial 减仓（均记入 sells 列表，以 removed_rows 区分）
    - sell_monitor_pauses：终端 sell（仅暂停监控，未删 config）
    - hold_watch_only：终端 hold <代码>（仅入池）
    - realized_profit：当日 position_ledger 减仓/清仓已实现（kind 为 reduce、close、unhold_settle 等）
    - unrealized_profit / net_profit：持仓浮盈 + 已实现
    - unrealized_positions：各持仓 code/name/float_pnl_est（与浮盈合计一致）
    """
    cli_entries = _position_cli_entries_for_day(config_path, day_iso)
    buys, sells, sell_pauses, hold_watch = _partition_trades_from_position_cli(
        cli_entries
    )

    unrealized, u_notes, unrealized_positions = _unrealized_holdings_yuan(
        cfg, root, day_iso
    )
    try:
        from position_ledger import (
            ledger_db_path,
            sum_realized_close_reduce_pnl_for_day,
        )

        realized = float(
            sum_realized_close_reduce_pnl_for_day(
                ledger_db_path(config_path.parent), day_iso
            )
        )
    except Exception:
        realized = 0.0
    net = float(realized) + float(unrealized)
    notes = list(u_notes)
    notes.append(
        "减仓清仓已实现=当日台账 reduce/close/unhold_settle 等卖出侧 realized_pnl 之和（不含 hold/buy/add）。"
        "buy/add=开仓或加仓；reduce / sell 代码 整数股数=减仓结算；"
        "sell 代码（无股数）或 unhold=清仓删配置并结算；pause=仅暂停监控。"
        "流水见 data/position_ledger.db。"
    )
    plog = config_path.parent / "data" / "position_cli_log.json"
    if not plog.is_file():
        notes.append(
            "尚无 position_cli_log.json；升级后新产生的 hold/unhold/sell 会写入该文件。"
        )

    return {
        "buys": buys,
        "sells": sells,
        "sell_monitor_pauses": sell_pauses,
        "hold_watch_only": hold_watch,
        "realized_profit": round(float(realized), 2),
        "unrealized_profit": round(unrealized, 4),
        "net_profit": round(net, 2),
        "unrealized_positions": unrealized_positions,
        "notes": notes,
    }


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


def _sell_ledger_rows_for_mail(account_pnl: Any) -> list[dict[str, Any]]:
    """从 account_pnl.ledger_events 筛出当日减仓/清仓台账行（供邮件正文）。"""
    kinds = frozenset(
        {"reduce", "close", "unhold_settle", "sell_clear", "sell_partial"}
    )
    out: list[dict[str, Any]] = []
    if not isinstance(account_pnl, dict):
        return out
    raw = account_pnl.get("ledger_events")
    if not isinstance(raw, list):
        return out
    for ev in raw:
        if not isinstance(ev, dict):
            continue
        k = str(ev.get("kind") or "").strip().lower()
        if k not in kinds:
            continue
        try:
            rp = float(ev.get("realized_pnl") or 0.0)
        except (TypeError, ValueError):
            rp = 0.0
        try:
            qty = int(ev.get("qty_traded") or 0)
        except (TypeError, ValueError):
            qty = 0
        if k == "close" and abs(rp) < 1e-12 and qty == 0:
            continue
        out.append(ev)
    return out


def _sell_kind_label_cn(kind: str) -> str:
    k = str(kind or "").strip().lower()
    return {
        "reduce": "减仓",
        "close": "清仓",
        "unhold_settle": "清仓",
        "sell_clear": "清仓",
        "sell_partial": "减仓",
    }.get(k, k or "卖出")


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

    holds = _collect_holdings(cfg, root)
    try:
        from account_pnl_daily import build_account_pnl_summary

        account_pnl = build_account_pnl_summary(
            cfg, root, config_path, day_iso, holdings=holds
        )
    except Exception as exc:
        _LOG.warning("daily_summary: account_pnl failed: %s", exc)
        account_pnl = {"notes": [f"account_pnl_error:{exc}"]}

    sell_events_today = _sell_ledger_rows_for_mail(account_pnl)
    position_operations_today = _collect_position_operations_today(
        config_path, day_iso
    )

    return {
        "schema_version": 1,
        "date": day_iso,
        "generated_at": now.isoformat(timespec="seconds"),
        "holdings": holds,
        "signals_today": _collect_today_signals(cfg, root, day_iso=day_iso),
        "daily_picks_quality": quality_rows,
        "daily_picks_watch": watch_rows,
        "console_quality_codes_eod": q_console_set,
        "dip_pick_codes_eod": dip_codes,
        "afternoon_opportunities": _collect_afternoon_opportunities(afternoon_path),
        "backtest_weekly_json": _collect_backtest_weekly(weekly_path),
        "health": _collect_health(cfg, root),
        "trades": _collect_trades_summary(cfg, root, day_iso, config_path),
        "position_operations_today": position_operations_today,
        "account_pnl": account_pnl,
        "sell_events_today": sell_events_today,
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
    """邮件/企微正文：今日终端操作流水 + 减仓清仓台账 + 当前持仓；其余见 daily_summary.json。"""
    lines: list[str] = []
    lines.append(f"【每日总结】{summary.get('date', '')}")
    lines.append(f"生成时间: {summary.get('generated_at', '')}")
    lines.append("")

    lines.append("— 今日操作记录（终端：买入 / 加仓 / 录仓 / 减持 / 清仓等）—")
    op_rows = summary.get("position_operations_today") or []
    if not op_rows:
        lines.append("  （今日无 position_cli 记录，或未产生 hold/reduce/… 指令）")
    else:
        for ev in op_rows[:80]:
            if isinstance(ev, dict):
                lines.append(_format_position_operation_mail_line(ev))

    lines.append("")
    tr = summary.get("trades")
    realized = None
    if isinstance(tr, dict):
        realized = tr.get("realized_profit")

    lines.append("— 今日减仓 / 清仓（台账）—")
    if realized is not None:
        lines.append(f"  合计已实现：{realized} 元")
    sell_rows = summary.get("sell_events_today") or []
    if not sell_rows:
        lines.append("  （今日无卖出侧台账记录，或账本为空）")
    else:
        for ev in sell_rows[:40]:
            if not isinstance(ev, dict):
                continue
            kind = _sell_kind_label_cn(str(ev.get("kind") or ""))
            raw_c = str(ev.get("code") or "").strip()
            code = raw_c.zfill(6) if raw_c.isdigit() and len(raw_c) <= 6 else raw_c[:10]
            nm = str(ev.get("name") or "").strip()[:10]
            try:
                qty = int(ev.get("qty_traded") or 0)
            except (TypeError, ValueError):
                qty = 0
            ex = ev.get("exec_price")
            try:
                exf = float(ex) if ex is not None and str(ex).strip() != "" else None
            except (TypeError, ValueError):
                exf = None
            try:
                rp = float(ev.get("realized_pnl") or 0.0)
            except (TypeError, ValueError):
                rp = 0.0
            before_v = ev.get("shares_before")
            after_v = ev.get("shares_after")
            px_s = f"{exf:.4f}" if exf is not None and exf > 0 else "—"
            extra = ""
            if before_v is not None or after_v is not None:
                extra = f"  （仓 {before_v} → {after_v}）"
            lines.append(
                f"  [{kind}] {code} {nm}  数量 {qty}  结算价≈{px_s}  盈亏 {rp:+.2f} 元{extra}"
            )

    lines.append("")
    lines.append("— 当前持仓 —")
    hs_list = summary.get("holdings") or []
    npos = 0
    for h in hs_list:
        if not isinstance(h, dict):
            continue
        try:
            hs = int(h.get("hold_shares") or 0)
        except (TypeError, ValueError):
            hs = 0
        if hs <= 0:
            continue
        npos += 1
        lab = _report_stock_label(str(h.get("name") or ""), str(h.get("code") or ""))
        lines.append(
            f"  {_padded_label(lab, _REPORT_STOCK_COL_WIDTH)} "
            f"{hs} 股  成本 {h.get('cost_price')}"
        )
    if npos == 0:
        lines.append("  （无 hold_shares>0 的持仓行）")

    lines.append("")
    lines.append(
        "选股、信号、按标的日 K 的浮盈等仍写入 data/daily_summary.json，需要时请打开该文件。"
    )
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
