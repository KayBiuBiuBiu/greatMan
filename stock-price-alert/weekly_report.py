#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
券商交割单周报：从 broker_xls/ 读取中信证券 PC 导出的 XLS/XLSX，生成 JSON + 文本摘要并邮件/企微发送。

不依赖 watchlist 成本；持仓成本由交割单流水加权推算（买入按 |清算金额|，卖出按清算金额 - 成本）。

手动运行（项目根目录）：
  .venv/bin/python3 weekly_report.py -c config.json
  .venv/bin/python3 weekly_report.py -c config.json --as-of 2026-05-16
  .venv/bin/python3 weekly_report.py -c config.json --xls broker_xls/交割单.xlsx --no-send

macOS 定时（每周一 09:30，统计上一交易周 Mon–Fri）：
  crontab -e
  30 9 * * 1 cd /Users/haha/greatMan/stock-price-alert && .venv/bin/python3 weekly_report.py -c config.json >> logs/weekly_report.log 2>&1

说明：
  - data/daily_summary.json 仍会由 run_alert 写入，本脚本不删除；默认关闭每日总结邮件（见 ops_automation.daily_summary_email_enabled）。
  - 请将券商导出的「全部历史」或至少含本周的交割单放入 broker_xls/；脚本默认取该目录下最新修改的文件。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest_picks_performance import code_to_secid, resolve_db_path
from kline_store import open_store_connection
from pnl_period_report import _last_completed_trading_week_mon_fri
from quote_eastmoney import secid_for

_LOG = logging.getLogger(__name__)
_MAPPING_PATH = ROOT / "mapping_config.json"
_DELIVERY_FILENAME_RE = re.compile(
    r"^交割单_(\d{8})_(\d{6})\.(xls|xlsx)$", re.IGNORECASE
)

PERIOD_LABELS = {
    "weekly": "周报",
    "monthly": "月报",
    "h1": "半年报（上半年）",
    "h2": "半年报（下半年）",
    "annual": "年报",
}


def _normalize_header(name: str) -> str:
    """中信证券 XLS 表头常带 UTF-8 BOM（\\ufeff）。"""
    return str(name).replace("\ufeff", "").strip()


def _cell_str(val: Any) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).replace("\ufeff", "").strip()


def _z6(code: str) -> str:
    s = re.sub(r"\D", "", str(code or ""))
    return s.zfill(6)[-6:] if len(s) >= 6 else s.zfill(6) if s else ""


def load_mapping_config(path: Path | None = None) -> dict[str, Any]:
    p = path or _MAPPING_PATH
    if not p.is_file():
        raise FileNotFoundError(f"缺少列映射配置: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("mapping_config.json 须为 JSON 对象")
    return raw


def _parse_trade_date(val: Any) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("nan", "nat"):
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).date()
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(val, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        s = str(val).replace(",", "").strip()
        if not s:
            return default
        try:
            return float(s)
        except ValueError:
            return default


def _read_excel_file(path: Path, sheet_index: int = 0) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".xlsx":
        return pd.read_excel(path, sheet_name=sheet_index, engine="openpyxl")
    if suf == ".xls":
        try:
            return pd.read_excel(path, sheet_name=sheet_index, engine="xlrd")
        except Exception:
            return pd.read_excel(path, sheet_name=sheet_index)
    return pd.read_excel(path, sheet_name=sheet_index)


def _rename_columns(df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_header(c) for c in df.columns]
    inv = {_normalize_header(v): k for k, v in col_map.items() if v}
    out = df.rename(columns={c: inv[c] for c in df.columns if c in inv})
    missing = [
        k
        for k, v in col_map.items()
        if v and _normalize_header(v) not in df.columns and k not in out.columns
    ]
    if missing:
        _LOG.warning("交割单缺少映射列: %s", missing)
    return out


def _file_export_datetime(path: Path) -> datetime | None:
    m = _DELIVERY_FILENAME_RE.match(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def list_broker_files(
    broker_dir: Path, mapping: dict[str, Any], *, xls_path: Path | None = None
) -> list[Path]:
    if xls_path is not None:
        if not xls_path.is_file():
            raise FileNotFoundError(f"指定文件不存在: {xls_path}")
        return [xls_path.resolve()]
    if not broker_dir.is_dir():
        raise FileNotFoundError(
            f"broker_xls 目录不存在: {broker_dir}（请创建并放入中信证券导出的 XLS）"
        )
    globs = mapping.get("file_glob") or ["交割单_*.xls", "交割单_*.xlsx"]
    files: list[Path] = []
    for g in globs:
        files.extend(broker_dir.glob(g))
    files = sorted({p.resolve() for p in files if p.is_file()})
    if not files:
        for g in ("*.xls", "*.xlsx"):
            files.extend(broker_dir.glob(g))
        files = sorted({p.resolve() for p in files if p.is_file()})

    def _sort_key(p: Path) -> tuple:
        dt = _file_export_datetime(p)
        if dt is not None:
            return (1, dt.timestamp())
        return (0, p.stat().st_mtime)

    files = sorted(files, key=_sort_key)
    if not files:
        raise FileNotFoundError(f"{broker_dir} 下未找到交割单文件（支持 {globs}）")
    return files


def pick_primary_broker_file(
    files: list[Path], *, as_of: date | None = None
) -> Path:
    """优先 交割单_YYYYMMDD_HHMMSS.xls 命名；默认取导出时间最新的一份。"""
    if not files:
        raise FileNotFoundError("无交割单文件")
    tagged = [(p, _file_export_datetime(p)) for p in files]
    with_dt = [(p, dt) for p, dt in tagged if dt is not None]
    if as_of is not None:
        tag = as_of.strftime("%Y%m%d")
        day_files = [(p, dt) for p, dt in with_dt if tag in p.name]
        if day_files:
            return max(day_files, key=lambda x: x[1])[0]
    if with_dt:
        return max(with_dt, key=lambda x: x[1])[0]
    return files[-1]


def load_broker_frames(
    files: list[Path], mapping: dict[str, Any]
) -> pd.DataFrame:
    col_map = mapping.get("columns") or {}
    sheet = int(mapping.get("sheet_index", 0) or 0)
    header_row = int(mapping.get("header_row", 0) or 0)
    frames: list[pd.DataFrame] = []
    for fp in files:
        try:
            raw = _read_excel_file(fp, sheet_index=sheet)
        except Exception as exc:
            _LOG.warning("跳过无法读取的文件 %s: %s", fp.name, exc)
            continue
        if header_row > 0 and len(raw) > header_row:
            raw.columns = [_normalize_header(c) for c in raw.iloc[header_row]]
            raw = raw.iloc[header_row + 1 :].reset_index(drop=True)
        norm = _rename_columns(raw, col_map)
        norm["_source_file"] = fp.name
        frames.append(norm)
    if not frames:
        raise ValueError("未能从任何交割单文件解析出数据")
    merged = pd.concat(frames, ignore_index=True)
    return merged


def _biz_kind(business: str, mapping: dict[str, Any]) -> str:
    b = _cell_str(business)
    bt = mapping.get("business_types") or {}
    for kw in bt.get("skip_keywords") or []:
        if kw and kw in b:
            return "skip"
    for kw in bt.get("sell_keywords") or []:
        if kw and kw in b:
            return "sell"
    for kw in bt.get("buy_keywords") or []:
        if kw and kw in b:
            return "buy"
    return "skip"


def _row_fee_sum(row: pd.Series) -> float:
    keys = (
        "commission",
        "stamp_tax",
        "transfer_fee",
        "surcharge",
        "exchange_clearing_fee",
        "fund_fee",
        "regulatory_fee",
        "fx_diff",
    )
    return sum(abs(_to_float(row.get(k), 0.0)) for k in keys)


def _dedupe_key(row: pd.Series) -> str:
    parts = [
        str(row.get("order_id") or ""),
        str(row.get("trade_time") or ""),
        _z6(str(row.get("code") or "")),
        str(row.get("business") or ""),
        str(row.get("quantity") or ""),
        str(row.get("settlement_amount") or ""),
    ]
    return "|".join(parts)


@dataclass
class PositionState:
    code: str
    name: str
    shares: int = 0
    cost_total: float = 0.0

    @property
    def avg_cost(self) -> float | None:
        if self.shares <= 0:
            return None
        return self.cost_total / self.shares


@dataclass
class ClosedLot:
    code: str
    name: str
    shares: int
    sell_amount: float
    sell_qty: int
    realized_profit: float
    last_settle_date: date
    sell_prices: list[float] = field(default_factory=list)

    @property
    def avg_sell_price(self) -> float | None:
        if self.sell_qty <= 0:
            return None
        return self.sell_amount / self.sell_qty


def parse_ledger_from_df(
    df: pd.DataFrame, mapping: dict[str, Any]
) -> tuple[dict[str, PositionState], list[dict[str, Any]], float | None, dict[str, Any]]:
    """
  按交收日期顺序处理流水，返回 (期末持仓, 事件列表, 最新资金余额, 元数据)。
    """
    allowed_ccy = {
        _normalize_header(x)
        for x in (mapping.get("currency_allowed") or ["人民币", "CNY", "RMB", ""])
    }
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        code = _z6(_cell_str(r.get("code")))
        if not code or len(code) != 6:
            continue
        ccy = _cell_str(r.get("currency"))
        if allowed_ccy and ccy not in allowed_ccy:
            continue
        sd = _parse_trade_date(r.get("settle_date"))
        if sd is None:
            continue
        biz = _cell_str(r.get("business"))
        kind = _biz_kind(biz, mapping)
        if kind == "skip":
            continue
        qty = int(abs(_to_float(r.get("quantity"), 0.0)))
        if qty <= 0:
            continue
        rows.append(
            {
                "code": code,
                "name": _cell_str(r.get("name")),
                "settle_date": sd,
                "business": biz,
                "kind": kind,
                "quantity": qty,
                "price": _to_float(r.get("price"), 0.0),
                "amount": _to_float(r.get("amount"), 0.0),
                "settlement_amount": _to_float(r.get("settlement_amount"), 0.0),
                "cash_balance": _to_float(r.get("cash_balance"), float("nan")),
                "fee_sum": _row_fee_sum(r),
                "order_id": str(r.get("order_id") or ""),
                "trade_time": str(r.get("trade_time") or ""),
                "_source_file": str(r.get("_source_file") or ""),
                "_dedupe": "",
            }
        )

    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for row in rows:
        row["_dedupe"] = _dedupe_key(pd.Series(row))
        if row["_dedupe"] in seen:
            continue
        seen.add(row["_dedupe"])
        uniq.append(row)
    uniq.sort(key=lambda x: (x["settle_date"], x.get("trade_time") or "", x["code"]))

    positions: dict[str, PositionState] = {}
    events: list[dict[str, Any]] = []
    last_cash: float | None = None
    last_cash_date: date | None = None

    for row in uniq:
        code = row["code"]
        pos = positions.get(code)
        if pos is None:
            pos = PositionState(code=code, name=row["name"] or code)
            positions[code] = pos
        elif row["name"]:
            pos.name = row["name"]

        qty = row["quantity"]
        settle_amt = row["settlement_amount"]
        kind = row["kind"]

        if not pd.isna(row["cash_balance"]):
            cb = float(row["cash_balance"])
            if last_cash_date is None or row["settle_date"] >= last_cash_date:
                last_cash = cb
                last_cash_date = row["settle_date"]

        if kind == "buy":
            if settle_amt < 0:
                cost_add = abs(settle_amt)
            else:
                cost_add = abs(row["amount"]) + row["fee_sum"]
            pos.shares += qty
            pos.cost_total += cost_add
            events.append({**row, "event": "buy", "realized_profit": 0.0})
            continue

        if kind == "sell":
            if pos.shares <= 0:
                _LOG.warning("卖出但无持仓 %s %s", code, row["settle_date"])
                continue
            sell_qty = min(qty, pos.shares)
            avg = pos.cost_total / pos.shares
            if settle_amt > 0:
                proceeds = settle_amt
            else:
                proceeds = abs(row["amount"]) - row["fee_sum"]
            cost_removed = avg * sell_qty
            realized = proceeds - cost_removed
            pos.shares -= sell_qty
            pos.cost_total -= cost_removed
            if pos.shares <= 0:
                pos.shares = 0
                pos.cost_total = 0.0
            events.append(
                {
                    **row,
                    "event": "sell",
                    "sell_qty": sell_qty,
                    "realized_profit": round(realized, 2),
                    "proceeds": round(proceeds, 2),
                }
            )

    meta = {
        "rows_parsed": len(uniq),
        "last_cash_balance": last_cash,
        "last_cash_date": last_cash_date.isoformat() if last_cash_date else None,
    }
    return positions, events, last_cash, meta


def positions_at_date(
    events: list[dict[str, Any]], as_of: date
) -> dict[str, PositionState]:
    """截至 as_of（含）的持仓快照。"""
    pos: dict[str, PositionState] = {}
    for ev in events:
        if ev["settle_date"] > as_of:
            break
        code = ev["code"]
        p = pos.get(code)
        if p is None:
            p = PositionState(code=code, name=ev.get("name") or code)
            pos[code] = p
        elif ev.get("name"):
            p.name = ev["name"]
        if ev["event"] == "buy":
            qty = ev["quantity"]
            settle_amt = ev["settlement_amount"]
            if settle_amt < 0:
                cost_add = abs(settle_amt)
            else:
                cost_add = abs(ev["amount"]) + ev["fee_sum"]
            p.shares += qty
            p.cost_total += cost_add
        elif ev["event"] == "sell":
            sell_qty = ev.get("sell_qty") or ev["quantity"]
            if p.shares <= 0:
                continue
            avg = p.cost_total / p.shares
            p.shares -= sell_qty
            p.cost_total -= avg * sell_qty
            if p.shares <= 0:
                p.shares = 0
                p.cost_total = 0.0
    return {k: v for k, v in pos.items() if v.shares > 0}


def closed_positions_in_week(
    events: list[dict[str, Any]], week_start: date, week_end: date
) -> list[ClosedLot]:
    """本周内完成清仓的标的（卖完后持仓为 0）。"""
    pos: dict[str, PositionState] = {}
    closing: dict[str, ClosedLot] = {}

    for ev in events:
        sd = ev["settle_date"]
        code = ev["code"]
        p = pos.get(code)
        if p is None:
            p = PositionState(code=code, name=ev.get("name") or code)
            pos[code] = p
        elif ev.get("name"):
            p.name = ev["name"]

        if ev["event"] == "buy":
            qty = ev["quantity"]
            settle_amt = ev["settlement_amount"]
            cost_add = abs(settle_amt) if settle_amt < 0 else abs(ev["amount"]) + ev["fee_sum"]
            p.shares += qty
            p.cost_total += cost_add
            if code in closing:
                del closing[code]
            continue

        if ev["event"] != "sell":
            continue
        sell_qty = ev.get("sell_qty") or ev["quantity"]
        if p.shares <= 0:
            continue
        avg = p.cost_total / p.shares
        proceeds = (
            ev["settlement_amount"]
            if ev["settlement_amount"] > 0
            else abs(ev["amount"]) - ev["fee_sum"]
        )
        realized = ev.get("realized_profit", proceeds - avg * sell_qty)
        p.shares -= sell_qty
        p.cost_total -= avg * sell_qty

        if week_start <= sd <= week_end:
            lot = closing.get(code)
            if lot is None:
                lot = ClosedLot(
                    code=code,
                    name=p.name,
                    shares=0,
                    sell_amount=0.0,
                    sell_qty=0,
                    realized_profit=0.0,
                    last_settle_date=sd,
                )
                closing[code] = lot
            lot.shares += sell_qty
            lot.sell_qty += sell_qty
            lot.sell_amount += proceeds
            lot.realized_profit += float(realized)
            lot.last_settle_date = sd
            if ev.get("price"):
                lot.sell_prices.append(float(ev["price"]))

        if p.shares <= 0:
            p.shares = 0
            p.cost_total = 0.0
            if code in closing and week_start <= sd <= week_end:
                pass
            elif code in closing:
                del closing[code]

    out: list[ClosedLot] = []
    for code, lot in closing.items():
        if pos.get(code) and pos[code].shares > 0:
            continue
        if lot.sell_qty <= 0:
            continue
        out.append(lot)
    out.sort(key=lambda x: x.code)
    return out


def close_on_date(db_path: Path, code: str, on_date: date) -> float | None:
    """本地日 K 收盘价；无则 None。"""
    secid = code_to_secid(code)
    dstr = on_date.isoformat()
    conn = open_store_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT close FROM daily_klines
            WHERE secid = ? AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT 1
            """,
            (secid, dstr),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return float(row[0])


def close_on_date_tushare(code: str, on_date: date, cfg: dict[str, Any]) -> float | None:
    try:
        from quote_tushare import configure_tushare_from_sources, fetch_daily_kline_df
    except Exception:
        return None
    configure_tushare_from_sources(cfg.get("sources"))
    market = "sh" if code.startswith(("6", "9")) else "sz"
    sid = secid_for(code, market)
    df = fetch_daily_kline_df(sid, count=30)
    if df is None or df.empty:
        return None
    col = "trade_date" if "trade_date" in df.columns else None
    if col is None:
        return None
    sub = df[df[col].astype(str) <= on_date.strftime("%Y%m%d")]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["close"])


def fetch_close_prices(
    codes: list[str],
    on_date: date,
    *,
    cfg: dict[str, Any],
    db_path: Path,
) -> dict[str, float | None]:
    """优先 SQLite daily_klines.db，缺失时用 Tushare。"""
    out: dict[str, float | None] = {}
    for code in codes:
        c = _z6(code)
        if not c:
            continue
        px = close_on_date(db_path, c, on_date)
        if px is None:
            px = close_on_date_tushare(c, on_date, cfg)
        out[c] = px
    return out


def unrealized_total(
    positions: dict[str, PositionState], closes: dict[str, float | None]
) -> tuple[float, list[dict[str, Any]]]:
    total = 0.0
    rows: list[dict[str, Any]] = []
    for code in sorted(positions.keys()):
        p = positions[code]
        if p.shares <= 0:
            continue
        px = closes.get(code)
        avg = p.avg_cost
        if px is None or avg is None:
            u = None
        else:
            u = (px - avg) * p.shares
            total += u
        rows.append(
            {
                "code": code,
                "name": p.name,
                "hold_shares": p.shares,
                "cost_price": round(avg, 4) if avg is not None else None,
                "close_price": round(px, 4) if px is not None else None,
                "unrealized_profit": round(u, 2) if u is not None else None,
            }
        )
    return round(total, 2), rows


def period_realized_sum(
    events: list[dict[str, Any]], period_start: date, period_end: date
) -> float:
    s = 0.0
    for ev in events:
        if ev.get("event") != "sell":
            continue
        sd = ev["settle_date"]
        if period_start <= sd <= period_end:
            s += float(ev.get("realized_profit") or 0.0)
    return round(s, 2)


def week_realized_sum(events: list[dict[str, Any]], week_start: date, week_end: date) -> float:
    return period_realized_sum(events, week_start, week_end)


def closed_positions_in_period(
    events: list[dict[str, Any]], period_start: date, period_end: date
) -> list[ClosedLot]:
    return closed_positions_in_week(events, period_start, period_end)


def _output_cfg(mapping: dict[str, Any], period: str) -> dict[str, str]:
    out = mapping.get("output") or {}
    if isinstance(out.get(period), dict):
        return out[period]
    if period == "weekly" and out.get("json_dir"):
        return {"json_dir": out["json_dir"], "json_prefix": out.get("json_prefix", "weekly_report_")}
    defaults = {
        "weekly": ("data/weekly_reports", "weekly_report_"),
        "monthly": ("data/monthly_reports", "monthly_report_"),
        "h1": ("data/halfyear_reports", "h1_report_"),
        "h2": ("data/halfyear_reports", "h2_report_"),
        "annual": ("data/annual_reports", "annual_report_"),
    }
    d, p = defaults.get(period, defaults["weekly"])
    return {"json_dir": d, "json_prefix": p}


def format_broker_period_text(report: dict[str, Any]) -> str:
    period = str(report.get("period") or "weekly")
    label = PERIOD_LABELS.get(period, "报告")
    pr = report.get("period_range") or report.get("week") or {}
    tot = report.get("totals") or {}
    close_label = "期末收盘" if period != "weekly" else "上周五收盘"
    lines = [
        f"【券商交割单{label}】{pr.get('start', '')} ～ {pr.get('end', '')}",
        f"数据源：{report.get('source_file', '—')}",
        "",
        f"一、本{'周' if period == 'weekly' else '期'}清仓（已实现）",
    ]
    closed = report.get("closed_positions") or []
    if not closed:
        lines.append("  （本周无清仓）")
    else:
        for row in closed:
            lbl = row.get("name") or row.get("code")
            sp = row.get("avg_sell_price")
            sp_s = f"{sp:.4f}" if sp is not None else "—"
            lines.append(
                f"  {row.get('code')} {lbl}  卖价 {sp_s}  "
                f"{row.get('shares')}股  盈亏 {row.get('realized_profit'):+.2f} 元"
            )
    lines.extend(["", f"二、当前持仓（{close_label}）"])
    holdings = report.get("holdings") or []
    if not holdings:
        lines.append("  （无持仓）")
    else:
        for row in holdings:
            lbl = row.get("name") or row.get("code")
            cp = row.get("cost_price")
            cl = row.get("close_price")
            u = row.get("unrealized_profit")
            cp_s = f"{cp:.4f}" if cp is not None else "—"
            cl_s = f"{cl:.4f}" if cl is not None else "—"
            u_s = f"{u:+.2f}" if u is not None else "—"
            lines.append(
                f"  {row.get('code')} {lbl}  {row.get('hold_shares')}股  "
                f"成本 {cp_s}  收盘 {cl_s}  浮盈 {u_s}"
            )
    lines.extend(
        [
            "",
            f"三、本{'周' if period == 'weekly' else '期'}合计",
            f"  已实现盈亏：{tot.get('realized_profit_period', tot.get('realized_profit_week', 0)):+.2f} 元",
            f"  浮动盈亏变化：{tot.get('unrealized_change', '—')} 元"
            f"（期末 {tot.get('unrealized_period_end', tot.get('unrealized_week_end', '—'))} "
            f"− 期初 {tot.get('unrealized_period_start', tot.get('unrealized_week_start', '—'))}）",
            f"  可用资金：{tot.get('cash_available', '—')} 元",
            f"  持仓市值：{tot.get('market_value', '—')} 元",
            f"  总资产：{tot.get('total_assets', '—')} 元",
            "",
            "说明：成本与已实现盈亏均来自券商交割单流水，非 watchlist 成本。",
        ]
    )
    warnings = report.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("⚠️ " + "；".join(str(x) for x in warnings))
    return "\n".join(lines)


def format_weekly_summary_text(report: dict[str, Any]) -> str:
    return format_broker_period_text(report)


def notify_weekly_report(cfg: dict[str, Any], *, subject: str, body: str) -> bool:
    from email_notify import send_email_alert

    return bool(send_email_alert(subject, body, app_cfg=cfg))


def build_broker_period_report(
    *,
    cfg: dict[str, Any],
    root: Path,
    mapping: dict[str, Any],
    broker_dir: Path,
    files: list[Path],
    primary_file: Path,
    as_of: date,
    period: str,
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    df = load_broker_frames(files, mapping)
    positions_eod, events, last_cash, ledger_meta = parse_ledger_from_df(df, mapping)

    pos_start = positions_at_date(events, period_start - timedelta(days=1))
    pos_end = positions_at_date(events, period_end)
    if not pos_end:
        pos_end = positions_eod

    all_codes = sorted(
        set(pos_start.keys()) | set(pos_end.keys()) | {_z6(e["code"]) for e in events}
    )
    db_path = resolve_db_path(cfg)
    closes_end = fetch_close_prices(all_codes, period_end, cfg=cfg, db_path=db_path)
    start_px_date = period_start - timedelta(days=1)
    closes_start = fetch_close_prices(
        list(pos_start.keys()), start_px_date, cfg=cfg, db_path=db_path
    )

    unreal_end, holdings_rows = unrealized_total(pos_end, closes_end)
    unreal_start, _ = unrealized_total(pos_start, closes_start)
    unreal_change = round(unreal_end - unreal_start, 2)

    market_value = 0.0
    for row in holdings_rows:
        sh = row.get("hold_shares") or 0
        cl = row.get("close_price")
        if cl is not None and sh:
            market_value += cl * sh
    market_value = round(market_value, 2)

    cash = last_cash
    total_assets = round((cash or 0.0) + market_value, 2) if cash is not None else None

    realized_period = period_realized_sum(events, period_start, period_end)
    closed = closed_positions_in_period(events, period_start, period_end)
    closed_rows = [
        {
            "code": lot.code,
            "name": lot.name,
            "shares": lot.sell_qty,
            "avg_sell_price": round(lot.avg_sell_price, 4)
            if lot.avg_sell_price is not None
            else None,
            "realized_profit": round(lot.realized_profit, 2),
            "last_settle_date": lot.last_settle_date.isoformat(),
        }
        for lot in closed
    ]

    warnings: list[str] = []
    if ledger_meta.get("rows_parsed", 0) == 0:
        warnings.append("交割单无有效成交行")
    missing_close = [c for c in pos_end if closes_end.get(c) is None]
    if missing_close:
        warnings.append(f"{len(missing_close)} 只持仓缺期末收盘价")
    if cash is None:
        warnings.append("未能从交割单解析资金余额")

    return {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": primary_file.name,
        "source_files": [p.name for p in files],
        "period": period,
        "period_range": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "as_of": as_of.isoformat(),
        },
        "week": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "as_of": as_of.isoformat(),
        },
        "ledger_meta": ledger_meta,
        "closed_positions": closed_rows,
        "holdings": holdings_rows,
        "totals": {
            "realized_profit_period": realized_period,
            "realized_profit_week": realized_period,
            "unrealized_period_start": unreal_start,
            "unrealized_period_end": unreal_end,
            "unrealized_week_start": unreal_start,
            "unrealized_week_end": unreal_end,
            "unrealized_change": unreal_change,
            "cash_available": round(cash, 2) if cash is not None else None,
            "market_value": market_value,
            "total_assets": total_assets,
        },
        "warnings": warnings,
    }


def build_weekly_report(
    *,
    cfg: dict[str, Any],
    root: Path,
    mapping: dict[str, Any],
    broker_dir: Path,
    files: list[Path],
    primary_file: Path,
    as_of: date,
    week_start: date,
    week_end: date,
) -> dict[str, Any]:
    return build_broker_period_report(
        cfg=cfg,
        root=root,
        mapping=mapping,
        broker_dir=broker_dir,
        files=files,
        primary_file=primary_file,
        as_of=as_of,
        period="weekly",
        period_start=week_start,
        period_end=week_end,
    )


def save_broker_period_json(
    report: dict[str, Any], mapping: dict[str, Any], root: Path, period: str
) -> Path:
    out_cfg = _output_cfg(mapping, period)
    rel = str(out_cfg.get("json_dir") or "data/weekly_reports")
    prefix = str(out_cfg.get("json_prefix") or "weekly_report_")
    out_dir = Path(rel)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    pr = report.get("period_range") or report.get("week") or {}
    end_s = pr.get("end") or date.today().isoformat()
    if period == "monthly":
        fname = f"{prefix}{str(end_s)[:7]}.json"
    elif period in ("h1", "h2"):
        fname = f"{prefix}{str(end_s)[:4]}_{period}.json"
    elif period == "annual":
        fname = f"{prefix}{str(end_s)[:4]}.json"
    else:
        fname = f"{prefix}{end_s}.json"
    path = out_dir / fname
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_weekly_report_json(report: dict[str, Any], mapping: dict[str, Any], root: Path) -> Path:
    return save_broker_period_json(report, mapping, root, str(report.get("period") or "weekly"))


def _prev_month_bounds(today: date) -> tuple[date, date]:
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    return last_prev.replace(day=1), last_prev


def resolve_period_bounds(period: str, as_of: date) -> tuple[date, date]:
    p = period.strip().lower()
    if p == "weekly":
        return resolve_week_bounds(as_of)
    if p == "monthly":
        if as_of.day == 1 or (as_of.day <= 5 and as_of.weekday() < 5):
            return _prev_month_bounds(as_of)
        return as_of.replace(day=1), as_of
    y = as_of.year
    if p == "h1":
        if as_of.month >= 7 and as_of.day <= 5 and as_of.weekday() < 5:
            return date(y, 1, 1), date(y, 6, 30)
        if as_of.month >= 7:
            return date(y, 1, 1), date(y, 6, 30)
        return date(y - 1, 1, 1), date(y - 1, 6, 30)
    if p == "h2":
        if as_of.month == 1 and as_of.day <= 5 and as_of.weekday() < 5:
            return date(y - 1, 7, 1), date(y - 1, 12, 31)
        return date(y - 1, 7, 1), date(y - 1, 12, 31)
    if p == "annual":
        if as_of.month == 1 and as_of.day <= 5 and as_of.weekday() < 5:
            py = y - 1
            return date(py, 1, 1), date(py, 12, 31)
        py = y - 1
        return date(py, 1, 1), date(py, 12, 31)
    raise ValueError(f"未知 period: {period}")


def resolve_week_bounds(as_of: date) -> tuple[date, date]:
    """默认统计「上一交易周」周一至周五。周一跑报时取刚结束的一周；周五 as_of 可取本周一至当天。"""
    wd = as_of.weekday()
    if wd == 4:
        return as_of - timedelta(days=4), as_of
    mon, fri, _ = _last_completed_trading_week_mon_fri(as_of)
    return mon, fri


def run_broker_period_report(
    *,
    period: str,
    cfg: dict[str, Any],
    root: Path,
    as_of: date | None = None,
    xls_path: Path | None = None,
    mapping_path: Path | None = None,
    send: bool = True,
) -> dict[str, Any]:
    period = period.strip().lower()
    if period not in PERIOD_LABELS:
        raise ValueError(f"period 须为 {list(PERIOD_LABELS)}")

    mapping = load_mapping_config(mapping_path)
    broker_dir = root / "broker_xls"
    today = as_of or date.today()
    period_start, period_end = resolve_period_bounds(period, today)
    if period == "weekly" and today.weekday() >= 5:
        _LOG.warning(
            "as_of 为周末，周报区间按上一交易周: %s ~ %s", period_start, period_end
        )

    files = list_broker_files(broker_dir, mapping, xls_path=xls_path)
    primary = pick_primary_broker_file(files, as_of=today)

    report = build_broker_period_report(
        cfg=cfg,
        root=root,
        mapping=mapping,
        broker_dir=broker_dir,
        files=files,
        primary_file=primary,
        as_of=today,
        period=period,
        period_start=period_start,
        period_end=period_end,
    )
    json_path = save_broker_period_json(report, mapping, root, period)
    report["json_path"] = str(json_path)
    text = format_broker_period_text(report)
    report["text_summary"] = text

    print(text, flush=True)
    _LOG.info("broker_%s_report: wrote %s", period, json_path)

    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    key = f"broker_{period}_report_email_enabled"
    if period == "weekly":
        email_on = bool(oa.get("weekly_broker_report_email_enabled", oa.get(key, True)))
    else:
        email_on = bool(oa.get(key, oa.get("broker_period_report_email_enabled", True)))
    if send and email_on:
        label = PERIOD_LABELS.get(period, "报告")
        subj = (
            f"[股价监控] 券商{label} "
            f"{period_start.isoformat()}～{period_end.isoformat()}"
        )
        ok = notify_weekly_report(cfg, subject=subj, body=text)
        _LOG.info("broker_%s_report: notify %s", period, "ok" if ok else "failed")
        report["notified"] = ok
    else:
        report["notified"] = False
    return report


def run_weekly_report(
    *,
    cfg: dict[str, Any],
    root: Path,
    as_of: date | None = None,
    xls_path: Path | None = None,
    mapping_path: Path | None = None,
    send: bool = True,
) -> dict[str, Any]:
    return run_broker_period_report(
        period="weekly",
        cfg=cfg,
        root=root,
        as_of=as_of,
        xls_path=xls_path,
        mapping_path=mapping_path,
        send=send,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="中信证券交割单周报")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--as-of",
        type=str,
        default="",
        help="报告锚定日 YYYY-MM-DD（默认今天；周报统计上一交易周 Mon–Fri）",
    )
    ap.add_argument("--xls", type=Path, default=None, help="指定单个交割单文件")
    ap.add_argument("--mapping", type=Path, default=None, help="mapping_config.json 路径")
    ap.add_argument("--no-send", action="store_true", help="只生成 JSON/打印，不发送")
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1

    from run_alert import merge_full_config

    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    as_of: date | None = None
    if args.as_of.strip():
        try:
            as_of = datetime.strptime(args.as_of.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            print("--as-of 须为 YYYY-MM-DD", file=sys.stderr)
            return 1

    try:
        run_weekly_report(
            cfg=cfg,
            root=ROOT,
            as_of=as_of,
            xls_path=args.xls,
            mapping_path=args.mapping,
            send=not args.no_send,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        _LOG.exception("weekly_report failed")
        print(f"周报生成失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
