"""买入过滤拦截（watch_strategy_buy_filtered）复盘：读 JSONL、估算后续日 K 收益、生成邮件正文。"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


def resolve_alert_jsonl_path(cfg: dict[str, Any], root: Path) -> Path | None:
    """与 app_logging 一致：logging.enabled + file；返回绝对路径（文件可不存在）。"""
    raw = cfg.get("logging") or {}
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return None
    rel = str(raw.get("file", "logs/run_alert.jsonl")).strip()
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = (root / p).resolve()
    return p


def infer_market(code6: str) -> str:
    c = str(code6).strip()
    if len(c) != 6 or not c.isdigit():
        return "sh"
    if c.startswith(("6", "9")):
        return "sh"
    return "sz"


def parse_event_date(ts: str) -> date | None:
    s = str(ts).strip()
    if len(s) >= 10:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return None


def anchor_index(dates: list[str], ev: date) -> int | None:
    evs = ev.strftime("%Y-%m-%d")
    for i, d in enumerate(dates):
        di = str(d).strip()[:10]
        if di >= evs:
            return i
    return None


def forward_close_return(
    code: str,
    market: str,
    *,
    anchor: date,
    forward_days: int,
    ut: str | None,
) -> float | None:
    from quote_eastmoney import fetch_kline_rows_for_secid, resolve_ut, secid_for

    if forward_days <= 0:
        return None
    try:
        sid = secid_for(code, market)
    except ValueError:
        return None
    u = resolve_ut(ut)
    rows = fetch_kline_rows_for_secid(sid, u, lmt=max(80, forward_days + 40))
    if not rows:
        return None
    dates = [str(r[0]).strip()[:10] for r in rows]
    closes = [float(r[4]) for r in rows]
    i0 = anchor_index(dates, anchor)
    if i0 is None:
        return None
    j = i0 + forward_days
    if j >= len(closes):
        return None
    c0 = float(closes[i0])
    c1 = float(closes[j])
    if c0 <= 0:
        return None
    return c1 / c0 - 1.0


def load_buy_filter_events(jsonl_path: Path) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if not jsonl_path.is_file():
        return events
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "watch_strategy_buy_filtered":
                continue
            code = str(row.get("code") or "").strip()
            if len(code) != 6 or not code.isdigit():
                continue
            evd = parse_event_date(str(row.get("ts") or ""))
            if evd is None:
                continue
            events.append(
                {
                    "code": code,
                    "date": evd.isoformat(),
                    "reason": str(row.get("skipped_by_filter") or "")[:120],
                }
            )
    return events


def build_friday_buy_filter_digest(
    cfg: dict[str, Any],
    root: Path,
    *,
    forward_days: int,
    max_events: int,
    ut: str | None = None,
) -> tuple[str, str]:
    """
    生成 (邮件标题, 正文)。
    依赖 JSONL 与东财日 K；logging 未启用或文件缺失时仍返回说明性正文。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"【复盘】买入过滤拦截｜后{forward_days}交易日收益（{today}）"

    jp = resolve_alert_jsonl_path(cfg, root)
    if jp is None:
        body = (
            "本周报未执行数据统计：请在 config 中开启 logging.enabled，"
            "并指定 logging.file（如 logs/run_alert.jsonl），"
            "以便记录 watch_strategy_buy_filtered 事件。\n"
        )
        return subject, body

    events = load_buy_filter_events(jp)
    lines: list[str] = [
        f"数据源: {jp}",
        f"forward_days={forward_days}，最多处理事件数={max_events}",
        "",
    ]
    if not events:
        lines.append(
            "本周 JSONL 中未发现 watch_strategy_buy_filtered 事件（无买入信号被实时过滤记录）。"
        )
        return subject, "\n".join(lines)

    events = events[-max(1, int(max_events)) :]
    rets: list[float] = []
    fail_n = 0
    by_reason: dict[str, list[float]] = defaultdict(list)
    for e in events:
        mkt = infer_market(e["code"])
        try:
            r = forward_close_return(
                e["code"],
                mkt,
                anchor=date.fromisoformat(e["date"]),
                forward_days=int(forward_days),
                ut=ut,
            )
        except Exception:
            r = None
        if r is None:
            fail_n += 1
            continue
        rets.append(r)
        key = e["reason"] or "(empty)"
        by_reason[key].append(r)

    n = len(events)
    lines.append(
        f"样本事件: {n}（收益估算成功 {len(rets)}，失败或数据不足 {fail_n}）"
    )
    if rets:
        pct = [x * 100.0 for x in rets]
        lines.append(
            f"收益%: 均值 {statistics.mean(pct):.2f}  中位 {statistics.median(pct):.2f}  "
            f"最小 {min(pct):.2f}  最大 {max(pct):.2f}"
        )
    lines.append("")
    lines.append("按拦截原因（TOP12，仅含成功算出收益的样本）：")
    for reason, xs in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))[:12]:
        ps = [x * 100.0 for x in xs]
        rshort = reason if len(reason) <= 100 else reason[:100] + "…"
        lines.append(f"  [{len(xs)}] {rshort} | 均值 {statistics.mean(ps):.2f}%")
    lines.append("")
    lines.append(
        "说明：锚定日为日志事件日期当日起首根可用日 K；收益为收盘价涨跌幅，非实盘。"
    )
    return subject, "\n".join(lines)
