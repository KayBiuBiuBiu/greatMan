"""A 股 T+1 展示与通知过滤层：不改变策略打分，仅约束信号输出与风控提示。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

SH_TZ = "Asia/Shanghai"


def shanghai_today() -> date:
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(SH_TZ)).date()
    return datetime.now().date()


def shanghai_today_iso() -> str:
    return shanghai_today().isoformat()


def _parse_iso_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def next_a_share_session_start(from_d: date) -> date:
    """下一「可卖/可再买」自然日参考：周五买入则周一；不含法定节假日。"""
    wd = from_d.weekday()
    if wd == 4:
        return from_d + timedelta(days=3)
    if wd == 5:
        return from_d + timedelta(days=2)
    if wd == 6:
        return from_d + timedelta(days=1)
    return from_d + timedelta(days=1)


def _rec(state: dict[str, Any], code6: str) -> dict[str, Any]:
    root = state.setdefault("t1_by_code", {})
    if not isinstance(root, dict):
        state["t1_by_code"] = {}
        root = state["t1_by_code"]
    ent = root.get(code6)
    if not isinstance(ent, dict):
        ent = {}
        root[code6] = ent
    return ent


def _is_buy_sig(sig: str) -> bool:
    return "【买入信号】" in sig


def _is_sell_sig(sig: str) -> bool:
    return "【卖出信号】" in sig


@dataclass
class T1StrategyPlan:
    show_line: bool
    line_text: str
    allow_notify: bool
    allow_email_buy: bool
    allow_email_sell: bool
    commit_side: Literal["buy", "sell", None]
    log_sig: str
    suppressed_sell: bool
    suppressed_buy: bool
    suppressed_duplicate_buy: bool


def plan_strategy_t1(code6: str, sig: str, state: dict[str, Any]) -> T1StrategyPlan:
    today = shanghai_today()
    today_s = today.isoformat()
    rec = _rec(state, code6)
    lb = _parse_iso_date(rec.get("last_buy_emit_date"))
    ls = _parse_iso_date(rec.get("last_sell_emit_date"))

    if _is_buy_sig(sig):
        if ls is not None and today < next_a_share_session_start(ls):
            unlock = next_a_share_session_start(ls).isoformat()
            bh_key = "buy_suppress_after_sell_hint_date"
            show_hint = str(rec.get(bh_key) or "") != today_s
            if show_hint:
                rec[bh_key] = today_s
            return T1StrategyPlan(
                show_line=show_hint,
                line_text=(
                    f"（T+1）距上次卖出未满一个交易日窗口，买入提示已抑制（解锁参考日 {unlock}）"
                ),
                allow_notify=False,
                allow_email_buy=False,
                allow_email_sell=False,
                commit_side=None,
                log_sig=sig,
                suppressed_sell=False,
                suppressed_buy=True,
                suppressed_duplicate_buy=False,
            )
        if lb == today:
            return T1StrategyPlan(
                show_line=False,
                line_text="",
                allow_notify=False,
                allow_email_buy=False,
                allow_email_sell=False,
                commit_side=None,
                log_sig=sig,
                suppressed_sell=False,
                suppressed_buy=False,
                suppressed_duplicate_buy=True,
            )
        return T1StrategyPlan(
            show_line=True,
            line_text=sig,
            allow_notify=True,
            allow_email_buy=True,
            allow_email_sell=False,
            commit_side="buy",
            log_sig=sig,
            suppressed_sell=False,
            suppressed_buy=False,
            suppressed_duplicate_buy=False,
        )

    if _is_sell_sig(sig):
        if lb is not None and today < next_a_share_session_start(lb):
            hint_key = "sell_suppress_hint_date"
            show_hint = str(rec.get(hint_key) or "") != today_s
            if show_hint:
                rec[hint_key] = today_s
            return T1StrategyPlan(
                show_line=show_hint,
                line_text="（T+1）今日已触发买入，卖出/减仓类策略提示暂不展示",
                allow_notify=False,
                allow_email_buy=False,
                allow_email_sell=False,
                commit_side=None,
                log_sig=sig,
                suppressed_sell=True,
                suppressed_buy=False,
                suppressed_duplicate_buy=False,
            )
        return T1StrategyPlan(
            show_line=True,
            line_text=sig,
            allow_notify=True,
            allow_email_buy=False,
            allow_email_sell=True,
            commit_side="sell",
            log_sig=sig,
            suppressed_sell=False,
            suppressed_buy=False,
            suppressed_duplicate_buy=False,
        )

    return T1StrategyPlan(
        show_line=True,
        line_text=sig,
        allow_notify=True,
        allow_email_buy=False,
        allow_email_sell=False,
        commit_side=None,
        log_sig=sig,
        suppressed_sell=False,
        suppressed_buy=False,
        suppressed_duplicate_buy=False,
    )


def commit_strategy_emit(
    code6: str, side: Literal["buy", "sell"], state: dict[str, Any]
) -> None:
    today_s = shanghai_today_iso()
    rec = _rec(state, code6)
    if side == "buy":
        rec["last_buy_emit_date"] = today_s
    elif side == "sell":
        rec["last_sell_emit_date"] = today_s


def should_suppress_risk_stop_take(code6: str, state: dict[str, Any]) -> bool:
    """买入信号已记入当日：在下一交易窗口前屏蔽止盈/止损类风控提醒。"""
    rec = _rec(state, code6)
    lb = _parse_iso_date(rec.get("last_buy_emit_date"))
    if lb is None:
        return False
    today = shanghai_today()
    return today < next_a_share_session_start(lb)
