#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交割单 → daily_summary_history 回灌，供 self_improve_use_trade_profit / 信号后验采纳闭环。

通常由 broker_day_report.py 在日结报告后自动调用；也可单独跑：

  .venv/bin/python3 broker_summary_sync.py -c config.json --date 2026-05-16
  .venv/bin/python3 broker_summary_sync.py -c config.json --all-days   # 交割单内每个交收日回灌
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def _ops(cfg: dict[str, Any]) -> dict[str, Any]:
    oa = cfg.get("ops_automation")
    return oa if isinstance(oa, dict) else {}


def broker_sync_enabled(cfg: dict[str, Any]) -> bool:
    return bool(_ops(cfg).get("broker_sync_to_summary_enabled", True))


def broker_align_holdings_enabled(cfg: dict[str, Any]) -> bool:
    return bool(_ops(cfg).get("broker_sync_align_holdings", True))


def broker_sync_on_startup_enabled(cfg: dict[str, Any]) -> bool:
    return bool(_ops(cfg).get("broker_sync_on_startup_enabled", True))


def broker_sync_after_close_enabled(cfg: dict[str, Any]) -> bool:
    return bool(_ops(cfg).get("broker_sync_after_close_enabled", True))


def last_completed_trading_day(as_of: date) -> date:
    """as_of 当日开盘前：最近一个已结束的 A 股交易日（周一至周五）。"""
    d = as_of
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    if as_of.weekday() == 0:
        return as_of - timedelta(days=3)
    return as_of - timedelta(days=1)


def trade_days_to_sync_on_startup(
    ledger: Any,
    *,
    as_of: date,
    lookback_days: int,
) -> list[date]:
    """从全历史交割单中取 ≤ 最近交易日的末 N 个交收日。"""
    from weekly_report import trade_dates_in_events

    end = last_completed_trading_day(as_of)
    all_d = [d for d in trade_dates_in_events(ledger.events) if d <= end]
    if not all_d:
        return []
    n = max(1, int(lookback_days or 1))
    return all_d[-n:]


def run_broker_sync_startup(
    cfg: dict[str, Any],
    root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    开盘前自动校准：读 broker_xls 最新全历史文件，回灌近 N 个交收日到 daily_summary_history。
    供 run_alert 在 _maybe_run_ops_automation 中每日调用一次。
    """
    now = now or datetime.now()
    out: dict[str, Any] = {"ok": False, "synced": []}
    if not broker_sync_enabled(cfg) or not broker_sync_on_startup_enabled(cfg):
        out["skipped"] = "disabled"
        return out
    if now.weekday() >= 5:
        out["skipped"] = "weekend"
        return out

    from weekly_report import (
        load_broker_ledger,
        load_mapping_config,
        pick_primary_broker_file,
        resolve_broker_files,
    )

    try:
        mapping = load_mapping_config()
        broker_dir = root / "broker_xls"
        files = resolve_broker_files(broker_dir, mapping, cfg=cfg)
        primary = pick_primary_broker_file(files)
        ledger = load_broker_ledger(files, mapping)
    except FileNotFoundError as exc:
        out["error"] = str(exc)
        return out

    try:
        lb = max(1, int(_ops(cfg).get("broker_sync_startup_lookback_days", 3) or 3))
    except (TypeError, ValueError):
        lb = 3
    days = trade_days_to_sync_on_startup(ledger, as_of=now.date(), lookback_days=lb)
    out["source_file"] = primary.name
    out["target_end"] = last_completed_trading_day(now.date()).isoformat()
    if not days:
        out["skipped"] = "no_trade_dates"
        return out

    for d in days:
        try:
            rep = run_sync_for_day(
                cfg,
                root,
                trade_day=d,
                ledger=ledger,
                files=files,
                primary_file=primary,
                mapping=mapping,
            )
            sync = rep.get("broker_sync") or {}
            out["synced"].append(
                {
                    "date": d.isoformat(),
                    "broker_net_profit": sync.get("broker_net_profit"),
                    "holdings_aligned": sync.get("holdings_aligned"),
                }
            )
        except Exception as exc:
            _LOG.warning("broker_sync_startup %s failed: %s", d, exc)
            out.setdefault("errors", []).append({"date": d.isoformat(), "error": str(exc)})

    out["ok"] = len(out.get("errors") or []) == 0 and len(out["synced"]) > 0
    out["count"] = len(out["synced"])
    return out


def run_broker_sync_after_close(
    cfg: dict[str, Any],
    root: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """收盘 daily_summary 之后：若交割单含当日交收，回灌当日盈亏与持仓。"""
    now = now or datetime.now()
    if not broker_sync_enabled(cfg) or not broker_sync_after_close_enabled(cfg):
        return {"skipped": "disabled"}
    if now.weekday() >= 5:
        return {"skipped": "weekend"}
    try:
        rep = run_sync_for_day(cfg, root, trade_day=now.date())
        sync = rep.get("broker_sync")
        return sync if isinstance(sync, dict) else {"ok": False}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


def broker_adopt_signals_enabled(cfg: dict[str, Any]) -> bool:
    return bool(_ops(cfg).get("broker_sync_adopt_signals_enabled", True))


def broker_signal_match_days(cfg: dict[str, Any]) -> int:
    try:
        return max(1, int(_ops(cfg).get("broker_signal_match_days", 5) or 5))
    except (TypeError, ValueError):
        return 5


def _day_trades_to_buys_sells(day_trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    buys: list[dict[str, Any]] = []
    sells: list[dict[str, Any]] = []
    for row in day_trades:
        ev = row.get("event")
        base = {
            "code": row.get("code"),
            "name": row.get("name"),
            "quantity": row.get("quantity"),
            "price": row.get("price"),
            "source": "broker_xls",
            "trade_time": row.get("trade_time") or "",
        }
        if ev == "buy":
            buys.append(base)
        elif ev == "sell":
            item = dict(base)
            rp = row.get("realized_profit")
            if rp is not None:
                item["realized_profit"] = rp
            sells.append(item)
    return buys, sells


def broker_trades_overlay_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """从券商日结 report 生成写入 daily_summary.trades 的 overlay。"""
    pr = report.get("period_range") or report.get("week") or {}
    day_iso = str(pr.get("end") or pr.get("start") or "")[:10]
    tot = report.get("totals") or {}
    day_trades = report.get("day_trades") or []
    broker_buys, broker_sells = _day_trades_to_buys_sells(day_trades)

    realized = float(
        tot.get("realized_profit_period", tot.get("realized_profit_week", 0)) or 0
    )
    unreal_ch = tot.get("unrealized_change")
    try:
        unreal_f = float(unreal_ch) if unreal_ch is not None else None
    except (TypeError, ValueError):
        unreal_f = None

    total_day = tot.get("total_pnl_day")
    if total_day is None and unreal_f is not None:
        total_day = round(realized + unreal_f, 2)
    try:
        net = float(total_day) if total_day is not None else realized
    except (TypeError, ValueError):
        net = realized

    return {
        "source": "broker_xls",
        "broker_synced_at": datetime.now().isoformat(timespec="seconds"),
        "broker_source_file": report.get("source_file"),
        "broker_source_files": report.get("source_files"),
        "broker_report_json": report.get("json_path"),
        "broker_day": day_iso,
        "broker_realized_profit": round(realized, 2),
        "broker_unrealized_change": unreal_f,
        "broker_net_profit": round(net, 2),
        "broker_buys": broker_buys,
        "broker_sells": broker_sells,
        "broker_day_trades": day_trades,
        "broker_closed_positions": report.get("closed_positions") or [],
    }


def merge_broker_into_summary_history(
    root: Path,
    day_iso: str,
    overlay: dict[str, Any],
    *,
    overwrite_net: bool = True,
    report: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> Path:
    """
    合并到 data/daily_summary_history/YYYY-MM-DD.json。
    overwrite_net=True 时，用券商 net/realized 覆盖 trades.net_profit / realized_profit（供调参）。
    report 提供时且 broker_sync_align_holdings：用交割单日终持仓覆盖 holdings。
    """
    hdir = root / "data" / "daily_summary_history"
    hdir.mkdir(parents=True, exist_ok=True)
    path = hdir / f"{day_iso}.json"
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            doc = {}
    else:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}

    doc.setdefault("schema_version", 1)
    doc["date"] = day_iso
    doc.setdefault("generated_at", datetime.now().isoformat(timespec="seconds"))
    doc["broker_summary_synced_at"] = overlay.get("broker_synced_at")

    tr = doc.get("trades")
    if not isinstance(tr, dict):
        tr = {}
    tr = dict(tr)

    for k, v in overlay.items():
        tr[k] = v

    if overwrite_net:
        tr["realized_profit"] = overlay.get("broker_realized_profit", tr.get("realized_profit"))
        if overlay.get("broker_unrealized_change") is not None:
            tr["unrealized_profit"] = overlay.get("broker_unrealized_change")
        tr["net_profit"] = overlay.get("broker_net_profit", tr.get("net_profit"))

    notes = tr.get("notes")
    if not isinstance(notes, list):
        notes = []
    notes = [n for n in notes if isinstance(n, str)]
    tag = "broker_xls 已回灌 net/realized（供 self_improve_use_trade_profit）"
    if tag not in notes:
        notes.append(tag)
    tr["notes"] = notes

    doc["trades"] = tr

    align_holdings = (
        report is not None
        and cfg is not None
        and broker_align_holdings_enabled(cfg)
    )
    if align_holdings:
        from weekly_report import (
            broker_holdings_for_daily_summary,
            broker_unrealized_positions_from_holdings,
        )

        broker_hs = broker_holdings_for_daily_summary(report)
        if doc.get("holdings") and not doc.get("holdings_watchlist"):
            doc["holdings_watchlist"] = doc["holdings"]
        doc["holdings"] = broker_hs
        doc["holdings_broker"] = broker_hs
        doc["holdings_broker_as_of"] = day_iso
        tr["unrealized_positions"] = broker_unrealized_positions_from_holdings(
            broker_hs
        )
        tot = report.get("totals") or {}
        cash = tot.get("cash_available")
        mkt = tot.get("market_value")
        assets = tot.get("total_assets")
        doc["account_pnl_broker"] = {
            "as_of": day_iso,
            "cash_available": cash,
            "market_value": mkt,
            "total_assets": assets,
            "position_count": len(broker_hs),
            "source": "broker_xls",
        }
        hnotes = doc.get("holdings_notes")
        if not isinstance(hnotes, list):
            hnotes = []
        htag = "holdings 已与交割单日终持仓对齐（股数/成本来自流水）"
        if htag not in hnotes:
            hnotes.append(htag)
        doc["holdings_notes"] = hnotes

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    if align_holdings:
        live = root / "data" / "daily_summary.json"
        if live.is_file():
            try:
                live_doc = json.loads(live.read_text(encoding="utf-8"))
                if str(live_doc.get("date") or "")[:10] == day_iso:
                    live_doc["holdings"] = doc["holdings"]
                    live_doc["holdings_broker"] = doc.get("holdings_broker")
                    live_doc["holdings_broker_as_of"] = day_iso
                    live_doc["broker_summary_synced_at"] = doc.get(
                        "broker_summary_synced_at"
                    )
                    if isinstance(live_doc.get("trades"), dict):
                        live_doc["trades"]["unrealized_positions"] = tr.get(
                            "unrealized_positions"
                        )
                    live.write_text(
                        json.dumps(live_doc, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except (json.JSONDecodeError, OSError) as exc:
                _LOG.warning("broker_sync: skip live daily_summary.json: %s", exc)

    return path


def sync_broker_closed_loop(
    cfg: dict[str, Any],
    root: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    """回灌 daily_summary_history，并可选后验匹配 strategy_signal_log。"""
    out: dict[str, Any] = {"ok": False}
    if str(report.get("period") or "") != "daily":
        out["skipped"] = "not_daily_report"
        return out

    pr = report.get("period_range") or {}
    day_iso = str(pr.get("end") or "")[:10]
    if len(day_iso) != 10:
        out["error"] = "invalid_day"
        return out

    overlay = broker_trades_overlay_from_report(report)
    overwrite = bool(_ops(cfg).get("broker_sync_overwrite_profit", True))
    hist_path = merge_broker_into_summary_history(
        root,
        day_iso,
        overlay,
        overwrite_net=overwrite,
        report=report,
        cfg=cfg,
    )
    out["history_path"] = str(hist_path)
    out["broker_net_profit"] = overlay.get("broker_net_profit")
    if broker_align_holdings_enabled(cfg):
        from weekly_report import broker_holdings_for_daily_summary

        bh = broker_holdings_for_daily_summary(report)
        out["holdings_aligned"] = len(bh)
    out["ok"] = True

    adopted = 0
    if broker_adopt_signals_enabled(cfg):
        try:
            from signal_operation_feedback import adopt_signals_from_broker_day_trades

            trade_day = datetime.strptime(day_iso, "%Y-%m-%d").date()
            adopted = adopt_signals_from_broker_day_trades(
                cfg,
                root,
                trade_day=trade_day,
                day_trades=overlay.get("broker_day_trades") or [],
                lookback_days=broker_signal_match_days(cfg),
            )
        except Exception as exc:
            _LOG.warning("broker_sync: signal adopt failed: %s", exc)
            out["adopt_error"] = str(exc)
    out["signals_adopted"] = adopted
    _LOG.info(
        "broker_sync: %s net=%s adopted=%s",
        day_iso,
        overlay.get("broker_net_profit"),
        adopted,
    )
    return out


def maybe_sync_daily_broker_loop(
    cfg: dict[str, Any],
    root: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    if not broker_sync_enabled(cfg):
        return {"skipped": "broker_sync_to_summary_disabled"}
    return sync_broker_closed_loop(cfg, root, report)


def run_sync_for_day(
    cfg: dict[str, Any],
    root: Path,
    *,
    trade_day: date,
    xls_path: Path | None = None,
    mapping_path: Path | None = None,
    ledger: Any | None = None,
    files: list[Path] | None = None,
    primary_file: Path | None = None,
    mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成日结 report 并执行闭环同步（可传入已解析的全历史 ledger）。"""
    from weekly_report import (
        build_broker_period_report,
        load_mapping_config,
        load_broker_ledger,
        pick_primary_broker_file,
        resolve_broker_files,
        save_broker_period_json,
    )

    mapping = mapping or load_mapping_config(mapping_path)
    broker_dir = root / "broker_xls"
    if files is None:
        files = resolve_broker_files(
            broker_dir, mapping, xls_path=xls_path, cfg=cfg
        )
    primary = primary_file or pick_primary_broker_file(files)
    if ledger is None:
        ledger = load_broker_ledger(files, mapping)

    report = build_broker_period_report(
        cfg=cfg,
        root=root,
        mapping=mapping,
        broker_dir=broker_dir,
        files=files,
        primary_file=primary,
        as_of=trade_day,
        period="daily",
        period_start=trade_day,
        period_end=trade_day,
        ledger=ledger,
    )
    if bool(_ops(cfg).get("broker_sync_save_daily_reports", False)):
        p = save_broker_period_json(report, mapping, root, "daily")
        report["json_path"] = str(p)
    sync = maybe_sync_daily_broker_loop(cfg, root, report)
    report["broker_sync"] = sync
    return report


def sync_all_trade_days(
    cfg: dict[str, Any],
    root: Path,
    *,
    xls_path: Path | None = None,
    mapping_path: Path | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict[str, Any]:
    """
    从「一份全历史交割单」按每个交收日回灌 daily_summary_history（替换 xls 后跑一次即可）。
    """
    from weekly_report import (
        load_mapping_config,
        load_broker_ledger,
        pick_primary_broker_file,
        resolve_broker_files,
        trade_dates_in_events,
    )

    if not broker_sync_enabled(cfg):
        return {"skipped": "broker_sync_to_summary_disabled"}

    mapping = load_mapping_config(mapping_path)
    broker_dir = root / "broker_xls"
    files = resolve_broker_files(broker_dir, mapping, xls_path=xls_path, cfg=cfg)
    primary = pick_primary_broker_file(files)
    ledger = load_broker_ledger(files, mapping)
    dates = trade_dates_in_events(ledger.events)
    if from_date is not None:
        dates = [d for d in dates if d >= from_date]
    if to_date is not None:
        dates = [d for d in dates if d <= to_date]

    out: dict[str, Any] = {
        "source_file": primary.name,
        "trade_dates": [d.isoformat() for d in dates],
        "synced": [],
        "errors": [],
    }
    if not dates:
        out["ok"] = False
        out["error"] = "no_trade_dates_in_ledger"
        return out

    _LOG.info(
        "broker_sync_all: %s 共 %d 个交收日 %s ~ %s",
        primary.name,
        len(dates),
        dates[0],
        dates[-1],
    )

    for d in dates:
        try:
            rep = run_sync_for_day(
                cfg,
                root,
                trade_day=d,
                xls_path=xls_path,
                mapping_path=mapping_path,
                ledger=ledger,
                files=files,
                primary_file=primary,
                mapping=mapping,
            )
            sync = rep.get("broker_sync") or {}
            out["synced"].append(
                {
                    "date": d.isoformat(),
                    "broker_net_profit": sync.get("broker_net_profit"),
                    "signals_adopted": sync.get("signals_adopted", 0),
                }
            )
        except Exception as exc:
            _LOG.warning("broker_sync_all %s failed: %s", d, exc)
            out["errors"].append({"date": d.isoformat(), "error": str(exc)})

    out["ok"] = len(out["errors"]) == 0
    out["count"] = len(out["synced"])
    return out


def main() -> int:
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="交割单回灌 daily_summary_history + 信号采纳")
    ap.add_argument("-c", "--config", type=Path, default=root / "config.json")
    ap.add_argument("--date", type=str, default="", help="YYYY-MM-DD，默认今天")
    ap.add_argument(
        "--all-days",
        action="store_true",
        help="按交割单内全部交收日回灌（替换全历史 xls 后推荐）",
    )
    ap.add_argument("--from", dest="from_date", type=str, default="", help="--all-days 时起始日")
    ap.add_argument("--to", dest="to_date", type=str, default="", help="--all-days 时截止日")
    ap.add_argument("--xls", type=Path, default=None)
    ap.add_argument("--mapping", type=Path, default=None)
    ap.add_argument("--no-report", action="store_true", help="仅用已有 daily_report JSON")
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1

    from run_alert import merge_full_config

    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    def _parse_d(s: str) -> date | None:
        s = s.strip()
        if not s:
            return None
        return datetime.strptime(s[:10], "%Y-%m-%d").date()

    if args.date.strip():
        try:
            trade_day = _parse_d(args.date)
        except ValueError:
            print("--date 须为 YYYY-MM-DD", file=sys.stderr)
            return 1
    else:
        trade_day = date.today()

    from_d = to_d = None
    if args.from_date.strip() or args.to_date.strip():
        try:
            from_d = _parse_d(args.from_date)
            to_d = _parse_d(args.to_date)
        except ValueError:
            print("--from / --to 须为 YYYY-MM-DD", file=sys.stderr)
            return 1

    try:
        if args.all_days:
            result = sync_all_trade_days(
                cfg,
                root,
                xls_path=args.xls,
                mapping_path=args.mapping,
                from_date=from_d,
                to_date=to_d,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok", True) else 1
        if args.no_report:
            p = root / "data" / "daily_broker_reports" / f"daily_report_{trade_day.isoformat()}.json"
            if not p.is_file():
                print(f"缺少日结 JSON: {p}", file=sys.stderr)
                return 2
            report = json.loads(p.read_text(encoding="utf-8"))
            report["json_path"] = str(p)
            sync = maybe_sync_daily_broker_loop(cfg, root, report)
        else:
            report = run_sync_for_day(
                cfg,
                root,
                trade_day=trade_day,
                xls_path=args.xls,
                mapping_path=args.mapping,
            )
            sync = report.get("broker_sync") or {}
        print(json.dumps(sync, ensure_ascii=False, indent=2))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        _LOG.exception("broker_summary_sync failed")
        print(f"同步失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
