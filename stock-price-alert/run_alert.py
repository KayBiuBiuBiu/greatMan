#!/usr/bin/env python3
"""
沪深 A 股监控：现价 / 区间提醒 + 1W 风控（补仓摊薄、止盈止损）+
均线箱体策略 + 控制台 & 系统通知双通道。
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
from collections import OrderedDict
from contextlib import nullcontext
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _maybe_reexec_with_project_venv() -> None:
    """仓库内若有 .venv，则用其解释器重启进程（可直接 `python run_alert.py -c config.json`）。"""
    if os.environ.get("STOCK_ALERT_NO_VENV_REEXEC") == "1":
        return
    # 被 pytest / 其它库 import 时不要 execv，否则会换掉测试进程
    if any(m in sys.modules for m in ("pytest", "_pytest")):
        return
    if getattr(sys, "frozen", False):
        return
    if sys.platform == "win32":
        vpy = ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        vpy = ROOT / ".venv" / "bin" / "python3"
        if not vpy.is_file():
            vpy = ROOT / ".venv" / "bin" / "python"
    if not vpy.is_file():
        return
    try:
        if Path(sys.executable).resolve() == vpy.resolve():
            return
    except OSError:
        return
    os.environ["STOCK_ALERT_NO_VENV_REEXEC"] = "1"
    os.execv(str(vpy), [str(vpy)] + sys.argv)


_maybe_reexec_with_project_venv()

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s) if s else s


def _emit_watch_line(
    rendered: str,
    *,
    event: str,
    code: str | None = None,
    rk: str | None = None,
    section: str = "watch_pack",
    duration_ms: float | None = None,
    level: int = logging.INFO,
    skipped_by_filter: str | None = None,
) -> None:
    print(rendered)
    try:
        from app_logging import record_alert_event

        record_alert_event(
            level,
            _strip_ansi(rendered),
            event=event,
            code=code,
            rk=rk,
            section=section,
            duration_ms=duration_ms,
            skipped_by_filter=skipped_by_filter,
        )
    except Exception:
        pass


def _emit_fetch_line(
    print_lock: threading.Lock,
    rendered: str,
    *,
    event: str,
    code: str,
    rk: str | None = None,
    level: int = logging.WARNING,
) -> None:
    with print_lock:
        print(rendered)
    try:
        from app_logging import record_alert_event

        record_alert_event(
            level,
            _strip_ansi(rendered),
            event=event,
            code=code,
            rk=rk,
            section="fetch",
        )
    except Exception:
        pass


def _emit_main_line(
    rendered: str,
    *,
    event: str,
    duration_ms: float | None = None,
    level: int = logging.INFO,
) -> None:
    print(rendered)
    try:
        from app_logging import record_alert_event

        record_alert_event(
            level,
            _strip_ansi(rendered),
            event=event,
            section="main_loop",
            duration_ms=duration_ms,
        )
    except Exception:
        pass


def _cli_print_blank() -> None:
    print(file=sys.stdout, flush=True)


def _emit_cli_subcmd_line(msg: str, *, event: str) -> None:
    """子命令与 CLI 提示：stdout；若 logging 已启用则写 JSONL（同 emit_select_tool_line）。"""
    if not msg:
        _cli_print_blank()
        return
    from app_logging import emit_select_tool_line

    emit_select_tool_line(_strip_ansi(msg), event=event, section="run_alert_cli")


def _backup_user_config_file(config_path: Path) -> None:
    """将正在使用的配置文件复制为同目录下 「原名.bak」（与 auto_tune 等备份并存）。"""
    dst = config_path.parent / f"{config_path.name}.bak"
    try:
        shutil.copy2(config_path, dst)
    except OSError as e:
        print(
            f"[config] 无法备份配置: {config_path} -> {dst} （{e}）",
            file=sys.stderr,
        )


def _ensure_app_logging_from_config_path(config_path: Path) -> None:
    """尽早 setup_app_logging，使子命令 / 早期 CLI 输出可写入 JSONL。"""
    if not config_path.exists():
        return
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return
    cfg0 = merge_full_config(raw)
    from app_logging import setup_app_logging

    setup_app_logging(cfg0, root=ROOT)


from macro_risk import (
    configure_index_kline_cache,
    fetch_index_5d_return,
    fetch_index_mood_mult,
    get_market_mood_three_tier,
    macro_score_multiplier,
)
from strategy_buy_filter_resolve import resolve_effective_strategy_buy_filter
from email_notify import (
    send_buy_signal_email,
    send_email_alert,
    send_sell_signal_email,
)
from alert_log_store import apply_feedback_to_latest_alert
from email_command_bot import fetch_email_bot_actions
from notify_macos import send_notification
from pick_score import composite_pick_score
from position_tags import format_tags_line, has_position_tag, normalize_tags_field
from quote_eastmoney import (
    DEFAULT_UT,
    configure_kline_performance,
    configure_kline_store_from_cfg,
    configure_quote_live_from_cfg,
    fetch_price,
    fetch_quote_metrics,
    fetch_quote_metrics_bulk,
    get_bk_kline_data,
    get_stock_kline_data,
    normalize_bk_code,
    resolve_ut,
    secid_for,
)
from sector_em import clear_round_cache as sector_clear_round_cache, resolve_sector_bk
from risk_control import RiskManager
from strategy_engine import ma_box_strategy
from t1_guard import (
    commit_strategy_emit,
    plan_strategy_t1,
    should_suppress_risk_stop_take,
    T1StrategyPlan,
)
from trade_log import log_signal
from trend_slippage_risk import evaluate_trend_slippage_alert
from trend_slip_confirm import consecutive_trend_slip_notify_ok
from realtime_hub import hub_from_cfg
from ml_infer import (
    build_feature_vector as build_ml_feature_vector,
    load_model_cached as load_ml_model_cached,
    predict_bearish_probability as predict_ml_bearish_probability,
    resolve_model_path as resolve_ml_model_path,
)

# ---------------- 股票名称：本地主表 + 小缓存 + 单次接口补充 ----------------
# 主数据：a_share_names.json（python build_a_share_name_table.py 生成/更新，全市场代码→简称）
# 补充：stock_name_cache.json（接口曾成功写过的简称，退市等可能仅存于此）
CACHE_FILE = ROOT / "stock_name_cache.json"
A_SHARE_NAMES_FILE = ROOT / "a_share_names.json"
_a_share_static: dict[str, str] | None = None

stock_name_cache: dict[str, str] = {}
_name_resolve_lock = threading.Lock()
_name_proc_memo: OrderedDict[str, str] = OrderedDict()
_NAME_MEMO_CAP = 3000


def _name_memo_touch(c6: str, name: str) -> None:
    if not c6 or len(c6) != 6 or not c6.isdigit():
        return
    n = str(name).strip()
    if not n or n == c6:
        return
    _name_proc_memo[c6] = n
    _name_proc_memo.move_to_end(c6)
    while len(_name_proc_memo) > _NAME_MEMO_CAP:
        _name_proc_memo.popitem(last=False)
if CACHE_FILE.exists():
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            stock_name_cache = {str(k): str(v) for k, v in raw.items()}
    except Exception:
        stock_name_cache = {}


def _normalized_code6(code: str) -> str:
    s = str(code).strip()
    if not s:
        return s
    if s.isdigit() and len(s) <= 6:
        return s.zfill(6)
    return s


def _load_a_share_static_names() -> dict[str, str]:
    """读取 a_share_names.json（仅六位数字键为股票）。"""
    global _a_share_static
    if _a_share_static is not None:
        return _a_share_static
    _a_share_static = {}
    if not A_SHARE_NAMES_FILE.exists():
        return _a_share_static
    try:
        raw = json.loads(A_SHARE_NAMES_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k, v in raw.items():
                ks = str(k).strip()
                if len(ks) == 6 and ks.isdigit():
                    _a_share_static[ks] = str(v).strip()
    except Exception:
        pass
    return _a_share_static


def save_stock_name_cache() -> None:
    try:
        CACHE_FILE.write_text(
            json.dumps(stock_name_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def get_stock_name(code: str) -> str:
    """
    名称解析顺序（尽量快）：
    1) a_share_names.json 本地主表（命中则零网络）
    2) stock_name_cache.json 中曾成功的简称
    3) 东财个股信息接口补一条（不再拉全市场 spot，避免巨慢）
    4) 仍失败则暂用代码，并写入缓存避免反复打接口
    """
    with _name_resolve_lock:
        return _get_stock_name_unlocked(code)


def _get_stock_name_unlocked(code: str) -> str:
    raw = str(code).strip()
    if not raw:
        return raw
    c6 = _normalized_code6(raw)

    if c6 and len(c6) == 6 and c6.isdigit():
        hit = _name_proc_memo.get(c6)
        if hit and str(hit).strip() and str(hit).strip() != c6:
            _name_proc_memo.move_to_end(c6)
            return str(hit).strip()

    static = _load_a_share_static_names()
    if c6 and len(c6) == 6 and c6.isdigit() and c6 in static and static[c6]:
        n = static[c6]
        _name_memo_touch(c6, n)
        return n

    for k in (c6, raw):
        if k in stock_name_cache:
            cv = stock_name_cache[k]
            if cv and str(cv).strip() != str(k).strip():
                out0 = str(cv).strip()
                if c6 and len(c6) == 6 and c6.isdigit():
                    _name_memo_touch(c6, out0)
                return out0

    c = c6 if (c6 and len(c6) == 6 and c6.isdigit()) else raw

    try:
        import akshare as ak

        info = ak.stock_individual_info_em(symbol=c)
        name = str(info.loc[info["item"] == "股票简称", "value"].values[0])
        stock_name_cache[c6 if c6 else c] = name
        save_stock_name_cache()
        time.sleep(0.1)
        if c6 and len(c6) == 6 and c6.isdigit():
            _name_memo_touch(c6, name)
        return name
    except Exception:
        pass

    out = c6 if c6 else raw
    stock_name_cache[out] = out
    save_stock_name_cache()
    return out


MIN_INTERVAL = 10
# 默认：盘中 poll_interval_seconds、非交易 trading_closed_interval（秒）
POLL_INTERVAL = 30
DEFAULT_POLL = POLL_INTERVAL
DEFAULT_CLOSED_INTERVAL = 60
DEFAULT_COOLDOWN_MIN = 5
DEFAULT_BUFFER = 0.02
FUSE_MIN_INTERVAL = 30
# 监控池为空时，避免每轮 sleep 都刷同一条 CLI 提示（秒）
EMPTY_WATCH_STATUS_LOG_SEC = 300.0

DEFAULT_CAPITAL = {
    "total": 200000,
    "max_total_position_ratio": 0.5,
    "max_single_stock_ratio": 0.3,
}
DEFAULT_BUY_RULE = {
    "base_position": 1000,
    "add_1_ratio": -0.03,
    "add_1_money": 800,
    "add_2_ratio": -0.06,
    "add_2_money": 700,
    "forbid_add_ratio": -0.08,
}
DEFAULT_RISK_RULE = {
    "stop_loss_ratio": -0.05,
    "take_profit_short": 0.05,
    "take_profit_wave": 0.10,
}
DEFAULT_DRAWDOWN_ALERT = {
    "enabled": True,
    "warn_1_ratio": -0.03,
    "warn_2_ratio": -0.06,
    "warn_3_ratio": -0.1,
    "alert_ignore_codes": [],
}
DEFAULT_ATR_TIERS = {
    "enabled": True,
    "method": "wilder",
    "lookback": 20,
    "tiers": [
        {
            "max_close_atr_pct": 2.0,
            "stock_min_weak_dims": 2,
            "sector_min_weak_dims": 2,
            "min_pillars_weak": 2,
        },
        {
            "max_close_atr_pct": 4.0,
            "stock_min_weak_dims": 2,
            "sector_min_weak_dims": 2,
            "min_pillars_weak": 2,
        },
        {
            "max_close_atr_pct": None,
            "stock_min_weak_dims": 3,
            "sector_min_weak_dims": 3,
            "min_pillars_weak": 2,
        },
    ],
}
DEFAULT_DYNAMIC_ADAPTIVE = {
    "enabled": False,
    "ma_period": 20,
    "bull_min_pillars": 3,
    "bear_min_pillars": 2,
    "volume_ratio_active": 1.2,
    "use_volume_filter": False,
    # 三档：强牛 / 震荡 / 弱熊（需 MA+RSI+布林宽度，可选上证量能）
    "use_mood_three_tier": False,
    "strong_bull_min_pillars": 4,
    "range_min_pillars": 3,
    "weak_bear_min_pillars": 2,
    "rsi_period": 14,
    "rsi_strong_bull_min": 56.0,
    "rsi_weak_bear_max": 44.0,
    "bb_period": 20,
    "bb_width_min_for_strong": 0.012,
    # 板块相对上证 N 日收益微调 min_pillars_weak
    "sector_rs_enabled": False,
    "sector_rs_ret_days": 20,
    "sector_rs_outperform_pct": 0.005,
    "sector_rs_underperform_pct": -0.005,
    "sector_rs_strong_delta": 1,
    "sector_rs_weak_delta": -1,
}
DEFAULT_TREND_SLIPPAGE_ALERT = {
    "enabled": True,
    "require_resolved_bk": False,
    "min_pillars_weak": 2,
    "stock_min_weak_dims": 2,
    "sector_min_weak_dims": 2,
    "index_weak_mult_max": 0.99,
    "index_5d_ret_weak": -0.008,
    "volume_spike_vs_ma20": 1.85,
    "near_high_20_ratio": 0.88,
    "atr_tiers": copy.deepcopy(DEFAULT_ATR_TIERS),
    "verbose_trend_alert": True,
    "min_price": 0.0,
    "min_float_mv_yi": 0.0,
    "min_volume_ratio": 0.0,
    "alert_ignore_codes": [],
    "require_consecutive_trade_days": 1,
    "dynamic_adaptive": copy.deepcopy(DEFAULT_DYNAMIC_ADAPTIVE),
}
DEFAULT_DATA_HEALTH = {
    "enabled": True,
    "host_consecutive_fail_threshold": 5,
    "backoff_cap_sec": 16.0,
    "backoff_base_sec": 0.25,
    "full_outage_consecutive_notify_threshold": 0,
    "full_outage_email_enabled": False,
    "recovery_notify_enabled": True,
    "suppress_trend_rounds_after_full_outage": 0,
    # 非空路径且 interval>0 时写入 JSON（相对 stock-price-alert 根目录）
    "heartbeat_path": "",
    "heartbeat_interval_sec": 180,
}
DEFAULT_NOTIFICATIONS = {
    "aggregate_interval_alerts": True,
    "aggregate_max_items": 20,
    "aggregate_trend_alerts": True,
    "aggregate_trend_max_items": 15,
    # 远程投递：email=仅 SMTP；wecom=仅企业微信机器人；both=邮件+企微双发；none=不发（仍可有本机通知）
    "remote_channel": "both",
    "wecom_webhook": {
        "enabled": True,
        "webhook_url": "",
        # text 与 curl 一致、兼容性最好；markdown 支持 <font color="warning"> 等
        "msgtype": "text",
    },
}
DEFAULT_LOGGING = {
    "enabled": True,
    "file": "logs/run_alert.jsonl",
    "max_bytes": 5_000_000,
    "backup_count": 3,
    "level": "INFO",
    "console_mirror": False,
}
POSITION_SUGGESTION_EVAL_DEFAULT: dict[str, float] = {
    # 百分比数值，如 -0.5 表示 -0.5%
    "sell_hit_r5_below_pct": -0.5,
    "sell_miss_r5_above_pct": 1.5,
    "add_hit_r5_above_pct": 0.5,
    "add_miss_r5_below_pct": -2.0,
    "hold_hit_abs_r5_below_pct": 3.0,
    "hold_miss_abs_r5_above_pct": 6.0,
}
STRATEGY_HIT_EVAL_DEFAULT: dict[str, float] = {
    "buy_hit_r5_above_pct": 0.0,
    "sell_hit_r5_below_pct": 0.0,
    "buy_hit_r1_above_pct": 0.0,
    "sell_hit_r1_below_pct": 0.0,
}
RISK_STOP_TAKE_EVAL_DEFAULT: dict[str, float] = {
    "take_profit_hit_r1_above_pct": 0.5,
    # 1=卖对算 hit（跌）；0=旧语义卖飞算 hit（配合 take_profit_hit_r1_above_pct）
    "take_profit_hit_for_correctness": 1.0,
}
DEFAULT_ALERT_LOG = {
    "enabled": False,
    "share_kline_db": True,
    "db_path": "data/alert_events.db",
    "bearish_hit_threshold_pct_1d": -2.0,
    "bearish_hit_threshold_pct_3d": -2.5,
    "bearish_hit_threshold_pct_5d": -3.0,
    "position_suggestion_eval": dict(POSITION_SUGGESTION_EVAL_DEFAULT),
    "strategy_hit_eval": dict(STRATEGY_HIT_EVAL_DEFAULT),
    "risk_stop_take_eval": dict(RISK_STOP_TAKE_EVAL_DEFAULT),
}
DEFAULT_ML_FILTER = {
    "enabled": False,
    "model_path": "data/ml_bearish_nb.json",
    "apply_to_alert_types": ["trend_slip"],
    "bearish_prob_threshold": 0.60,
    "kline_rf_enabled": False,
    "kline_rf_db_path": "data/baostock_full.db",
    "kline_rf_table": "daily_klines",
    "kline_rf_model_path": "models/kline_rf.pkl",
    "kline_rf_suppress_below": 0.30,
    # any：任一模型认为「弱势/大跌概率」低于各自阈值即抑制；all：仅当已启用且算出概率的模型都低于阈值才抑制
    "suppress_combo": "any",
    # AkShare 资金/北向/龙虎榜附加特征（需重训 NB；默认关闭以保持与旧模型兼容）
    "external_flow_features_enabled": False,
    "external_flow_days": 10,
    # 个股北向持股接口若滞后于锚定日超过该天数，则 ext_north_mv_chg_ratio 置 0（避免用陈旧序列误导 NB）
    "external_flow_north_max_lag_days": 120,
    # True：滞后时打 INFO；False：仅 DEBUG（默认安静）
    "external_flow_warn_stale_north": False,
}
DEFAULT_OPS_AUTOMATION = {
    "enabled": True,
    "preopen_enabled": True,
    "preopen_cutoff_hhmm": "09:20",
    "after_close_enabled": True,
    "after_close_hhmm": "15:10",
    "friday_weekly_enabled": True,
    "backtest_since_days": 7,
    "auto_tune_apply": True,
    "auto_tune_email": True,
    "ml_train_weekly": True,
    "ml_train_days": 180,
    "ml_train_min_samples": 18,
    # 开盘前自愈：日 K 过旧则 sync、行业缓存过旧则删文件强制重拉、pending 预警过多则补算回测
    "self_health_enabled": False,
    "self_health_kline_max_lag_calendar_days": 1,
    "self_health_pending_alerts_min": 200,
    "self_health_sector_cache_ttl_mult": 2.0,
    # 周五在 ml_train 之后可选重训日 K 随机森林（需本机 sklearn；路径取自 ml_filter）
    "friday_kline_rf_train_enabled": False,
    "incremental_nb_after_close": False,
    "incremental_nb_days": 30,
    "incremental_nb_min_samples": 12,
    # 周五收盘后任务内：买入过滤拦截复盘 → 邮件+企微（走 notifications.remote_channel）
    "friday_buy_filter_digest_enabled": True,
    "buy_filter_digest_forward_days": 5,
    "buy_filter_digest_max_events": 200,
}
DEFAULT_MONITORING = {
    # true：忽略 daily_picks.json 优质股扩容，仅轮询 config watchlist（+ 运行时 hold 补票）
    "watchlist_only": False,
    # true：即使非 watchlist_only，也不在进程启动时跑盘前选股（优质池依赖 ops_automation 或手动选股）
    "skip_startup_daily_select": False,
}
DEFAULT_QUANT_SELECTOR = {
    # 优质池：因子分 + 回测门槛（见 quant_core.selector._classify）
    "score_min_quality": 7.0,
    "score_min_watch": 5.5,
    "profit_1y_min": 0.0,
    "win_1y_min": 50.0,
    "profit_3y_floor": -8.0,
}
DEFAULT_STRATEGY_SIGNAL = {
    # 各策略参考分下限（仅压制买入类 action，卖出/风控仍保留）
    "min_score_by_strategy": {
        "ma_dip": 72.0,
        "box_breakout": 78.0,
        "range_arbitrage": 74.0,
    },
}
DEFAULT_STRATEGY_BUY_FILTER = {
    "enabled": True,
    # 日 K 量比（末根量 / 前 20 日均量）；≤0 表示不做量比过滤
    "min_volume_ratio": 1.2,
    # 上证三档 mood 为 weak_bear 时不采纳买入信号（与 position 建议用的 tier 独立，见代码注释）
    "block_weak_bear": True,
    # 日内位置过滤（依赖 RealtimeQuoteHub 增量统计 + pack["q"] 中 intraday_position；默认关闭）
    "use_intraday_position_filter": False,
    "min_intraday_position": 0.3,
    "max_intraday_position": 0.85,
}
DEFAULT_SECTOR_BUY_CROSS_CHECK = {
    "enabled": False,
    # vote：有效维度≥min_evaluated_dims 时，通过票数≥min_pass_votes 则放行；
    # weighted：按 weights 加权得分≥pass_weighted_threshold 则放行。
    "mode": "vote",
    "min_evaluated_dims": 2,
    "min_pass_votes": 2,
    "pass_weighted_threshold": 0.5,
    "weights": {
        "sector_rs_vs_index": 1.0,
        "sector_above_ma20": 1.0,
        "stock_vs_sector_rs": 1.0,
    },
    # 板块 5 日收益可略弱于大盘（小数，如 -0.003 表示可低 0.3%）
    "sector_rs_vs_index_margin": -0.003,
    # 收盘允许略低于 MA20（比例容忍，如 0.002）
    "ma20_tolerance": 0.002,
    # 个股 5 日可弱于板块的最大幅度（小数）
    "stock_vs_sector_max_lag": 0.02,
    # 无板块代码时不做本项过滤（放行）
    "require_sector_bk": True,
}
DEFAULT_ADAPTIVE_BY_MOOD = {
    "enabled": False,
    "strong_bull": {},
    "range": {},
    "weak_bear": {},
}
DEFAULT_POSITION_SUGGESTION = {
    "enabled": True,
    "rules": {
        "sell": {
            "profit_to_take": 0.15,
            "profit_break_ma5": True,
            "loss_stop": -0.08,
            "loss_below_ma20_and_ma60": True,
            "bearish_prob_threshold": 0.7,
            "box_high_threshold": 0.85,
            "volume_ratio_low": 0.8,
            "market_weak_bear_sell": True,
        },
        "add": {
            "loss_min": -0.20,
            "loss_max": -0.05,
            "require_above_ma20": True,
            "box_low_threshold": 0.4,
            "min_volume_ratio": 0.8,
            "forbid_market_weak_bear": True,
            "add_amount_tier1": 6000,
            "add_amount_tier2": 9000,
            "loss_tier2": -0.15,
        },
    },
}
DEFAULT_EMAIL_COMMAND_BOT = {
    "enabled": False,
    "use_shared_mail_config": True,
    "imap_server": "",
    "imap_port": 993,
    "imap_username": "",
    "imap_password": "",
    "imap_folder": "INBOX",
    "trusted_senders": [],
    "poll_interval_sec": 45,
    "mark_seen": True,
    # 邮件/控制台 set take_profit_hit_for_correctness 成功后是否自动跑 backtest_alerts --force
    "auto_backtest_on_take_profit_hit_change": False,
}
DEFAULT_SECTOR_EM = {
    "api_hosts": [
        "https://push2.eastmoney.com",
        "http://82.push2.eastmoney.com",
        "http://77.push2.eastmoney.com",
    ],
    "industry_clist_fs": ["m:90+t:2", "m:90+t:3"],
    "cache_filename": "sector_index_cache.json",
    "industry_map_ttl_sec": 3600,
}
DEFAULT_PERFORMANCE = {
    "kline_cache_ttl_sec": 900,
    "sector_kline_cache_ttl_sec": 3600,
    "index_kline_cache_ttl_sec": 60,
    # 为 True 时拉取当日 1 分钟 K 摘要写入 pack["minute_kline"]（增加请求量，默认关）
    "fetch_minute_kline_today": False,
    "minute_kline_max_bars": 256,
    # 分钟 K 进程内缓存秒数（越大越少重复请求；0=不缓存，仅调试）
    "minute_kline_cache_ttl_sec": 120.0,
    # 每轮最多拉几只的分钟 K；0=不限制（监控池大时请求多）
    "minute_kline_max_per_round": 0,
    # True：仅在上午盘 9:30–11:30 拉分钟 K（下午一般不消费则省请求）
    "minute_kline_am_session_only": True,
    # 为 True 时本轮轮询各阶段毫秒耗时写入控制台 + JSONL event=poll_round_timing；
    # 另打印一行「单票拉取耗时」按墙钟 ms 排序（含并行线程内整包耗时）。
    "log_poll_segment_ms": False,
    # 后台线程维护分钟 K 摘要，主轮询只读缓存（见 async_minute_kline.py）
    "async_minute_kline": {
        "enabled": False,
        "refresh_sec": 300,
        "max_bars": 240,
    },
    "enable_parallel_fetch": True,
    "fetch_max_workers": 4,
    "fetch_max_concurrency": 4,
    "request_min_interval_sec": 0.0,
    "hub_poll_start_offset_sec": 3.0,
    "safe_get_jitter_sec_min": 0.25,
    "safe_get_jitter_sec_max": 1.2,
    "http_domain_bucket_rps": 0.0,
    "http_domain_bucket_hosts": [],
    "process_watch_max_workers": 1,
    "name_prewarm_max_workers": 4,
    "hub_warm_timeout_sec": 12.0,
    "hub_warm_min_fraction": 0.85,
}
DEFAULT_KLINE_STORE = {
    "enabled": True,
    "db_path": "data/daily_klines.db",
    "fresh_hours_after_sync": 36,
    "divergence_warn_price_pct": None,
    "sync_skip_min_bars": 50,
    "sync_max_stale_calendar_days": 2,
    "sync_fetch_lmt": 1020,
    "sync_target_bars": 800,
    "use_indicator_last": False,
}
DEFAULT_REALTIME_HUB = {
    "enabled": True,
    "poll_interval_sec": 5.0,
    # True + eastmoney_sse：东财 SSE 推送写入 Hub 缓存（与 HTTP 轮询并存，盘中更及时）
    "ws_enabled": True,
    "ws_transport": "eastmoney_sse",
    "ws_url": "",
    "ws_reconnect_sec": 5.0,
    "ws_ping_interval_sec": 30.0,
    "em_sse_url": "",
    "em_sse_fields": "",
    "em_sse_slots": 4,
    "em_sse_burst_sec": 12.0,
    "em_sse_read_timeout_sec": 60.0,
}
DEFAULT_SCAN_RULE = {
    "min_price": 5.0,
    "max_price": 32.0,
    "min_amount": 5000.0,
    "min_daily_amount_wan": 6500.0,
    "min_float_mv_yi": 28.0,
    "max_float_mv_yi": 750.0,
    "full_scan_interval_days": 3.0,
    "max_turnover": 15.0,
}

TRADING_START_AM = dt_time(9, 30)
TRADING_END_AM = dt_time(11, 30)
TRADING_START_PM = dt_time(13, 0)
TRADING_END_PM = dt_time(15, 0)


def _no_color() -> bool:
    return bool(os.environ.get("NO_COLOR"))


def is_trading_session() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (TRADING_START_AM <= t <= TRADING_END_AM) or (
        TRADING_START_PM <= t <= TRADING_END_PM
    )


def _merge_trend_slippage_alert(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = copy.deepcopy(DEFAULT_TREND_SLIPPAGE_ALERT)
    u = dict(raw or {})
    u_atr = u.pop("atr_tiers", None)
    u_dyn = u.pop("dynamic_adaptive", None)
    base.update(u)
    merged_atr = copy.deepcopy(DEFAULT_ATR_TIERS)
    if isinstance(u_atr, dict):
        user_tiers = u_atr.get("tiers")
        merged_atr.update({k: v for k, v in u_atr.items() if k != "tiers"})
        if isinstance(user_tiers, list) and len(user_tiers) > 0:
            merged_atr["tiers"] = user_tiers
    base["atr_tiers"] = merged_atr
    da = copy.deepcopy(DEFAULT_DYNAMIC_ADAPTIVE)
    if isinstance(u_dyn, dict):
        da.update(u_dyn)
    base["dynamic_adaptive"] = da
    return base


def _market_state_log_label_three_tier(tier: str) -> str:
    return {"strong_bull": "牛市", "range": "震荡", "weak_bear": "熊市"}.get(tier, tier)


def _market_state_log_label_regime(regime: str) -> str:
    return {"bull": "牛市", "bear": "熊市"}.get(regime, regime)


def _compute_round_dynamic_min_pillars_weak(cfg: dict[str, Any]) -> tuple[int | None, str]:
    """按大盘情绪得到本轮动态 min_pillars_weak；未开启时返回 (None, '')。"""
    tc = cfg.get("trend_slippage_alert") or {}
    da = tc.get("dynamic_adaptive")
    if not isinstance(da, dict) or not bool(da.get("enabled", False)):
        return None, ""
    from macro_risk import get_market_mood_three_tier, get_market_regime

    ma_p = max(5, min(120, int(da.get("ma_period", 20) or 20)))
    if bool(da.get("use_mood_three_tier", False)):
        tier = get_market_mood_three_tier(dynamic_cfg=da)
        if tier == "strong_bull":
            v = int(da.get("strong_bull_min_pillars", da.get("bull_min_pillars", 4)))
        elif tier == "weak_bear":
            v = int(da.get("weak_bear_min_pillars", da.get("bear_min_pillars", 2)))
        else:
            v = int(da.get("range_min_pillars", 3))
        tag = _market_state_log_label_three_tier(tier)
    else:
        regime = get_market_regime(ma_period=ma_p, dynamic_cfg=da)
        if regime == "bull":
            v = int(da.get("bull_min_pillars", 3))
        else:
            v = int(da.get("bear_min_pillars", 2))
        tag = _market_state_log_label_regime(regime)
    v = max(1, min(4, v))
    msg = (
        f"[市场状态] {tag}（上证 MA{ma_p}），"
        f"本轮趋势 min_pillars_weak={v}（dynamic_adaptive）"
    )
    return v, msg


def _market_mood_tier_for_position_suggestion(cfg: dict[str, Any]) -> str:
    """与 dynamic_adaptive 一致的大盘三档/牛熊标签，供持仓仓位建议。"""
    tc = cfg.get("trend_slippage_alert") or {}
    da = tc.get("dynamic_adaptive")
    if not isinstance(da, dict) or not bool(da.get("enabled", False)):
        return "range"
    from macro_risk import get_market_mood_three_tier, get_market_regime

    ma_p = max(5, min(120, int(da.get("ma_period", 20) or 20)))
    if bool(da.get("use_mood_three_tier", False)):
        return get_market_mood_three_tier(dynamic_cfg=da)
    regime = get_market_regime(ma_period=ma_p, dynamic_cfg=da)
    return "weak_bear" if regime == "bear" else "range"


def _fill_position_suggestion_metrics(pack: dict[str, Any], now_price: float) -> None:
    """写入 box/均线/量比等字段，供 _get_position_suggestion 使用。"""
    pack.pop("_ps_box_pct", None)
    pack.pop("_ps_above_ma5", None)
    pack.pop("_ps_above_ma20", None)
    pack.pop("_ps_above_ma60", None)
    pack.pop("_ps_vol_ratio", None)
    pack.pop("_ps_ma5", None)
    pack.pop("_ps_ma20", None)
    pack.pop("_ps_ma60", None)
    kl = pack.get("kline")
    if not isinstance(kl, dict) or now_price <= 0:
        return
    try:
        ma5 = float(kl.get("ma5") or 0.0)
        ma20 = float(kl.get("ma20") or 0.0)
        low20 = float(kl.get("low20") or 0.0)
        high20 = float(kl.get("high20") or 0.0)
    except (TypeError, ValueError):
        return
    if ma5 > 0:
        pack["_ps_ma5"] = ma5
        pack["_ps_above_ma5"] = now_price > ma5
    if ma20 > 0:
        pack["_ps_ma20"] = ma20
        pack["_ps_above_ma20"] = now_price > ma20
    ma60v = kl.get("ma60")
    if ma60v is not None:
        try:
            m60 = float(ma60v)
        except (TypeError, ValueError):
            m60 = 0.0
        if m60 > 0:
            pack["_ps_ma60"] = m60
            pack["_ps_above_ma60"] = now_price > m60
    span = max(high20 - low20, 1e-6)
    if high20 > 0 and low20 >= 0:
        pack["_ps_box_pct"] = (now_price - low20) / span
    vols = kl.get("volumes")
    if isinstance(vols, list) and len(vols) >= 21:
        try:
            v_last = float(vols[-1])
            tail = [float(x) for x in vols[-21:-1]]
            v_ma = sum(tail) / 20.0
            if v_ma > 0:
                pack["_ps_vol_ratio"] = v_last / v_ma
        except (TypeError, ValueError):
            pass


def _strategy_buy_realtime_blocked(pack: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    """买入信号实时过滤：量比、大盘 weak_bear、可选日内位置、可选板块交叉。返回原因文案；未拦截返回 None。"""
    from sector_cross_check import sector_buy_cross_block_reason

    sbf = cfg.get("_runtime_effective_strategy_buy_filter")
    if not isinstance(sbf, dict):
        sbf = cfg.get("strategy_buy_filter") or {}
    if not bool(sbf.get("enabled", True)):
        return None
    reasons: list[str] = []
    min_vr = float(sbf.get("min_volume_ratio", 1.2) or 1.2)
    if min_vr > 0:
        vr = pack.get("_ps_vol_ratio")
        if vr is None or float(vr) < min_vr:
            v_show = f"{float(vr):.2f}" if vr is not None else "—"
            reasons.append(f"量比{v_show}（需≥{min_vr:g}）")
    if bool(sbf.get("block_weak_bear", True)):
        mt = pack.get("_strategy_buy_mood_tier")
        if mt == "weak_bear":
            reasons.append("大盘 weak_bear")
    if bool(sbf.get("use_intraday_position_filter", False)):
        qd = pack.get("q")
        if isinstance(qd, dict):
            ip_raw = qd.get("intraday_position")
            if ip_raw is not None:
                try:
                    ipv = float(ip_raw)
                except (TypeError, ValueError):
                    ipv = None
                if ipv is not None:
                    mn = float(sbf.get("min_intraday_position", 0.3) or 0.0)
                    mx = float(sbf.get("max_intraday_position", 0.85) or 1.0)
                    if mn > 0.0 and ipv + 1e-9 < mn:
                        reasons.append(
                            f"日内位置{ipv:.2f}（需≥{mn:g}，避免贴近当日最低区）"
                        )
                    if mx < 1.0 and ipv > mx + 1e-9:
                        reasons.append(
                            f"日内位置{ipv:.2f}（需≤{mx:g}，避免追日内高点）"
                        )
    scc = sbf.get("sector_buy_cross_check")
    scc_r = sector_buy_cross_block_reason(
        pack, scc if isinstance(scc, dict) else None
    )
    if scc_r:
        reasons.append(scc_r)
    return "；".join(reasons) if reasons else None


def _ml_bearish_prob_for_position_suggestion(
    cfg: dict[str, Any],
    *,
    now_price: float,
    pnl_pct: float,
    code6: str,
    anchor_trade_date: str,
) -> float | None:
    """NB 模型下跌概率；未启用或失败返回 None。"""
    mfc = cfg.get("ml_filter") or {}
    if not bool(mfc.get("enabled", False)):
        return None
    mp = resolve_ml_model_path(cfg, ROOT)
    model = load_ml_model_cached(mp)
    if not isinstance(model, dict):
        return None
    td = str(anchor_trade_date or "")[:10]
    feats = build_ml_feature_vector(
        alert_type="trend_slip",
        anchor_price=now_price,
        pnl_pct=pnl_pct,
        weak_pillars=None,
        dd_level=None,
        cfg=cfg,
        root=ROOT,
        code6=code6.strip() if code6 else None,
        anchor_trade_date=td if td else None,
    )
    try:
        return predict_ml_bearish_probability(model, feats)
    except Exception:
        return None


def _get_position_suggestion(
    pack: dict[str, Any],
    cfg: dict[str, Any],
    *,
    pnl_pct: float,
    bearish_prob: float | None,
) -> tuple[str, str]:
    """
    返回 (卖出|补仓|持有, 理由文案)。
    pnl_pct 为相对成本的盈亏百分数（与 risk.calc_profit_pct 一致）。
    """
    ps = cfg.get("position_suggestion") or {}
    if not bool(ps.get("enabled", True)):
        return "持有", ""
    rules = ps.get("rules") or {}
    sell_r = rules.get("sell") or {}
    add_r = rules.get("add") or {}

    def _f(key: str, default: float) -> float:
        try:
            return float(sell_r.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _fa(key: str, default: float) -> float:
        try:
            return float(add_r.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    p_frac = pnl_pct / 100.0
    tier = str(pack.get("_market_mood_tier") or "range")
    box_pct = pack.get("_ps_box_pct")
    vol_ratio = pack.get("_ps_vol_ratio")
    a5 = pack.get("_ps_above_ma5")
    a20 = pack.get("_ps_above_ma20")
    a60 = pack.get("_ps_above_ma60")

    pt = _f("profit_to_take", 0.15)
    if bool(sell_r.get("profit_break_ma5", True)) and p_frac >= pt:
        if a5 is False:
            return "卖出", f"浮盈{pnl_pct:.1f}%已破5日线，止盈"

    ls = _f("loss_stop", -0.08)
    if bool(sell_r.get("loss_below_ma20_and_ma60", True)) and p_frac <= ls:
        if a20 is False and a60 is False:
            return "卖出", "趋势走坏，止损"

    bp_th = _f("bearish_prob_threshold", 0.7)
    if bearish_prob is not None and float(bearish_prob) >= bp_th:
        return "卖出", f"下跌概率{bearish_prob * 100:.1f}%，规避风险"

    bh = _f("box_high_threshold", 0.85)
    vr_lo = _f("volume_ratio_low", 0.8)
    if (
        isinstance(box_pct, (int, float))
        and vol_ratio is not None
        and isinstance(vol_ratio, (int, float))
    ):
        if float(box_pct) >= bh and float(vol_ratio) < vr_lo:
            return "卖出", "高位缩量，动能不足"

    if bool(sell_r.get("market_weak_bear_sell", True)):
        if tier == "weak_bear" and a20 is False:
            return "卖出", "大盘走弱+个股破均线"

    lmin = _fa("loss_min", -0.20)
    lmax = _fa("loss_max", -0.05)
    in_loss_band = (pnl_pct >= lmin * 100.0) and (pnl_pct <= lmax * 100.0)
    if in_loss_band:
        ok_add = True
        if bool(add_r.get("require_above_ma20", True)) and a20 is not True:
            ok_add = False
        bl = _fa("box_low_threshold", 0.4)
        if not isinstance(box_pct, (int, float)) or float(box_pct) > bl:
            ok_add = False
        mvr = _fa("min_volume_ratio", 0.8)
        if vol_ratio is None or float(vol_ratio) < mvr:
            ok_add = False
        if bool(add_r.get("forbid_market_weak_bear", True)) and tier == "weak_bear":
            ok_add = False
        if ok_add:
            lt2 = _fa("loss_tier2", -0.15)
            t1_amt = _fa("add_amount_tier1", 6000)
            t2_amt = _fa("add_amount_tier2", 9000)
            amt = t2_amt if pnl_pct <= lt2 * 100.0 else t1_amt
            return "补仓", f"低位缩量企稳条件满足，建议补仓约{amt:.0f}元"

    return "持有", "观望"


def _merge_top_level_ml_alias(cfg: dict[str, Any], ml_filter: dict[str, Any]) -> None:
    """将顶层 `ml` 节映射到 `ml_filter`，便于与方向二文档中的配置示例对齐。"""
    box = cfg.get("ml")
    if not isinstance(box, dict) or not box:
        return

    def _set(dst: str, val: Any) -> None:
        if val is None:
            return
        ml_filter[dst] = val

    if "kline_model_enabled" in box:
        _set("kline_rf_enabled", bool(box.get("kline_model_enabled")))
    if "kline_model_path" in box:
        _set("kline_rf_model_path", str(box.get("kline_model_path") or "").strip())
    if "kline_db_path" in box:
        _set("kline_rf_db_path", str(box.get("kline_db_path") or "").strip())
    if "kline_table" in box:
        _set("kline_rf_table", str(box.get("kline_table") or "").strip())
    if "kline_suppress_threshold" in box:
        try:
            _set("kline_rf_suppress_below", float(box.get("kline_suppress_threshold")))
        except (TypeError, ValueError):
            pass
    if "suppress_combo" in box:
        _set("suppress_combo", str(box.get("suppress_combo") or "any").strip().lower())
    if "nb_enabled" in box:
        _set("enabled", bool(box.get("nb_enabled")))
    if "nb_model_path" in box:
        _set("model_path", str(box.get("nb_model_path") or "").strip())
    if "nb_prob_threshold" in box:
        try:
            _set("bearish_prob_threshold", float(box.get("nb_prob_threshold")))
        except (TypeError, ValueError):
            pass


def merge_full_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(raw)
    cfg.setdefault("poll_interval_seconds", DEFAULT_POLL)
    cfg.setdefault("trading_closed_interval", DEFAULT_CLOSED_INTERVAL)
    cfg.setdefault("alert_cooldown_minutes", DEFAULT_COOLDOWN_MIN)
    cfg.setdefault("alert_price_buffer", DEFAULT_BUFFER)
    cap = dict(DEFAULT_CAPITAL)
    cap.update(cfg.get("capital") or {})
    cfg["capital"] = cap
    br = dict(DEFAULT_BUY_RULE)
    br.update(cfg.get("buy_rule") or {})
    cfg["buy_rule"] = br
    rr = dict(DEFAULT_RISK_RULE)
    rr.update(cfg.get("risk_rule") or {})
    cfg["risk_rule"] = rr
    dda = dict(DEFAULT_DRAWDOWN_ALERT)
    dda.update(cfg.get("drawdown_alert") or {})
    cfg["drawdown_alert"] = dda
    cfg["trend_slippage_alert"] = _merge_trend_slippage_alert(
        cfg.get("trend_slippage_alert")
    )
    if not isinstance(cfg.get("sector_index_overrides"), dict):
        cfg["sector_index_overrides"] = {}
    sem = dict(DEFAULT_SECTOR_EM)
    sem.update(cfg.get("sector_em") or {})
    cfg["sector_em"] = sem
    sr = dict(DEFAULT_SCAN_RULE)
    sr.update(cfg.get("scan_rule") or {})
    cfg["scan_rule"] = sr
    cfg.setdefault("run_only_in_trading_hours", True)
    cfg.setdefault("scan_pool_max", 4000)
    cfg.setdefault("daily_pick_count", 6)
    cfg.setdefault("macro_risk", {})
    cfg.setdefault("sources", {})
    if not isinstance(cfg["sources"], dict):
        cfg["sources"] = {}
    cfg["sources"].setdefault("ssl_verify", False)
    cfg.setdefault("scan_meta", {})
    perf = dict(DEFAULT_PERFORMANCE)
    perf.update(cfg.get("performance") or {})
    _am0 = dict(DEFAULT_PERFORMANCE.get("async_minute_kline") or {})
    _am_in = perf.get("async_minute_kline")
    if isinstance(_am_in, dict):
        _am0.update(_am_in)
    perf["async_minute_kline"] = _am0
    cfg["performance"] = perf
    if not isinstance(cfg.get("kline_store"), dict):
        cfg["kline_store"] = {}
    ks_m = dict(DEFAULT_KLINE_STORE)
    ks_m.update(cfg["kline_store"])
    cfg["kline_store"] = ks_m
    if not isinstance(cfg.get("realtime_hub"), dict):
        cfg["realtime_hub"] = {}
    rh_m = dict(DEFAULT_REALTIME_HUB)
    rh_m.update(cfg["realtime_hub"])
    cfg["realtime_hub"] = rh_m
    cfg.setdefault("data_health", {})
    if not isinstance(cfg["data_health"], dict):
        cfg["data_health"] = {}
    dh_m = dict(DEFAULT_DATA_HEALTH)
    dh_m.update(cfg["data_health"])
    cfg["data_health"] = dh_m
    cfg.setdefault("logging", {})
    if not isinstance(cfg["logging"], dict):
        cfg["logging"] = {}
    lg_m = dict(DEFAULT_LOGGING)
    lg_m.update(cfg["logging"])
    cfg["logging"] = lg_m
    cfg.setdefault("notifications", {})
    if not isinstance(cfg.get("notifications"), dict):
        cfg["notifications"] = {}
    nt_m = dict(DEFAULT_NOTIFICATIONS)
    nt_m.update(cfg["notifications"])
    _wc_def = dict(DEFAULT_NOTIFICATIONS.get("wecom_webhook") or {})
    _wc_u = nt_m.get("wecom_webhook")
    if isinstance(_wc_u, dict):
        _wc_def.update(_wc_u)
    nt_m["wecom_webhook"] = _wc_def
    cfg["notifications"] = nt_m
    cfg.setdefault("alert_log", {})
    if not isinstance(cfg["alert_log"], dict):
        cfg["alert_log"] = {}
    al_m = dict(DEFAULT_ALERT_LOG)
    al_m.update(cfg["alert_log"])
    _pse = dict(POSITION_SUGGESTION_EVAL_DEFAULT)
    _pse_in = al_m.get("position_suggestion_eval")
    if isinstance(_pse_in, dict):
        for _k, _v in _pse_in.items():
            try:
                _pse[str(_k)] = float(_v)
            except (TypeError, ValueError):
                pass
    al_m["position_suggestion_eval"] = _pse
    _she = dict(STRATEGY_HIT_EVAL_DEFAULT)
    _she_in = al_m.get("strategy_hit_eval")
    if isinstance(_she_in, dict):
        for _k, _v in _she_in.items():
            try:
                _she[str(_k)] = float(_v)
            except (TypeError, ValueError):
                pass
    al_m["strategy_hit_eval"] = _she
    _rte = dict(RISK_STOP_TAKE_EVAL_DEFAULT)
    _rte_in = al_m.get("risk_stop_take_eval")
    if isinstance(_rte_in, dict):
        for _k, _v in _rte_in.items():
            try:
                _rte[str(_k)] = float(_v)
            except (TypeError, ValueError):
                pass
    al_m["risk_stop_take_eval"] = _rte
    cfg["alert_log"] = al_m
    cfg.setdefault("ml_filter", {})
    if not isinstance(cfg["ml_filter"], dict):
        cfg["ml_filter"] = {}
    mf_m = dict(DEFAULT_ML_FILTER)
    mf_m.update(cfg["ml_filter"])
    _merge_top_level_ml_alias(cfg, mf_m)
    cfg["ml_filter"] = mf_m
    cfg.setdefault("ops_automation", {})
    if not isinstance(cfg["ops_automation"], dict):
        cfg["ops_automation"] = {}
    oa_m = dict(DEFAULT_OPS_AUTOMATION)
    oa_m.update(cfg["ops_automation"])
    cfg["ops_automation"] = oa_m
    cfg.setdefault("email_command_bot", {})
    if not isinstance(cfg["email_command_bot"], dict):
        cfg["email_command_bot"] = {}
    ecb_m = dict(DEFAULT_EMAIL_COMMAND_BOT)
    ecb_m.update(cfg["email_command_bot"])
    cfg["email_command_bot"] = ecb_m
    cfg.setdefault("monitoring", {})
    if not isinstance(cfg["monitoring"], dict):
        cfg["monitoring"] = {}
    mon_m = dict(DEFAULT_MONITORING)
    mon_m.update(cfg["monitoring"])
    cfg["monitoring"] = mon_m
    ps0 = copy.deepcopy(DEFAULT_POSITION_SUGGESTION)
    ps_raw = cfg.get("position_suggestion")
    if isinstance(ps_raw, dict):
        ps0["enabled"] = bool(ps_raw.get("enabled", ps0["enabled"]))
        rs_u = ps_raw.get("rules")
        if isinstance(rs_u, dict):
            for branch in ("sell", "add"):
                if isinstance(rs_u.get(branch), dict):
                    ps0["rules"][branch].update(rs_u[branch])
    cfg["position_suggestion"] = ps0
    cfg.setdefault("quant_selector", {})
    if not isinstance(cfg["quant_selector"], dict):
        cfg["quant_selector"] = {}
    qs_m = dict(DEFAULT_QUANT_SELECTOR)
    qs_m.update(cfg["quant_selector"])
    cfg["quant_selector"] = qs_m

    cfg.setdefault("strategy_signal", {})
    if not isinstance(cfg["strategy_signal"], dict):
        cfg["strategy_signal"] = {}
    ss_m = copy.deepcopy(DEFAULT_STRATEGY_SIGNAL)
    ss_raw = cfg.get("strategy_signal") or {}
    for k, v in ss_raw.items():
        if k == "min_score_by_strategy" and isinstance(v, dict):
            base_ms = dict(ss_m.get("min_score_by_strategy") or {})
            for sk, sv in v.items():
                try:
                    base_ms[str(sk)] = float(sv)
                except (TypeError, ValueError):
                    pass
            ss_m["min_score_by_strategy"] = base_ms
        elif k != "min_score_by_strategy":
            ss_m[k] = v
    cfg["strategy_signal"] = ss_m

    cfg.setdefault("strategy_buy_filter", {})
    if not isinstance(cfg["strategy_buy_filter"], dict):
        cfg["strategy_buy_filter"] = {}
    sbf_m = dict(DEFAULT_STRATEGY_BUY_FILTER)
    sbf_m.update(cfg["strategy_buy_filter"])
    _scc = dict(DEFAULT_SECTOR_BUY_CROSS_CHECK)
    _scc_in = sbf_m.get("sector_buy_cross_check")
    _w0 = dict(DEFAULT_SECTOR_BUY_CROSS_CHECK.get("weights") or {})
    if isinstance(_scc_in, dict):
        for _k, _v in _scc_in.items():
            if _k == "weights":
                continue
            _scc[_k] = _v
        _w_in = _scc_in.get("weights")
        if isinstance(_w_in, dict):
            for _wk, _wv in _w_in.items():
                try:
                    _w0[str(_wk)] = float(_wv)
                except (TypeError, ValueError):
                    pass
    _scc["weights"] = _w0
    sbf_m["sector_buy_cross_check"] = _scc
    _ab_m = dict(DEFAULT_ADAPTIVE_BY_MOOD)
    _ab_in = sbf_m.get("adaptive_by_mood")
    if isinstance(_ab_in, dict):
        if "enabled" in _ab_in:
            _ab_m["enabled"] = bool(_ab_in["enabled"])
        for _tier in ("strong_bull", "range", "weak_bear"):
            _t_in = _ab_in.get(_tier)
            if isinstance(_t_in, dict):
                _cur = dict(_ab_m.get(_tier) or {})
                _cur.update(_t_in)
                _ab_m[_tier] = _cur
    sbf_m["adaptive_by_mood"] = _ab_m
    cfg["strategy_buy_filter"] = sbf_m

    from config_validate import validate_merged_config_or_exit

    validate_merged_config_or_exit(cfg)
    from data_health import configure_data_health

    configure_data_health(cfg)
    return cfg


def apply_poll_outage_state_mutations(
    state: dict[str, Any],
    *,
    full_outage: bool,
    dh_cfg: dict[str, Any],
) -> int | None:
    """
    全失败：累加 __full_outage_streak__，并按配置写入 __trend_suppress_rounds__。
    非全失败：streak 清零、清除 __full_outage_escalated_sent__、suppress 计数减一。
    返回非全失败时「清零前」的 streak，供恢复通知判断；全失败时返回 None。
    """
    if full_outage:
        streak = int(state.get("__full_outage_streak__") or 0) + 1
        state["__full_outage_streak__"] = streak
        sup_n = int(dh_cfg.get("suppress_trend_rounds_after_full_outage") or 0)
        if sup_n > 0:
            state["__trend_suppress_rounds__"] = sup_n
        return None
    old_streak = int(state.get("__full_outage_streak__") or 0)
    state["__full_outage_streak__"] = 0
    state.pop("__full_outage_escalated_sent__", None)
    tr_left = int(state.get("__trend_suppress_rounds__") or 0)
    if tr_left > 0:
        state["__trend_suppress_rounds__"] = tr_left - 1
    return old_streak


def rule_key(rule: dict[str, Any]) -> str:
    return f'{rule.get("code")}:{str(rule.get("market") or "sh").lower()}'


def should_alert(price: float, rule: dict[str, Any], buffer: float) -> tuple[bool, str]:
    mode = (rule.get("alert_mode") or "breach").lower()
    low, high = rule.get("alert_below"), rule.get("alert_above")
    if mode == "band":
        if low is None or high is None:
            return False, ""
        lo, hi = float(low), float(high)
        if lo > hi:
            lo, hi = hi, lo
        if (lo - buffer) <= price <= (hi + buffer):
            return True, f"在区间 [{lo}, {hi}] 内（含防抖）"
        return False, ""
    parts: list[str] = []
    if low is not None and price <= float(low) + buffer:
        parts.append(f"跌破或触及下限 {low}")
    if high is not None and price >= float(high) - buffer:
        parts.append(f"涨破或触及上限 {high}")
    if not parts:
        return False, ""
    return True, "；".join(parts)


def state_path(cfg_path: Path) -> Path:
    return cfg_path.parent / ".alert_state.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def hydrate_runtime_watch_sets(
    force_include_codes: set[str],
    force_exclude_codes: set[str],
    state: dict[str, Any],
) -> None:
    """从 .alert_state.json 恢复 hold/sell，避免重启后丢失。"""
    fi = state.get("__force_include__")
    if isinstance(fi, list):
        for x in fi:
            c = normalize_stock_code(str(x))
            if c:
                force_include_codes.add(c)
    fe = state.get("__force_exclude__")
    if isinstance(fe, list):
        for x in fe:
            c = normalize_stock_code(str(x))
            if c:
                force_exclude_codes.add(c)


def save_state(path: Path, state: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def valid_code(code: str) -> bool:
    c = code.strip()
    return len(c) == 6 and c.isdigit()


def normalize_stock_code(raw: str) -> str | None:
    """六位股票代码；纯数字且不足六位时左侧补零（如 537 → 000537）。"""
    s = str(raw).strip()
    if not s.isdigit():
        return None
    if len(s) > 6:
        return None
    c = s.zfill(6)
    return c if valid_code(c) else None


def _infer_market(code: str) -> str:
    c = str(code).strip()
    return "sh" if c.startswith("6") else "sz"


def _load_quality_codes(picks_path: Path) -> set[str]:
    if not picks_path.exists():
        return set()
    try:
        j = json.loads(picks_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    rows = (
        j.get("优质股")
        or j.get("优质标的")
        or j.get("stocks")
        or []
    )
    out: set[str] = set()
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        nc = normalize_stock_code(str(row.get("code") or "").strip())
        if nc:
            out.add(nc)
    return out


def _should_run_startup_daily_select(cfg: dict[str, Any], args: Any) -> bool:
    """是否在进入监控前执行「启动时」盘前选股（与轮内 ops_automation 独立）。"""
    if bool(getattr(args, "skip_daily_select", False)):
        return False
    mon = cfg.get("monitoring") or {}
    if bool(mon.get("watchlist_only", False)):
        return False
    if bool(mon.get("skip_startup_daily_select", False)):
        return False
    return True


def _build_watch_from_daily_picks(cfg: dict[str, Any], cfg_path: Path) -> tuple[list[dict[str, Any]], str]:
    return _build_watch_from_daily_picks_with_overrides(
        cfg,
        cfg_path,
        force_include_codes=set(),
        force_exclude_codes=set(),
    )


def _apply_runtime_watch_overrides(
    base_watch: list[dict[str, Any]],
    *,
    force_include_codes: set[str],
    force_exclude_codes: set[str],
) -> list[dict[str, Any]]:
    """无 daily_picks 时：在 watchlist 上应用 hold（补票）/ sell（剔除）。"""
    by_c: dict[str, dict[str, Any]] = {}
    for w in base_watch:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if nc:
            by_c[nc] = w
    out: list[dict[str, Any]] = []
    for w in base_watch:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if not nc:
            continue
        if nc in force_exclude_codes and nc not in force_include_codes:
            continue
        ent = dict(w)
        ent["code"] = nc
        out.append(ent)
    for c in sorted(force_include_codes):
        if c in force_exclude_codes or not valid_code(c):
            continue
        if any(
            normalize_stock_code(str(x.get("code") or "").strip()) == c for x in out
        ):
            continue
        src = by_c.get(c)
        if src is not None:
            ent = dict(src)
            if not has_position_tag(ent):
                prev = str(ent.get("tags") or "").strip()
                ent["tags"] = f"{prev} 持仓".strip() if prev else "持仓"
        else:
            ent = {
                "enabled": True,
                "cost_price": 0.0,
                "hold_shares": 0,
                "alert_mode": "breach",
                "alert_below": None,
                "alert_above": None,
                "note": "hold 命令加入",
                "tags": "持仓",
                "industry": "",
                "name": c,
                "code": c,
                "market": _infer_market(c),
            }
        out.append(ent)
    return _shuffle_watch_if_multi(_dedupe_watch_rules_list(out))


def _build_watch_from_daily_picks_with_overrides(
    cfg: dict[str, Any],
    cfg_path: Path,
    *,
    force_include_codes: set[str],
    force_exclude_codes: set[str],
) -> tuple[list[dict[str, Any]], str]:
    base_watch = [w for w in cfg.get("watchlist", []) if isinstance(w, dict) and w.get("enabled", True)]
    if not base_watch:
        return [], "watchlist_empty"
    mon = cfg.get("monitoring") or {}
    if bool(mon.get("watchlist_only", False)):
        return (
            _apply_runtime_watch_overrides(
                base_watch,
                force_include_codes=force_include_codes,
                force_exclude_codes=force_exclude_codes,
            ),
            "watchlist_only",
        )
    picks_path = cfg_path.parent / "daily_picks.json"
    qcodes = _load_quality_codes(picks_path)
    if not qcodes:
        return (
            _apply_runtime_watch_overrides(
                base_watch,
                force_include_codes=force_include_codes,
                force_exclude_codes=force_exclude_codes,
            ),
            "fallback_all",
        )

    by_code: dict[str, dict[str, Any]] = {}
    for w in base_watch:
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if not nc:
            continue
        ent_w = dict(w)
        ent_w["code"] = nc
        by_code[nc] = ent_w
    out: list[dict[str, Any]] = []
    # 只监控优质股
    for c in sorted(qcodes):
        if c in force_exclude_codes and c not in force_include_codes:
            continue
        ent = by_code.get(c)
        if ent is None:
            ent = {
                "enabled": True,
                "cost_price": 0.0,
                "hold_shares": 0,
                "alert_mode": "breach",
                "alert_below": None,
                "alert_above": None,
                "note": "daily_picks 优质股",
                "tags": "",
                "industry": "",
                "name": c,
                "code": c,
                "market": _infer_market(c),
            }
        out.append(dict(ent))

    # 强制加入 hold 的标的（即使不在优质池）
    for c in sorted(force_include_codes):
        if c in force_exclude_codes:
            continue
        if not valid_code(c):
            continue
        if any(
            normalize_stock_code(str(x.get("code") or "").strip()) == c for x in out
        ):
            continue
        ent = by_code.get(c)
        if ent is None:
            ent = {
                "enabled": True,
                "cost_price": 0.0,
                "hold_shares": 0,
                "alert_mode": "breach",
                "alert_below": None,
                "alert_above": None,
                "note": "hold 命令加入",
                "tags": "持仓",
                "industry": "",
                "name": c,
                "code": c,
                "market": _infer_market(c),
            }
        out.append(ent)

    # 持仓标签标的永远保留（避免漏看真实持仓）
    for w in base_watch:
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if not nc:
            continue
        if nc in force_exclude_codes and nc not in force_include_codes:
            continue
        if has_position_tag(w) and nc not in qcodes:
            ent = dict(w)
            ent["code"] = nc
            out.append(ent)
    return _shuffle_watch_if_multi(_dedupe_watch_rules_list(out)), "quality_only"


def save_config_atomic(path: Path, cfg: dict[str, Any]) -> bool:
    """原子写入 config.json，避免半截文件。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _watchlist_indices_for_code(
    wl: list[Any], code: str
) -> list[int]:
    c6 = normalize_stock_code(code)
    if not c6:
        return []
    out: list[int] = []
    for i, w in enumerate(wl):
        if not isinstance(w, dict):
            continue
        wc = normalize_stock_code(str(w.get("code") or ""))
        if wc == c6:
            out.append(i)
    return out


def _merge_duplicate_watch_rows(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """两条记录视为同一标的时合并为一条（去重 / 扫描合并）。"""
    sa, sb = int(a.get("hold_shares") or 0), int(b.get("hold_shares") or 0)
    ca, cb = float(a.get("cost_price") or 0.0), float(b.get("cost_price") or 0.0)
    if sa > sb or (sa == sb and ca >= cb):
        primary, secondary = a, b
    else:
        primary, secondary = b, a
    out = dict(primary)
    out["hold_shares"] = max(sa, sb)
    if sb > sa:
        out["cost_price"] = cb
    elif sa > sb:
        out["cost_price"] = ca
    else:
        out["cost_price"] = cb if cb > 0 else ca
    for fld in ("name", "industry", "market", "note", "alert_mode"):
        if not str(out.get(fld) or "").strip():
            v = secondary.get(fld)
            if v is not None:
                out[fld] = v
    if out.get("alert_below") is None and secondary.get("alert_below") is not None:
        out["alert_below"] = secondary["alert_below"]
    if out.get("alert_above") is None and secondary.get("alert_above") is not None:
        out["alert_above"] = secondary["alert_above"]
    parts: list[str] = []
    for t in (normalize_tags_field(primary), normalize_tags_field(secondary)):
        t = str(t).strip()
        if t and t not in parts:
            parts.append(t)
    tag_line = " ".join(parts)
    out["tags"] = tag_line
    if (has_position_tag(primary) or has_position_tag(secondary)) and not has_position_tag(
        out
    ):
        out["tags"] = f"{tag_line} 持仓".strip() if tag_line else "持仓"
    out["enabled"] = bool(primary.get("enabled", True)) or bool(
        secondary.get("enabled", True)
    )
    return out


def dedupe_watchlist_in_cfg(cfg: dict[str, Any]) -> int:
    """按六位代码合并 watchlist 重复项，并统一 code 为补零形式；返回被合并掉的条数。"""
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        return 0
    new_list: list[Any] = []
    removed = 0
    seen: dict[str, dict[str, Any]] = {}
    for w in wl:
        if not isinstance(w, dict):
            new_list.append(w)
            continue
        key = normalize_stock_code(str(w.get("code") or "").strip())
        if not key:
            new_list.append(w)
            continue
        if key not in seen:
            ent = dict(w)
            ent["code"] = key
            seen[key] = ent
            new_list.append(ent)
        else:
            merged = _merge_duplicate_watch_rows(seen[key], dict(w))
            merged["code"] = key
            seen[key].clear()
            seen[key].update(merged)
            removed += 1
    cfg["watchlist"] = new_list
    return removed


def _dedupe_watch_rules_list(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """监控规则列表按六位代码去重（保留首次出现顺序，合并同代码多条）。"""
    tail: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for w in rules:
        if not isinstance(w, dict):
            continue
        nc = normalize_stock_code(str(w.get("code") or "").strip())
        if not nc:
            tail.append(dict(w))
            continue
        if nc not in seen:
            ent = dict(w)
            ent["code"] = nc
            seen[nc] = ent
            order.append(nc)
        else:
            merged = _merge_duplicate_watch_rows(seen[nc], dict(w))
            merged["code"] = nc
            seen[nc].clear()
            seen[nc].update(merged)
    return [seen[k] for k in order] + tail


def _shuffle_watch_if_multi(watch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并去重后打乱顺序，避免控制台长期按代码字典序刷屏（主循环每轮重建列表时会再次打乱）。"""
    if len(watch) > 1:
        random.shuffle(watch)
    return watch


def _upsert_hold_in_cfg(
    cfg: dict[str, Any],
    *,
    code: str,
    hold_shares: int,
    cost_price: float,
    config_path: Path,
) -> bool:
    """
    写入/更新持仓：同代码已存在则用本次命令的股数、成本覆盖原记录，并去掉重复条目；
    否则追加新记录。字段与全站一致：hold_shares、cost_price；tags 为字符串。
    """
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        cfg["watchlist"] = []
        wl = cfg["watchlist"]
    name = get_stock_name(code)
    market = _infer_market(code)
    indices = _watchlist_indices_for_code(wl, code)
    delta_sh = int(hold_shares)
    delta_cost = float(cost_price)

    if indices:
        i0 = indices[0]
        raw_old = wl[i0]
        old = raw_old if isinstance(raw_old, dict) else {}
        merged = dict(old)
        merged["enabled"] = True
        merged["code"] = code
        merged["name"] = str(old.get("name") or name)
        merged["market"] = str(old.get("market") or market) or market
        merged["hold_shares"] = delta_sh
        merged["cost_price"] = delta_cost
        merged["alert_mode"] = str(old.get("alert_mode") or "breach")
        merged["alert_below"] = old.get("alert_below")
        merged["alert_above"] = old.get("alert_above")
        merged["note"] = str(old.get("note") or "终端 hold")
        merged["industry"] = str(old.get("industry") or "")
        prev_tags = normalize_tags_field(old)
        if not has_position_tag(old):
            merged["tags"] = f"{prev_tags} 持仓".strip() if prev_tags else "持仓"
        else:
            merged["tags"] = prev_tags if prev_tags else "持仓"
        wl[i0] = merged
        for j in reversed(indices[1:]):
            wl.pop(j)
    else:
        patch = {
            "enabled": True,
            "code": code,
            "name": name,
            "market": market,
            "hold_shares": delta_sh,
            "cost_price": delta_cost,
            "tags": "持仓",
            "alert_mode": "breach",
            "alert_below": None,
            "alert_above": None,
            "note": "终端 hold",
            "industry": "",
        }
        wl.append(patch)
    return save_config_atomic(config_path, cfg)


def _remove_hold_from_cfg(
    cfg: dict[str, Any], *, code: str, config_path: Path
) -> int:
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        return 0
    c6 = normalize_stock_code(code)
    if not c6:
        return 0
    removed = 0
    for i in range(len(wl) - 1, -1, -1):
        w = wl[i]
        if not isinstance(w, dict):
            continue
        if normalize_stock_code(str(w.get("code") or "")) == c6:
            wl.pop(i)
            removed += 1
    if removed:
        save_config_atomic(config_path, cfg)
    return removed


def _print_showhold(cfg: dict[str, Any]) -> None:
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        _emit_cli_subcmd_line(
            "[showhold] watchlist 为空或格式异常",
            event="cli_showhold_bad_watchlist",
        )
        return
    rows: list[tuple[str, str, int, float, str]] = []
    for w in wl:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        hs = int(w.get("hold_shares") or 0)
        cp = float(w.get("cost_price") or 0.0)
        if hs <= 0 and cp <= 0:
            continue
        code = str(w.get("code") or "").strip()
        name = str(w.get("name") or get_stock_name(code))
        note = str(w.get("note") or "")
        rows.append((code, name, hs, cp, note))
    _cli_print_blank()
    _emit_cli_subcmd_line(
        "---------- 当前持仓（config.json watchlist）----------",
        event="cli_showhold_title",
    )
    if not rows:
        _emit_cli_subcmd_line(
            "  （无：股数与成本均为 0 的条目已过滤）",
            event="cli_showhold_empty",
        )
    else:
        _emit_cli_subcmd_line(
            f"  {'代码':<8}  {'简称':<12}  {'股数':>8}  {'成本':>10}  备注",
            event="cli_showhold_table_header",
        )
        _emit_cli_subcmd_line("  " + "-" * 56, event="cli_showhold_table_sep")
        for code, name, hs, cp, note in sorted(rows, key=lambda x: x[0]):
            _emit_cli_subcmd_line(
                f"  {code:<8}  {name[:12]:<12}  {hs:>8}  {cp:>10.4f}  {note}",
                event="cli_showhold_row",
            )
    _emit_cli_subcmd_line(f"  共 {len(rows)} 条", event="cli_showhold_count")
    _emit_cli_subcmd_line(
        "------------------------------------------------------",
        event="cli_showhold_footer",
    )
    _cli_print_blank()


def _start_command_listener(*, read_stdin_commands: bool) -> queue.Queue[str]:
    """stdin 非 TTY 或 --once 时不启线程，避免解释器退出时 daemon+input 锁死（LibreSSL/macOS 等环境）。"""
    q: queue.Queue[str] = queue.Queue()
    if not read_stdin_commands:
        return q

    def _reader() -> None:
        while True:
            try:
                line = input()
            except EOFError:
                break
            except Exception:
                break
            line = str(line).strip()
            if line:
                q.put(line)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    return q


def _apply_take_profit_correctness_patch(
    config_path: Path,
    cfg: dict[str, Any],
    value: int,
) -> bool:
    """写入 config.json 的 alert_log.risk_stop_take_eval，并同步当前内存中的 merged cfg。"""
    if value not in (0, 1):
        return False
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    al = raw.setdefault("alert_log", {})
    if not isinstance(al, dict):
        raw["alert_log"] = {}
        al = raw["alert_log"]
    rte = al.setdefault("risk_stop_take_eval", {})
    if not isinstance(rte, dict):
        al["risk_stop_take_eval"] = {}
        rte = al["risk_stop_take_eval"]
    rte["take_profit_hit_for_correctness"] = float(value)
    if not save_config_atomic(config_path, raw):
        return False
    al_m = cfg.setdefault("alert_log", {})
    if not isinstance(al_m, dict):
        cfg["alert_log"] = {}
        al_m = cfg["alert_log"]
    rte_m = al_m.setdefault("risk_stop_take_eval", {})
    if not isinstance(rte_m, dict):
        al_m["risk_stop_take_eval"] = {}
        rte_m = al_m["risk_stop_take_eval"]
    rte_m["take_profit_hit_for_correctness"] = float(value)
    return True


def _maybe_run_backtest_after_tp_hit_change(
    *, cfg: dict[str, Any], config_path: Path
) -> None:
    ecb = cfg.get("email_command_bot") or {}
    if not isinstance(ecb, dict):
        return
    if not bool(ecb.get("auto_backtest_on_take_profit_hit_change", False)):
        return
    py = sys.executable
    try:
        cp = subprocess.run(
            [
                py,
                str(ROOT / "backtest_alerts.py"),
                "-c",
                str(config_path),
                "--force",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except Exception as exc:
        _emit_main_line(
            f"[配置] 止盈 hit 语义已写入，但自动回测失败：{exc}",
            event="tp_hit_change_backtest_err",
            level=logging.WARNING,
        )
        return
    tail = (cp.stdout or "")[-400:].strip()
    if cp.returncode == 0:
        _emit_main_line(
            "[配置] 已自动执行 backtest_alerts --force"
            + (f"｜{tail}" if tail else ""),
            event="tp_hit_change_backtest_ok",
        )
    else:
        _emit_main_line(
            f"[配置] 自动回测失败 rc={cp.returncode}"
            + (f"｜{tail}" if tail else ""),
            event="tp_hit_change_backtest_fail",
            level=logging.WARNING,
        )


def _handle_runtime_command(
    line: str,
    *,
    cfg: dict[str, Any],
    config_path: Path,
    force_include_codes: set[str],
    force_exclude_codes: set[str],
) -> None:
    """
    在**主循环线程**中执行（与行情轮询同线程，不阻塞 input 线程）。
    修改 cfg 并原子写回 config_path，下一轮 watch 立即生效。
    """
    parts = line.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    if cmd == "showhold" and len(parts) == 1:
        _print_showhold(cfg)
        return

    if cmd == "dedupewatchlist" and len(parts) == 1:
        n = dedupe_watchlist_in_cfg(cfg)
        if not save_config_atomic(config_path, cfg):
            _emit_cli_subcmd_line(
                "[dedupewatchlist] 写入 config 失败（请检查磁盘权限）",
                event="cli_dedupe_watchlist_write_failed",
            )
            return
        _emit_cli_subcmd_line(
            f"[dedupewatchlist] 已按六位代码合并重复项，移除 {n} 条",
            event="cli_dedupe_watchlist_ok",
        )
        return

    if cmd == "unhold" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            _emit_cli_subcmd_line(
                f"[unhold] 代码无效：{parts[1]!r}",
                event="cli_unhold_invalid_code",
            )
            return
        n = _remove_hold_from_cfg(cfg, code=code, config_path=config_path)
        force_include_codes.discard(code)
        force_exclude_codes.discard(code)
        if n:
            _emit_cli_subcmd_line(
                f"[unhold] 已从 config 删除 {code}（{get_stock_name(code)}），共移除 {n} 条",
                event="cli_unhold_ok",
            )
        else:
            _emit_cli_subcmd_line(
                f"[unhold] config 中未找到 {code}",
                event="cli_unhold_not_found",
            )
        return

    if cmd == "hold" and len(parts) == 4:
        code = normalize_stock_code(parts[1])
        if code is None:
            _emit_cli_subcmd_line(
                f"[hold] 代码无效：{parts[1]!r}",
                event="cli_hold_invalid_code",
            )
            return
        try:
            shares = int(parts[2])
            cost = float(parts[3])
        except ValueError:
            _emit_cli_subcmd_line(
                "[hold] 股数须为整数，成本须为数字，例：hold 000537 3000 10.25",
                event="cli_hold_parse_error",
            )
            return
        if shares < 0:
            _emit_cli_subcmd_line("[hold] 股数不能为负", event="cli_hold_shares_negative")
            return
        if cost < 0:
            _emit_cli_subcmd_line("[hold] 成本不能为负", event="cli_hold_cost_negative")
            return
        if not _upsert_hold_in_cfg(
            cfg,
            code=code,
            hold_shares=shares,
            cost_price=cost,
            config_path=config_path,
        ):
            _emit_cli_subcmd_line(
                "[hold] 写入 config 失败（请检查磁盘权限）",
                event="cli_hold_write_failed",
            )
            return
        force_include_codes.add(code)
        force_exclude_codes.discard(code)
        nm = get_stock_name(code)
        tot_sh, tot_cp = shares, cost
        wl_after = cfg.get("watchlist")
        if isinstance(wl_after, list):
            for ix in _watchlist_indices_for_code(wl_after, code)[:1]:
                ent = wl_after[ix]
                if isinstance(ent, dict):
                    tot_sh = int(ent.get("hold_shares") or 0)
                    tot_cp = float(ent.get("cost_price") or 0.0)
                    break
        _emit_cli_subcmd_line(
            f"[hold] 已写入 config：{code}（{nm}） 股数 {tot_sh}  成本 {tot_cp:.4f}",
            event="cli_hold_saved",
        )
        _emit_cli_subcmd_line(
            "       监控池已更新（本轮内下一段 watch 即生效）",
            event="cli_hold_pool_updated",
        )
        return

    if cmd == "hold" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            _emit_cli_subcmd_line(
                f"[hold] 代码无效：{parts[1]!r}",
                event="cli_hold_invalid_code",
            )
            return
        force_include_codes.add(code)
        force_exclude_codes.discard(code)
        _emit_cli_subcmd_line(
            f"[hold] 已加入监控池：{code}（{get_stock_name(code)}）（未改 config 股数/成本）",
            event="cli_hold_watch_only",
        )
        _emit_cli_subcmd_line(
            "       完整持仓请用：hold <代码> <股数> <成本>",
            event="cli_hold_watch_hint",
        )
        return

    if cmd == "sell" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            _emit_cli_subcmd_line(
                f"[sell] 代码无效：{parts[1]!r}",
                event="cli_sell_invalid_code",
            )
            return
        force_include_codes.discard(code)
        force_exclude_codes.add(code)
        _emit_cli_subcmd_line(
            f"[sell] 已暂停监控：{code}（{get_stock_name(code)}）（未删 config 条目）",
            event="cli_sell_ok",
        )
        _emit_cli_subcmd_line(
            "       删除持仓记录请用：unhold <代码>",
            event="cli_sell_unhold_hint",
        )
        return

    if (
        cmd == "set"
        and len(parts) == 3
        and parts[1] == "take_profit_hit_for_correctness"
    ):
        try:
            v = int(parts[2])
        except ValueError:
            _emit_cli_subcmd_line(
                f"[set] 取值须为 0 或 1，收到：{parts[2]!r}",
                event="cli_set_tp_hit_invalid",
            )
            return
        if v not in (0, 1):
            _emit_cli_subcmd_line(
                f"[set] 取值须为 0 或 1，收到：{v}",
                event="cli_set_tp_hit_invalid",
            )
            return
        if _apply_take_profit_correctness_patch(config_path, cfg, v):
            lab = "卖对避险" if v == 1 else "卖飞/旧语义"
            _emit_cli_subcmd_line(
                f"[set] take_profit_hit_for_correctness={v}（{lab}）已写入 {config_path.name}",
                event="cli_set_tp_hit_ok",
            )
            _maybe_run_backtest_after_tp_hit_change(
                cfg=cfg, config_path=config_path
            )
        else:
            _emit_cli_subcmd_line(
                "[set] 写入 config 失败（磁盘权限或 JSON 损坏）",
                event="cli_set_tp_hit_write_failed",
            )
        return

    _emit_cli_subcmd_line("[命令] 用法：", event="cli_usage_header")
    _emit_cli_subcmd_line(
        "  hold <代码> <股数> <成本>   例：hold 000537 3000 10.25  （写入 config；同代码再次 hold 覆盖该股数与成本）",
        event="cli_usage_hold_full",
    )
    _emit_cli_subcmd_line(
        "  hold <代码>                 仅纳入监控池（不写股数成本）",
        event="cli_usage_hold_code",
    )
    _emit_cli_subcmd_line(
        "  unhold <代码>               从 config 删除该标的",
        event="cli_usage_unhold",
    )
    _emit_cli_subcmd_line(
        "  showhold                    打印当前持仓表",
        event="cli_usage_showhold",
    )
    _emit_cli_subcmd_line(
        "  dedupewatchlist             合并 watchlist 中同一代码的重复条目并写回 config",
        event="cli_usage_dedupe_watchlist",
    )
    _emit_cli_subcmd_line(
        "  sell <代码>                 暂停监控（runtime，不删 config）",
        event="cli_usage_sell",
    )
    _emit_cli_subcmd_line(
        "  set take_profit_hit_for_correctness 0|1   止盈回测语义：1=卖对 0=卖飞（写 config；邮件可发同指令）",
        event="cli_usage_set_tp_hit",
    )


def _run_auto_daily_select(args: Any) -> int:
    """执行盘前自动筛选并输出统计；返回 0 成功，1 失败。"""
    from quant_core.selector import run_daily_selector, save_daily_selector_result

    if not args.config.exists():
        _emit_cli_subcmd_line(
            f"缺少配置: {args.config}",
            event="cli_daily_select_no_config",
        )
        return 1
    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    from app_logging import setup_app_logging

    setup_app_logging(cfg, root=ROOT)
    from utils import configure_ssl_from_sources

    configure_ssl_from_sources(cfg.get("sources"))
    out = run_daily_selector(
        cfg,
        limit=int(cfg.get("scan_pool_max", 250)),
        top_n_per_strategy=20,
    )
    out_path = args.config.parent / "daily_picks.json"
    save_daily_selector_result(out, out_path)
    _emit_cli_subcmd_line(
        f"[完成] 每日分策略选股已输出: {out_path}",
        event="cli_daily_select_done",
    )
    _emit_cli_subcmd_line(
        "  - 优质股: "
        f"{len(out.get('优质股') or out.get('优质标的') or [])}",
        event="cli_daily_select_count_quality",
    )
    _emit_cli_subcmd_line(
        "  - 观察股: "
        f"{len(out.get('观察股') or out.get('观察标的') or [])}",
        event="cli_daily_select_count_watch",
    )
    _emit_cli_subcmd_line(
        "  - 淘汰股: "
        f"{len(out.get('淘汰股') or out.get('淘汰标的') or [])}",
        event="cli_daily_select_count_reject",
    )

    # 预热股票名称缓存（与 stock_name_cache.json 同步，监控界面直接显示简称）
    for key in ("优质股", "优质标的", "观察股", "观察标的"):
        for item in out.get(key) or []:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if code is None:
                continue
            c = str(code).strip()
            if valid_code(c):
                get_stock_name(c)

    ks_post = cfg.get("kline_store") or {}
    if (
        isinstance(ks_post, dict)
        and bool(ks_post.get("enabled"))
        and not bool(getattr(args, "no_sync_after_select", False))
    ):
        _emit_cli_subcmd_line(
            "[主流程] 选股完成，自动同步日 K 到本地 SQLite（含新 daily_picks）…",
            event="cli_post_daily_select_sync_klines_start",
        )
        try:
            from sync_daily_klines import run_sync_daily_klines

            sr = run_sync_daily_klines(cfg, config_path=args.config)
            if sr != 0:
                _emit_cli_subcmd_line(
                    "[警告] 选股后日 K 同步返回非 0，监控仍继续（个股 K 可能走网络）",
                    event="cli_post_daily_select_sync_klines_bad_rc",
                )
            else:
                _emit_cli_subcmd_line(
                    "[主流程] 选股后日 K 同步已完成",
                    event="cli_post_daily_select_sync_klines_done",
                )
        except Exception as e:
            _emit_cli_subcmd_line(
                f"[警告] 选股后日 K 同步异常（已忽略，监控仍继续）: {e}",
                event="cli_post_daily_select_sync_klines_exc",
            )
    elif isinstance(ks_post, dict) and bool(ks_post.get("enabled")):
        _emit_cli_subcmd_line(
            "[主流程] 已跳过选股后日 K 同步（--no-sync-after-select）；请单独执行 sync_daily_klines",
            event="cli_post_daily_select_sync_klines_skipped",
        )

    return 0


def _run_check_bk_mapping(args: argparse.Namespace) -> int:
    """仅打印 watchlist 的 BK 解析，供自检 sector_index_overrides / 映射异常。"""
    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    from app_logging import setup_app_logging

    setup_app_logging(cfg, root=ROOT)
    from utils import configure_ssl_from_sources

    configure_ssl_from_sources(cfg.get("sources"))
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        _emit_cli_subcmd_line(
            "[check-bk] watchlist 缺失或非数组",
            event="cli_check_bk_bad_watchlist",
        )
        return 1
    _emit_cli_subcmd_line(
        "---------- BK 映射（趋势三柱用 sector_em；可配 sector_index_overrides）----------",
        event="cli_check_bk_title",
    )
    for w in wl:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        code = normalize_stock_code(str(w.get("code") or ""))
        if not code or not valid_code(code):
            continue
        market = str(w.get("market") or "sh").strip().lower()
        ind = str(w.get("industry") or "").strip()
        bk = resolve_sector_bk(
            code,
            market,
            cfg,
            root=ROOT,
            fallback_industry=ind,
        )
        nm = str(w.get("name") or get_stock_name(code))
        if bk:
            _emit_cli_subcmd_line(
                f"  {code}  {nm[:10]:<10}  -> BK {bk}   industry={ind or '-'}",
                event="cli_check_bk_row",
            )
        else:
            _emit_cli_subcmd_line(
                f"  {code}  {nm[:10]:<10}  -> (无BK，趋势两柱)   industry={ind or '-'}",
                event="cli_check_bk_row_no_bk",
            )
    _emit_cli_subcmd_line(
        "------------------------------------------------------------------------------",
        event="cli_check_bk_footer",
    )
    return 0


def breach_cooldown_ok(
    state: dict[str, Any],
    rk: str,
    cooldown_min: float,
    now: float,
) -> bool:
    entry = state.get(rk)
    if not isinstance(entry, dict):
        return True
    last = entry.get("last_alert_ts") or entry.get("ts")
    if last is None:
        return True
    return (now - float(last)) >= cooldown_min * 60.0


def channel_cooldown_ok(
    state: dict[str, Any],
    key: str,
    cooldown_min: float,
    now: float,
) -> bool:
    last = state.get(key)
    if last is None:
        return True
    return (now - float(last)) >= cooldown_min * 60.0


# ====================== 🔥 只改了这里：A股 红涨绿跌 ======================
def color_line(day_chg: float | None, text: str) -> str:
    if _no_color() or day_chg is None:
        return text
    if day_chg > 0:
        return f"\033[91m{text}\033[0m"   # 涨 → 红
    if day_chg < 0:
        return f"\033[32m{text}\033[0m"   # 跌 → 深绿（非亮绿 92，减少刺眼）
    return f"\033[90m{text}\033[0m"
# ======================================================================


def bold_console(text: str) -> str:
    if _no_color():
        return text
    return f"\033[1m{text}\033[0m"


def bold_strategy_buy_sell(sig: str) -> str:
    """终端：买入信号红粗、卖出信号绿粗（与 A 股涨跌色一致）。"""
    if _no_color():
        return sig
    out = sig
    buy_m, sell_m = "【买入信号】", "【卖出信号】"
    if buy_m in out:
        out = out.replace(buy_m, f"\033[1;91m{buy_m}\033[0m")
    if sell_m in out:
        out = out.replace(sell_m, f"\033[1;32m{sell_m}\033[0m")
    return out


def _is_add_buy_hint_line(ln: str) -> bool:
    return bool(
        (ln.startswith("【") and "补仓】" in ln[:16])
        or "建议补仓金额：" in ln
        or "按现价约合买入：" in ln
    )


def style_add_console_line(ln: str) -> str:
    """终端：补仓档位 / 建议补仓金额 / 约合买入 行用粗体亮洋红，其余维持洋红。"""
    if _no_color():
        return ln
    if _is_add_buy_hint_line(ln):
        return f"\033[1;95m{ln}\033[0m"
    return f"\033[95m{ln}\033[0m"


def _flush_round_notification_merge(
    digest: list[dict[str, Any]],
    *,
    title: str,
    subtitle: str,
    cfg: dict[str, Any],
    args: Any,
    max_items: int,
    severity: str,
) -> None:
    if args.no_notify or not digest:
        return
    n = max(1, int(max_items))
    chunks: list[str] = []
    for it in digest[:n]:
        chunks.append(f"• {it['title']}\n{it['body']}")
    body = "\n\n".join(chunks)
    if len(digest) > n:
        body += f"\n\n… 另有 {len(digest) - n} 条未展示"
    send_notification(
        title,
        body,
        subtitle=subtitle,
        sound=True,
        cfg=cfg,
        severity=severity,
    )


def _fetch_watch_item_pack(
    *,
    rule: dict[str, Any],
    cfg: dict[str, Any],
    ut: str,
    index_mult: float,
    index_5d_ret: float | None,
    force_include_codes: set[str],
    round_bk_kline: dict[str, dict[str, Any]],
    bk_round_lock: threading.Lock,
    fetch_sem: threading.Semaphore,
    watch_idx: int,
    print_lock: threading.Lock,
    hub: Any,
    prefetched_quotes: dict[tuple[str, str], dict[str, Any]] | None = None,
    bk_cache_stats: dict[str, int] | None = None,
    minute_budget_box: list[int] | None = None,
    minute_budget_lock: threading.Lock | None = None,
) -> dict[str, Any]:
    """拉取单标的行情+K 线+板块 K；供线程池调用。返回 kind ok|invalid|fail。"""
    with fetch_sem:
        code = str(rule.get("code", "")).strip()
        market = str(rule.get("market") or "sh")
        rk = rule_key(rule)

        if not valid_code(code):
            _emit_fetch_line(
                print_lock,
                f"[跳过] {code} 代码须为 6 位数字",
                event="fetch_skip_invalid_code",
                code=code,
                rk=rk,
                level=logging.INFO,
            )
            return {"kind": "invalid", "idx": watch_idx}

        name = get_stock_name(code)
        no_quote = False
        qm: dict[str, Any] | None = None
        got_price_from_hub = False
        if hub is not None:
            qm = hub.get_metrics(code, market)
            if qm is not None and float(qm.get("price") or 0) > 0:
                got_price_from_hub = True
        if (
            qm is None or float(qm.get("price") or 0) <= 0
        ) and prefetched_quotes:
            p0 = prefetched_quotes.get((code, str(market).strip().lower()))
            if p0 is not None and float(p0.get("price") or 0) > 0:
                qm = dict(p0)
                got_price_from_hub = False
        try:
            if qm is None or float(qm.get("price") or 0) <= 0:
                got_price_from_hub = False
                qm = fetch_quote_metrics(code, market, ut=str(ut))
        except Exception as e:
            _emit_fetch_line(
                print_lock,
                f"[行情失败] {code} ({name}): {e}",
                event="quote_fail",
                code=code,
                rk=rk,
                level=logging.WARNING,
            )
            try:
                fp = fetch_price(code, market, ut=str(ut))
                qm = {
                    **fp,
                    "amount_yuan": 0.0,
                    "float_mv_yuan": 0.0,
                    "total_mv_yuan": 0.0,
                }
            except Exception as e2:
                _emit_fetch_line(
                    print_lock,
                    f"[行情二次失败] {code} ({name}): {e2}",
                    event="quote_fail_secondary",
                    code=code,
                    rk=rk,
                    level=logging.WARNING,
                )
                pinned = code in force_include_codes or has_position_tag(rule)
                if not pinned:
                    return {"kind": "fail", "idx": watch_idx}
                got_price_from_hub = False
                qm = {
                    "code": code,
                    "name": name,
                    "price": 0.0,
                    "change_pct": None,
                    "amount_yuan": 0.0,
                    "float_mv_yuan": 0.0,
                    "total_mv_yuan": 0.0,
                    "pre_close": 0.0,
                    "open": 0.0,
                    "high": 0.0,
                    "low": 0.0,
                    "source": "unavailable",
                }
                no_quote = True

        q = dict(qm)
        q["code"] = code
        if got_price_from_hub:
            q["price_source"] = "realtime_hub"
        else:
            q["price_source"] = str(q.get("source") or "eastmoney")

        if hub is not None and float(q.get("price") or 0) > 0:
            chg_for_snap: float | None = None
            _cr = q.get("change_pct")
            if _cr is not None:
                try:
                    chg_for_snap = float(_cr)
                except (TypeError, ValueError):
                    chg_for_snap = None
            snap = hub.get_intraday_snapshot(
                code,
                market,
                price=float(q["price"]),
                change_pct=chg_for_snap,
            )
            for _k, _v in snap.items():
                if _v is not None:
                    q[_k] = _v

        if no_quote:
            kl_raw = None
        else:
            kl_raw = get_stock_kline_data(
                code, market, ut=str(ut), lmt=160, return_closes=True
            )
        closes: list[float] = []
        kline_pure: dict[str, Any] | None = None
        if kl_raw:
            closes = list(kl_raw.get("closes") or [])
            kline_pure = {x: y for x, y in kl_raw.items() if x != "closes"}

        industry = str(rule.get("industry") or "")
        label = rule.get("name") or q.get("name") or get_stock_name(code)
        macro_mult = macro_score_multiplier(
            industry,
            str(label),
            index_mood_mult=index_mult,
            cfg=cfg,
        )
        score_row: dict[str, Any] | None = None
        if (
            not no_quote
            and kline_pure
            and len(closes) >= 40
            and float(q["price"]) > 0
        ):
            score_row = composite_pick_score(
                float(q["price"]),
                kline_pure,
                closes,
                industry=industry,
                stock_name=str(label),
                amount_yuan=float(q.get("amount_yuan") or 0),
                float_mv_yuan=float(q.get("float_mv_yuan") or 0),
                macro_mult=macro_mult,
                cfg=cfg,
            )
        sector_bk_res: str | None = None
        sector_kline_pure: dict[str, Any] | None = None
        sector_closes_list: list[float] = []
        skl2: dict[str, Any] | None = None
        if not no_quote and valid_code(code):
            sector_bk_res = resolve_sector_bk(
                code,
                market,
                cfg,
                root=ROOT,
                fallback_industry=industry,
            )
            if sector_bk_res:
                bk_key = normalize_bk_code(sector_bk_res)
                with bk_round_lock:
                    skl2 = round_bk_kline.get(bk_key)
                    if skl2 is None:
                        skl2 = get_bk_kline_data(
                            sector_bk_res,
                            ut=str(ut),
                            lmt=160,
                            return_closes=True,
                        )
                        if skl2:
                            round_bk_kline[bk_key] = skl2
                        if bk_cache_stats is not None:
                            bk_cache_stats["bk_kline_fetch"] = (
                                int(bk_cache_stats.get("bk_kline_fetch", 0)) + 1
                            )
                    elif bk_cache_stats is not None:
                        bk_cache_stats["bk_kline_hit"] = (
                            int(bk_cache_stats.get("bk_kline_hit", 0)) + 1
                        )
                if skl2:
                    sector_closes_list = list(skl2.get("closes") or [])
                    sector_kline_pure = {
                        x: y for x, y in skl2.items() if x != "closes"
                    }
        sort_score = float(score_row["sort_score"]) if score_row else -1e18
        # 控制台分区「我的持仓」：仅 hold_shares>0（真实持股），不依据 tags / force_include
        _hold_for_section = int(rule.get("hold_shares") or 0)
        minute_kline_snap: dict[str, Any] | None = None
        perf_loc = cfg.get("performance") or {}
        async_am = (
            perf_loc.get("async_minute_kline")
            if isinstance(perf_loc, dict)
            else None
        )
        use_async_minute = (
            not no_quote
            and isinstance(async_am, dict)
            and bool(async_am.get("enabled", False))
        )
        if use_async_minute:
            from async_minute_kline import get_async_minute_kline_for_code

            minute_kline_snap = get_async_minute_kline_for_code(code)
        want_minute = (
            not use_async_minute
            and not no_quote
            and isinstance(perf_loc, dict)
            and bool(perf_loc.get("fetch_minute_kline_today", False))
        )
        if want_minute and bool(perf_loc.get("minute_kline_am_session_only", False)):
            _nt = datetime.now().time()
            if not (TRADING_START_AM <= _nt <= TRADING_END_AM):
                want_minute = False
        if want_minute:
            allow_minute = True
            if minute_budget_box is not None and minute_budget_lock is not None:
                with minute_budget_lock:
                    if minute_budget_box[0] <= 0:
                        allow_minute = False
                    else:
                        minute_budget_box[0] -= 1
            if allow_minute:
                try:
                    from quote_eastmoney import get_stock_minute_kline_summary_today

                    mx_bar = max(
                        32, int(perf_loc.get("minute_kline_max_bars", 256) or 256)
                    )
                    ttl_m = float(
                        perf_loc.get("minute_kline_cache_ttl_sec", 120.0) or 0.0
                    )
                    minute_kline_snap = get_stock_minute_kline_summary_today(
                        code,
                        market,
                        ut=str(ut),
                        lmt=mx_bar,
                        cache_ttl_sec=ttl_m,
                    )
                except Exception:
                    minute_kline_snap = None
        pack = {
            "rule": rule,
            "q": q,
            "kline": kline_pure,
            "closes": closes,
            "score_row": score_row,
            "sort_score": sort_score,
            "tagged": _hold_for_section > 0,
            "rk": rk,
            "label": label,
            "no_quote": no_quote,
            "index_mood_mult": index_mult,
            "index_5d_ret": index_5d_ret,
            "sector_bk": sector_bk_res,
            "sector_kline": sector_kline_pure,
            "sector_closes": sector_closes_list,
            "minute_kline": minute_kline_snap,
        }
        return {"kind": "ok", "idx": watch_idx, "pack": pack}


def _risk_kind_from_stop_msg(msg: str) -> str:
    if "硬性止损" in msg:
        return "stop_loss"
    if "波段" in msg:
        return "take_profit_wave"
    if "短线" in msg:
        return "take_profit_short"
    if "止损" in msg:
        return "stop_loss"
    return "take_profit_short"


def _try_log_watch_alert(
    cfg: dict[str, Any],
    pack: dict[str, Any],
    *,
    alert_type: str,
    rk: str,
    summary: str,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        from alert_log_store import log_watch_alert

        log_watch_alert(
            cfg,
            root=ROOT,
            pack=pack,
            alert_type=alert_type,
            rk=rk,
            summary=summary,
            extra=extra,
        )
    except Exception:
        logging.getLogger(__name__).debug("alert_log_store failed", exc_info=True)


def _ml_external_flow_snapshot(
    cfg: dict[str, Any], feats: dict[str, float] | None
) -> dict[str, float]:
    """从完整特征中取外部资金流字段，写入 JSONL。"""
    if not feats:
        return {}
    mf = cfg.get("ml_filter") if isinstance(cfg, dict) else None
    if not isinstance(mf, dict) or not bool(mf.get("external_flow_features_enabled")):
        return {}
    from external_ml_features import EXTERNAL_FLOW_FEATURE_KEYS

    out: dict[str, float] = {}
    for k in EXTERNAL_FLOW_FEATURE_KEYS:
        if k in feats:
            try:
                out[k] = round(float(feats[k]), 8)
            except (TypeError, ValueError):
                out[k] = 0.0
    return out


def _ml_prob_for_alert(
    cfg: dict[str, Any],
    *,
    alert_type: str,
    anchor_price: float,
    pnl_pct: float | None = None,
    weak_pillars: dict[str, bool] | None = None,
    dd_level: int | None = None,
    code6: str | None = None,
    anchor_trade_date: str | None = None,
) -> tuple[float | None, dict[str, float] | None, int | None]:
    """返回 (NB 概率, 完整特征向量, 已加载模型 JSON 的 features 长度)。"""
    mfc = cfg.get("ml_filter") or {}
    if not bool(mfc.get("enabled", False)):
        return None, None, None
    types = mfc.get("apply_to_alert_types")
    if isinstance(types, list) and len(types) > 0:
        ts = {str(x).strip() for x in types if str(x).strip()}
        if str(alert_type).strip() not in ts:
            return None, None, None
    mp = resolve_ml_model_path(cfg, ROOT)
    model = load_ml_model_cached(mp)
    if not isinstance(model, dict):
        return None, None, None
    try:
        n_model_feats = len(list(model.get("features") or []))
    except (TypeError, ValueError):
        n_model_feats = None
    feats = build_ml_feature_vector(
        alert_type=alert_type,
        anchor_price=anchor_price,
        pnl_pct=pnl_pct,
        weak_pillars=weak_pillars,
        dd_level=dd_level,
        cfg=cfg,
        root=ROOT,
        code6=code6,
        anchor_trade_date=anchor_trade_date,
    )
    return (
        predict_ml_bearish_probability(model, feats),
        feats,
        n_model_feats,
    )


def _ml_kline_decline_prob_for_trend(
    cfg: dict[str, Any],
    *,
    code6: str,
    anchor_td: str,
) -> float | None:
    """全量日 K 模型：未来大跌概率；未启用或失败时返回 None。"""
    mfc = cfg.get("ml_filter") or {}
    if not bool(mfc.get("kline_rf_enabled", False)):
        return None
    try:
        from ml_kline_infer import (
            load_kline_rf_bundle,
            predict_decline_probability,
            resolve_kline_db_path,
            resolve_kline_model_path,
        )
    except Exception:
        return None
    mp = resolve_kline_model_path(cfg, ROOT)
    bundle = load_kline_rf_bundle(mp)
    if not bundle:
        return None
    db = resolve_kline_db_path(cfg, ROOT)
    tbl = str(mfc.get("kline_rf_table") or "daily_klines").strip()
    return predict_decline_probability(
        db_path=db,
        table=tbl,
        code6=code6,
        anchor_trade_date=anchor_td,
        bundle=bundle,
    )


def _dual_ml_trend_suppress(
    *,
    nb_on: bool,
    kl_on: bool,
    ml_prob: float | None,
    k_prob: float | None,
    nb_th: float,
    k_th: float,
    combo: str,
) -> tuple[bool, bool, bool]:
    """
    趋势下滑双重 ML 抑制判定。
    返回 (suppress, nb_low, k_low)；suppress=True 表示应抑制主预警。
    nb_low / k_low：该路已启用、有概率且低于阈值（「模型认为弱势概率低」→ 倾向抑制假阳性）。
    """
    nb_low = bool(
        nb_on and ml_prob is not None and float(ml_prob) < float(nb_th)
    )
    k_low = bool(kl_on and k_prob is not None and float(k_prob) < float(k_th))
    c = str(combo or "any").strip().lower()
    if c == "all":
        if nb_on and kl_on:
            return (nb_low and k_low, nb_low, k_low)
        if nb_on:
            return (nb_low, nb_low, k_low)
        if kl_on:
            return (k_low, nb_low, k_low)
        return (False, nb_low, k_low)
    return (nb_low or k_low, nb_low, k_low)


def _parse_hhmm(s: str, fallback_h: int, fallback_m: int) -> tuple[int, int]:
    txt = str(s or "").strip()
    try:
        h0, m0 = txt.split(":", 1)
        h = max(0, min(23, int(h0)))
        m = max(0, min(59, int(m0)))
        return h, m
    except Exception:
        return fallback_h, fallback_m


def _self_health_kline_max_date(cfg: dict[str, Any], *, root: Path) -> str | None:
    """返回 daily_klines 库中全局最新 trade_date（YYYY-MM-DD），失败为 None。"""
    import sqlite3

    ks = cfg.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    p = Path(rel)
    if not p.is_absolute():
        p = root / p
    if not p.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute("SELECT MAX(trade_date) FROM daily_klines").fetchone()
        if not row or row[0] is None:
            return None
        s = str(row[0]).strip()[:10]
        return s if len(s) == 10 else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _self_health_pending_alert_count(cfg: dict[str, Any], *, root: Path) -> int:
    import sqlite3

    try:
        from alert_log_store import resolve_alert_db_path
    except Exception:
        return 0
    db_path = resolve_alert_db_path(cfg, root)
    if db_path is None or not db_path.is_file():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM alert_events WHERE eval_status = 'pending'"
        ).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _maybe_self_health_preopen(
    *,
    cfg: dict[str, Any],
    state: dict[str, Any],
    config_path: Path,
    oa: dict[str, Any],
    now: datetime,
    today: str,
    py: str,
) -> None:
    """每个交易日开盘窗口内至多执行一次：数据新鲜度巡检与轻量自愈。"""
    if not bool(oa.get("self_health_enabled", False)):
        return
    if state.get("__self_health_preopen_done__") == today:
        return
    ph, pm = _parse_hhmm(str(oa.get("preopen_cutoff_hhmm") or "09:20"), 9, 20)
    if now.time() > dt_time(ph, pm):
        return

    max_lag = max(0, int(oa.get("self_health_kline_max_lag_calendar_days", 1) or 1))
    pend_min = max(10, int(oa.get("self_health_pending_alerts_min", 200) or 200))
    ttl_mult = float(oa.get("self_health_sector_cache_ttl_mult", 2.0) or 2.0)

    mx = _self_health_kline_max_date(cfg, root=ROOT)
    need_before = (date.today() - timedelta(days=max_lag)).isoformat()
    if mx is None or mx < need_before:
        _emit_main_line(
            f"[自愈] 日 K 库最新日期={mx or '—'}，晚于阈值 {need_before}，执行 sync_daily_klines",
            event="ops_self_health_sync_klines",
        )
        _run_local_script(
            [py, str(ROOT / "sync_daily_klines.py"), "-c", str(config_path)],
            event="ops_self_health_sync_klines_run",
        )

    try:
        from sector_em import sector_index_cache_path

        cpath = sector_index_cache_path(cfg, ROOT)
        se = cfg.get("sector_em") or {}
        ttl = float(se.get("industry_map_ttl_sec", 3600) or 3600) * max(0.5, ttl_mult)
        if cpath.is_file():
            age = time.time() - cpath.stat().st_mtime
            if age > ttl:
                _emit_main_line(
                    f"[自愈] 行业缓存 {cpath.name} 已 {age / 3600:.1f}h 未更新（>{ttl / 3600:.1f}h），删除以强制刷新",
                    event="ops_self_health_sector_cache_stale",
                )
                try:
                    cpath.unlink()
                except OSError:
                    pass
    except Exception as exc:
        _emit_main_line(
            f"[自愈] 行业缓存检查异常: {exc}",
            event="ops_self_health_sector_err",
            level=logging.WARNING,
        )

    pend = _self_health_pending_alert_count(cfg, root=ROOT)
    if pend >= pend_min:
        _emit_main_line(
            f"[自愈] alert_events 待评估 {pend} 条（≥{pend_min}），执行 backtest_alerts（仅 pending）",
            event="ops_self_health_backtest_pending",
        )
        _run_local_script(
            [
                py,
                str(ROOT / "backtest_alerts.py"),
                "-c",
                str(config_path),
                "--since",
                "2000-01-01",
                "--reeval-missing-returns",
            ],
            event="ops_self_health_backtest_run",
        )

    state["__self_health_preopen_done__"] = today


def _maybe_friday_buy_filter_digest_notify(
    *,
    cfg: dict[str, Any],
    state: dict[str, Any],
    oa: dict[str, Any],
    now: datetime,
) -> None:
    """周五收盘后：汇总 watch_strategy_buy_filtered 后续收益，经 send_email_alert 双通道投递。"""
    if not bool(oa.get("friday_buy_filter_digest_enabled", True)):
        return
    if now.weekday() != 4:
        return
    week_tag = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    if state.get("__ops_buy_filter_digest_week__") == week_tag:
        return
    from buy_filter_digest import build_friday_buy_filter_digest
    from email_notify import send_email_alert

    fd = max(1, int(oa.get("buy_filter_digest_forward_days", 5) or 5))
    mx = max(1, int(oa.get("buy_filter_digest_max_events", 200) or 200))
    ut_raw = (cfg.get("sources") or {}).get("eastmoney_ut")
    ut = str(ut_raw).strip() if ut_raw else None
    ok = False
    try:
        subject, body = build_friday_buy_filter_digest(
            cfg, ROOT, forward_days=fd, max_events=mx, ut=ut
        )
        ok = bool(send_email_alert(subject, body, app_cfg=cfg))
    except Exception as exc:
        _emit_main_line(
            f"[自动化] 周五买入过滤复盘失败: {exc}",
            event="ops_friday_buy_filter_digest_err",
            level=logging.WARNING,
        )
    else:
        _emit_main_line(
            f"[自动化] 周五买入过滤复盘已投递（send_ok={ok}）",
            event="ops_friday_buy_filter_digest_done",
        )
    state["__ops_buy_filter_digest_week__"] = week_tag


def _run_local_script(argv: list[str], *, event: str) -> bool:
    try:
        cp = subprocess.run(
            argv,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except Exception as exc:
        _emit_main_line(
            f"[自动化] {event} 启动失败: {exc}",
            event="ops_auto_task_fail",
            level=logging.WARNING,
        )
        return False
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    tail = out[-280:] if out else (err[-280:] if err else "")
    if cp.returncode == 0:
        _emit_main_line(
            f"[自动化] {event} 完成" + (f"｜{tail}" if tail else ""),
            event="ops_auto_task_ok",
        )
        return True
    _emit_main_line(
        f"[自动化] {event} 失败 rc={cp.returncode}" + (f"｜{tail}" if tail else ""),
        event="ops_auto_task_fail",
        level=logging.WARNING,
    )
    return False


def _maybe_run_ops_automation(
    *,
    cfg: dict[str, Any],
    state: dict[str, Any],
    config_path: Path,
) -> None:
    oa = cfg.get("ops_automation") or {}
    if not bool(oa.get("enabled", False)):
        return
    now = datetime.now()
    if now.weekday() >= 5:
        return
    today = now.strftime("%Y-%m-%d")
    py = sys.executable

    _maybe_self_health_preopen(
        cfg=cfg,
        state=state,
        config_path=config_path,
        oa=oa,
        now=now,
        today=today,
        py=py,
    )

    # 开盘前任务（每天一次）
    if bool(oa.get("preopen_enabled", True)):
        ph, pm = _parse_hhmm(str(oa.get("preopen_cutoff_hhmm") or "09:20"), 9, 20)
        if now.time() <= dt_time(ph, pm) and state.get("__ops_preopen_done__") != today:
            _emit_main_line(
                "[自动化] 开盘前任务开始：sync_daily_klines -> compute_kline_indicators -> daily_select"
                "（选股完成后程序内会再同步一次日 K，含新 picks）",
                event="ops_auto_preopen_start",
            )
            _run_local_script(
                [py, str(ROOT / "sync_daily_klines.py"), "-c", str(config_path)],
                event="preopen_sync_daily_klines",
            )
            _run_local_script(
                [py, str(ROOT / "compute_kline_indicators.py"), "-c", str(config_path)],
                event="preopen_compute_indicators",
            )
            _run_local_script(
                [py, str(ROOT / "run_alert.py"), "-c", str(config_path), "--daily-select"],
                event="preopen_daily_select",
            )
            state["__ops_preopen_done__"] = today

    # 收盘后任务（每天一次）
    if bool(oa.get("after_close_enabled", True)):
        ah, am = _parse_hhmm(str(oa.get("after_close_hhmm") or "15:10"), 15, 10)
        if now.time() >= dt_time(ah, am) and state.get("__ops_after_close_done__") != today:
            since_days = max(1, int(oa.get("backtest_since_days", 7) or 7))
            since_day = (now.date() - timedelta(days=since_days)).isoformat()
            _emit_main_line(
                "[自动化] 收盘后任务开始：backtest_alerts + auto_tune",
                event="ops_auto_after_close_start",
            )
            _run_local_script(
                [
                    py,
                    str(ROOT / "backtest_alerts.py"),
                    "-c",
                    str(config_path),
                    "--since",
                    since_day,
                    "--reeval-missing-returns",
                    "--json-out",
                    str(ROOT / "weekly.json"),
                ],
                event="after_close_backtest",
            )
            tune_cmd = [
                py,
                str(ROOT / "auto_tune_accuracy.py"),
                "--days",
                str(since_days),
                "--config",
                str(config_path),
            ]
            if not bool(oa.get("auto_tune_apply", False)):
                tune_cmd.append("--dry-run")
            if bool(oa.get("auto_tune_email", True)):
                tune_cmd.append("--email")
            _run_local_script(tune_cmd, event="after_close_auto_tune")
            if bool(oa.get("incremental_nb_after_close", False)):
                inc_days = max(7, int(oa.get("incremental_nb_days", 30) or 30))
                inc_min = max(6, int(oa.get("incremental_nb_min_samples", 12) or 12))
                _run_local_script(
                    [
                        py,
                        str(ROOT / "ml_nb_incremental.py"),
                        "-c",
                        str(config_path),
                        "--days",
                        str(inc_days),
                        "--min-samples",
                        str(inc_min),
                    ],
                    event="after_close_ml_nb_incremental",
                )
            _maybe_friday_buy_filter_digest_notify(
                cfg=cfg, state=state, oa=oa, now=now
            )
            state["__ops_after_close_done__"] = today

    # 周五额外任务（每周一次）
    if bool(oa.get("friday_weekly_enabled", True)) and now.weekday() == 4:
        week_tag = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        if state.get("__ops_weekly_done__") != week_tag:
            _emit_main_line(
                "[自动化] 周五任务开始：ML 训练",
                event="ops_auto_weekly_start",
            )
            if bool(oa.get("ml_train_weekly", True)):
                _run_local_script(
                    [
                        py,
                        str(ROOT / "ml_train.py"),
                        "-c",
                        str(config_path),
                        "--days",
                        str(max(30, int(oa.get("ml_train_days", 180) or 180))),
                        "--min-samples",
                        str(max(6, int(oa.get("ml_train_min_samples", 18) or 18))),
                        "--model-out",
                        str(ROOT / "data" / "ml_bearish_nb.json"),
                    ],
                    event="weekly_ml_train",
                )
            if bool(oa.get("friday_kline_rf_train_enabled", False)):
                mf = cfg.get("ml_filter") or {}
                db_rf = str(mf.get("kline_rf_db_path") or "data/baostock_full.db").strip()
                tbl = str(mf.get("kline_rf_table") or "daily_klines").strip()
                mpath = str(mf.get("kline_rf_model_path") or "models/kline_rf.pkl").strip()
                db_p = Path(db_rf)
                if not db_p.is_absolute():
                    db_p = ROOT / db_p
                m_out = Path(mpath)
                if not m_out.is_absolute():
                    m_out = ROOT / m_out
                if db_p.is_file():
                    _run_local_script(
                        [
                            py,
                            str(ROOT / "train_kline_model.py"),
                            "--db",
                            str(db_p),
                            "--table",
                            tbl,
                            "--model",
                            str(m_out),
                            "--feature-set",
                            "trend",
                        ],
                        event="weekly_kline_rf_train",
                    )
                else:
                    _emit_main_line(
                        f"[自动化] 跳过日 K RF 重训：未找到库 {db_p}",
                        event="weekly_kline_rf_skip",
                        level=logging.WARNING,
                    )
            state["__ops_weekly_done__"] = week_tag


def _maybe_poll_email_commands(
    *,
    cfg: dict[str, Any],
    state: dict[str, Any],
    config_path: Path,
    force_include_codes: set[str],
    force_exclude_codes: set[str],
) -> None:
    ecb = cfg.get("email_command_bot") or {}
    if not bool(ecb.get("enabled", False)):
        return
    now_ts = time.time()
    poll_iv = max(10.0, float(ecb.get("poll_interval_sec", 45) or 45))
    last_ts = float(state.get("__email_cmd_last_poll_ts__") or 0.0)
    if now_ts - last_ts < poll_iv:
        return
    state["__email_cmd_last_poll_ts__"] = now_ts
    poll = fetch_email_bot_actions(cfg)
    if (
        not poll.runtime_commands
        and not poll.feedback_commands
        and not poll.config_commands
    ):
        return
    for kind, code in poll.feedback_commands:
        n = apply_feedback_to_latest_alert(
            cfg, ROOT, code=code, feedback=kind
        )
        if n:
            _emit_main_line(
                f"[邮件反馈] 已记录 {kind.upper()} → 最近一条预警：{code}",
                event="email_feedback_applied",
            )
        else:
            _emit_main_line(
                f"[邮件反馈] 未找到可标注的 trend_slip/drawdown 记录：{kind} {code}",
                event="email_feedback_miss",
            )
    for cmd in poll.config_commands:
        _emit_main_line(
            f"[邮件指令·配置] 执行：{cmd}",
            event="email_cmd_config_exec",
        )
        _handle_runtime_command(
            cmd,
            cfg=cfg,
            config_path=config_path,
            force_include_codes=force_include_codes,
            force_exclude_codes=force_exclude_codes,
        )
    for cmd in poll.runtime_commands:
        _emit_main_line(
            f"[邮件指令] 执行：{cmd}",
            event="email_cmd_exec",
        )
        _handle_runtime_command(
            cmd,
            cfg=cfg,
            config_path=config_path,
            force_include_codes=force_include_codes,
            force_exclude_codes=force_exclude_codes,
        )


def process_watch_pack(
    pack: dict[str, Any],
    *,
    risk: RiskManager,
    state: dict[str, Any],
    cfg: dict[str, Any],
    args: Any,
    buffer: float,
    cooldown_min: float,
    now_ts: float,
    log_dir: Path,
    show_pick_card: bool,
    round_notify_digest: list[dict[str, Any]] | None = None,
    round_trend_digest: list[dict[str, Any]] | None = None,
    state_mut_lock: threading.RLock | None = None,
    buy_mail_bucket: str | None = None,
) -> float:
    """单标的：行情展示、标签、策略、止盈止损、补仓、区间提醒；返回持仓市值。"""
    rule = pack["rule"]
    q = pack["q"]
    kline = pack["kline"]
    rk = pack["rk"]
    score_row = pack.get("score_row")
    code = str(q.get("code") or rule.get("code") or "")
    disp_name = get_stock_name(code)

    if pack.get("no_quote"):
        tstr = datetime.now().strftime("%H:%M:%S")
        _emit_watch_line(
            color_line(
                None,
                f"[{tstr}] {code} ({disp_name}) 现价 — 当日 — "
                f"｜行情暂不可用（持仓/hold 仍展示，下一轮重试）",
            ),
            event="watch_no_quote",
            code=code,
            rk=rk,
        )
        _emit_watch_line(
            format_tags_line(rule), event="watch_tags", code=code, rk=rk
        )
        return 0.0

    now_price = float(q["price"])
    day_pct = q.get("change_pct")
    dp = day_pct if day_pct is not None else 0.0
    tstr = datetime.now().strftime("%H:%M:%S")
    base_txt = (
        f"[{tstr}] {code} ({get_stock_name(code)}) "
        f"现价 {now_price:.2f} 当日 {dp:+.2f}%"
    )
    _emit_watch_line(
        color_line(day_pct, base_txt), event="watch_quote", code=code, rk=rk
    )
    _emit_watch_line(format_tags_line(rule), event="watch_tags", code=code, rk=rk)
    psrc = str(q.get("price_source") or "").strip()
    if psrc:
        _emit_watch_line(
            f"      └ 现价来源：{psrc}",
            event="watch_price_source",
            code=code,
            rk=rk,
        )
    kl_meta = kline or {}
    ksrc = str(kl_meta.get("kline_data_source") or "").strip()
    kld = str(kl_meta.get("kline_last_trade_date") or "").strip()
    ksync = str(kl_meta.get("kline_db_last_sync_iso") or "").strip()
    if ksrc or kld or ksync:
        extra = ""
        if kld:
            extra += f"｜最新日 {kld}"
        if ksync:
            extra += f"｜库同步 {ksync[:19]}"
        _emit_watch_line(
            f"      └ K 线数据：{ksrc or '—'}{extra}",
            event="watch_kline_meta",
            code=code,
            rk=rk,
        )
    kst = cfg.get("kline_store") or {}
    div_pct = float(kst.get("divergence_warn_price_pct") or 0) if isinstance(kst, dict) else 0.0
    closes_warn = list(pack.get("closes") or [])
    if (
        div_pct > 0
        and ksrc == "sqlite"
        and closes_warn
        and now_price > 0
    ):
        lc = float(closes_warn[-1])
        if lc > 0:
            gap = abs(now_price - lc) / lc
            if gap >= div_pct:
                _emit_watch_line(
                    f"      └ ⚠️ 本地 K 末收盘 {lc:.3f} 与现价偏离 {gap * 100:.2f}% "
                    f"（≥ 配置阈值 {div_pct * 100:.2f}%）",
                    event="watch_kline_divergence",
                    code=code,
                    rk=rk,
                    level=logging.WARNING,
                )
    bk_trend = str(pack.get("sector_bk") or "").strip()
    if bk_trend:
        _emit_watch_line(
            f"      └ 趋势板块柱 BK：{bk_trend}",
            event="watch_sector_bk",
            code=code,
            rk=rk,
        )

    if show_pick_card and score_row:
        _emit_watch_line(
            f"      └ 【优选画像】形态评分 {score_row['pattern_score']:.1f}｜"
            f"盈利概率约 {score_row['profit_prob_pct']:.1f}%｜"
            f"风险 {score_row['risk_level']}｜低吸逻辑：{score_row['dip_logic']}",
            event="watch_pick_card",
            code=code,
            rk=rk,
        )

    cost = float(rule.get("cost_price") or 0.0)
    hold = int(rule.get("hold_shares") or 0)
    mv = now_price * max(hold, 0)

    if cost > 0:
        pnl = risk.calc_profit_pct(now_price, cost)
        loss_before = pnl if pnl < 0 else 0.0
        _emit_watch_line(
            f"      └ 持仓盈亏 {pnl:+.2f}%"
            + (
                f"｜补仓前亏损幅度约 {loss_before:.2f}%"
                if loss_before < 0
                else "｜补仓前为盈利或持平"
            ),
            event="watch_pnl",
            code=code,
            rk=rk,
        )
    else:
        pnl = 0.0

    pscfg = cfg.get("position_suggestion") or {}
    if (
        bool(pscfg.get("enabled", True))
        and has_position_tag(rule)
        and cost > 0
        and not pack.get("no_quote")
    ):
        _fill_position_suggestion_metrics(pack, now_price)
        kl_ps = pack.get("kline") or {}
        anchor_td_ps = str(kl_ps.get("kline_last_trade_date") or "").strip()
        if len(anchor_td_ps) < 10:
            anchor_td_ps = datetime.now().strftime("%Y-%m-%d")
        else:
            anchor_td_ps = anchor_td_ps[:10]
        code6_ps = normalize_stock_code(code) or code
        bp_sug = _ml_bearish_prob_for_position_suggestion(
            cfg,
            now_price=now_price,
            pnl_pct=float(pnl),
            code6=code6_ps,
            anchor_trade_date=anchor_td_ps,
        )
        act, why = _get_position_suggestion(
            pack,
            cfg,
            pnl_pct=float(pnl),
            bearish_prob=bp_sug,
        )
        if act != "持有" and why:
            _emit_watch_line(
                f"      └ 【仓位建议】{act}（{why}）",
                event="watch_position_suggestion",
                code=code,
                rk=rk,
            )
            ps_log_k = f"ps_suggest_log_{rk}"
            if state.get(ps_log_k) != anchor_td_ps:
                _try_log_watch_alert(
                    cfg,
                    pack,
                    alert_type="position_suggestion",
                    rk=rk,
                    summary=f"{act}｜{why}",
                    extra={
                        "ps_action": act,
                        "ps_reason": why,
                        "pnl_pct": float(pnl),
                        "box_pct": pack.get("_ps_box_pct"),
                        "vol_ratio": pack.get("_ps_vol_ratio"),
                        "above_ma5": pack.get("_ps_above_ma5"),
                        "above_ma20": pack.get("_ps_above_ma20"),
                        "above_ma60": pack.get("_ps_above_ma60"),
                        "market_mood_tier": pack.get("_market_mood_tier"),
                        "bearish_prob": bp_sug,
                    },
                )
                state[ps_log_k] = anchor_td_ps

    sw = risk.check_single_position_value(mv)
    if sw:
        _emit_watch_line(
            f"      └ 【仓位】{sw}",
            event="watch_position_cap",
            code=code,
            rk=rk,
        )

    _state_cm = state_mut_lock if state_mut_lock is not None else nullcontext()
    with _state_cm:
        min_by = (cfg.get("strategy_signal") or {}).get("min_score_by_strategy")
        raw_sig = (
            ma_box_strategy(
                now_price,
                kline,
                min_score_by_strategy=min_by if isinstance(min_by, dict) else None,
            )
            if kline
            else None
        )
        sig = raw_sig
        if raw_sig and "【买入信号】" in raw_sig:
            sbf_gate = cfg.get("_runtime_effective_strategy_buy_filter")
            if not isinstance(sbf_gate, dict):
                sbf_gate = cfg.get("strategy_buy_filter") or {}
            if bool(sbf_gate.get("enabled", True)):
                _fill_position_suggestion_metrics(pack, now_price)
                br = _strategy_buy_realtime_blocked(pack, cfg)
                if br:
                    ip_s = ""
                    ip_raw = (pack.get("q") or {}).get("intraday_position")
                    if ip_raw is not None:
                        try:
                            ip_s = f" 日内位{float(ip_raw):.2f}"
                        except (TypeError, ValueError):
                            ip_s = ""
                    _emit_watch_line(
                        f"      └ 【策略】{code} ({disp_name}) "
                        f"买入信号未采纳（实时过滤）{ip_s}｜{br}",
                        event="watch_strategy_buy_filtered",
                        code=code,
                        rk=rk,
                        skipped_by_filter=br,
                    )
                    sig = None
        # 持仓策略邮件：同一轮「买入/卖出」持续期间只发一封；信号消失后再出现再发
        sig_has_buy = bool(sig and "【买入信号】" in sig)
        sig_has_sell = bool(sig and "【卖出信号】" in sig)
        ep_buy_k = f"strat_ep_mail_buy_{rk}"
        ep_sell_k = f"strat_ep_mail_sell_{rk}"
        if not sig_has_buy:
            state.pop(ep_buy_k, None)
        if not sig_has_sell:
            state.pop(ep_sell_k, None)
        if sig:
            sig_k = f"sig_{rk}"
            code6_t1 = normalize_stock_code(code) or ""
            if valid_code(code6_t1):
                plan = plan_strategy_t1(code6_t1, sig, state)
            else:
                plan = T1StrategyPlan(
                    show_line=True,
                    line_text=sig,
                    allow_notify=True,
                    allow_email_buy=True,
                    allow_email_sell=True,
                    commit_side=None,
                    log_sig=sig,
                    suppressed_sell=False,
                    suppressed_buy=False,
                    suppressed_duplicate_buy=False,
                )
            if plan.show_line:
                _emit_watch_line(
                    f"      └ 【策略】{bold_strategy_buy_sell(plan.line_text)}",
                    event="watch_strategy",
                    code=code,
                    rk=rk,
                )
            if channel_cooldown_ok(state, sig_k, cooldown_min, now_ts) and plan.allow_notify:
                if not args.no_notify:
                    send_notification(
                        f"策略｜{disp_name}",
                        sig,
                        f"{now_price:.2f} 元",
                        cfg=cfg,
                        severity="info",
                    )
                    _try_log_watch_alert(
                        cfg,
                        pack,
                        alert_type="strategy",
                        rk=rk,
                        summary=sig[:800],
                        extra=None,
                    )
                    if "【买入信号】" in sig and plan.allow_email_buy:
                        send_buy_ok = False
                        _bkt = str(buy_mail_bucket or "监控").strip() or "监控"
                        if not state.get(ep_buy_k) and send_buy_signal_email(
                            f"【买入信号·{_bkt}】",
                            f"分区：{_bkt}\n{code} {disp_name} 可以买入\n{sig}\n现价：{now_price:.2f} 元",
                            app_cfg=cfg,
                        ):
                            state[ep_buy_k] = True
                            send_buy_ok = True
                        if send_buy_ok:
                            _emit_watch_line(
                                "      └ （已发邮件通知）",
                                event="watch_email_sent",
                                code=code,
                                rk=rk,
                            )
                    elif (
                        "【卖出信号】" in sig
                        and hold > 0
                        and plan.allow_email_sell
                    ):
                        if not state.get(ep_sell_k) and send_sell_signal_email(
                            "【卖出信号】",
                            f"{code} {disp_name} 可以卖出（持仓 {hold} 股）\n{sig}\n现价：{now_price:.2f} 元",
                            app_cfg=cfg,
                        ):
                            state[ep_sell_k] = True
                            _emit_watch_line(
                                "      └ （已发邮件通知）",
                                event="watch_email_sent",
                                code=code,
                                rk=rk,
                            )
                    log_signal(disp_name, code, sig, now_price, base_dir=log_dir)
                if valid_code(code6_t1):
                    if plan.commit_side == "buy" and "【买入信号】" in sig:
                        commit_strategy_emit(code6_t1, "buy", state)
                    elif plan.commit_side == "sell" and "【卖出信号】" in sig:
                        commit_strategy_emit(code6_t1, "sell", state)
                state[sig_k] = now_ts

        st_msg = risk.check_stop_take(now_price, cost) if cost > 0 else None
        code6_risk = normalize_stock_code(code) or ""
        if (
            st_msg
            and valid_code(code6_risk)
            and should_suppress_risk_stop_take(code6_risk, state)
        ):
            st_msg = None
        if st_msg:
            risk_k = f"risk_{rk}"
            ms = str(st_msg)
            if "硬性止损" in ms:
                _st_head = "【止损提醒】"
            elif "波段" in ms:
                _st_head = "【止盈提醒】"
            elif "短线" in ms:
                _st_head = "【止盈提醒】"
            else:
                _st_head = "【止盈止损】"
            _emit_watch_line(
                f"      └ {_st_head}{bold_console(st_msg)}｜相对成本盈亏 {pnl:+.2f}%",
                event="watch_stop_take",
                code=code,
                rk=rk,
            )
            if channel_cooldown_ok(state, risk_k, cooldown_min, now_ts) and (
                not args.no_notify
            ):
                send_notification(
                    f"风控｜{disp_name}",
                    f"{st_msg}\n当前相对成本盈亏：{pnl:+.2f}%",
                    f"成本 {cost:.3f}",
                    sound=True,
                    cfg=cfg,
                    severity="critical",
                )
                _try_log_watch_alert(
                    cfg,
                    pack,
                    alert_type="risk_stop_take",
                    rk=rk,
                    summary=st_msg,
                    extra={
                        "risk_kind": _risk_kind_from_stop_msg(st_msg),
                        "pnl_pct": pnl,
                    },
                )
                state[risk_k] = now_ts

        dd_alert = risk.check_drawdown_alert(now_price, cost) if cost > 0 else None
        dd_cfg_ign = cfg.get("drawdown_alert") or {}
        dd_ign_raw = dd_cfg_ign.get("alert_ignore_codes") or []
        dd_ign_set = {
            str(x).strip().zfill(6)
            for x in dd_ign_raw
            if str(x).strip().isdigit() and len(str(x).strip()) <= 6
        }
        code6_dd = code6_risk.zfill(6) if code6_risk.isdigit() else code6_risk
        dd_code_blocked = len(code6_dd) == 6 and code6_dd in dd_ign_set
        if (
            dd_alert
            and valid_code(code6_risk)
            and not dd_code_blocked
            and not should_suppress_risk_stop_take(code6_risk, state)
        ):
            dd_lv, dd_msg = dd_alert
            dd_k = f"dd_{dd_lv}_{rk}"
            _emit_watch_line(
                f"      └ 【下跌预警】{bold_console(dd_msg)}｜相对成本盈亏 {pnl:+.2f}%",
                event="watch_drawdown",
                code=code,
                rk=rk,
            )
            if channel_cooldown_ok(state, dd_k, cooldown_min, now_ts) and (
                not args.no_notify
            ):
                send_notification(
                    f"下跌预警｜{disp_name}",
                    f"{dd_msg}\n当前相对成本盈亏：{pnl:+.2f}%",
                    f"成本 {cost:.3f}",
                    sound=True,
                    cfg=cfg,
                    severity="warning",
                )
                _try_log_watch_alert(
                    cfg,
                    pack,
                    alert_type="drawdown",
                    rk=rk,
                    summary=dd_msg,
                    extra={"dd_level": dd_lv, "pnl_pct": pnl},
                )
                state[dd_k] = now_ts

        closes_pack = list(pack.get("closes") or [])
        kline_for_trend = kline or {}
        idx_mult_pack = float(pack.get("index_mood_mult") or 1.0)
        idx5_pack = pack.get("index_5d_ret")
        idx5_f = float(idx5_pack) if idx5_pack is not None else None
        trend_cfg = cfg.get("trend_slippage_alert") or {}
        sector_bk_p = pack.get("sector_bk")
        sector_kline_p = pack.get("sector_kline")
        sector_closes_p = list(pack.get("sector_closes") or [])
        trend_suppress = int(state.get("__trend_suppress_rounds__") or 0)
        req_bk = bool(trend_cfg.get("require_resolved_bk"))
        bk_ok = bool(str(sector_bk_p or "").strip())
        if req_bk and not bk_ok:
            pass
        elif (
            bool(trend_cfg.get("enabled", True))
            and trend_suppress <= 0
            and cost > 0
            and len(closes_pack) >= 40
            and kline_for_trend.get("opens")
            and not pack.get("no_quote")
        ):
            fm_raw = q.get("float_mv_yuan")
            try:
                fm_yuan = (
                    float(fm_raw)
                    if fm_raw is not None and str(fm_raw).strip() != ""
                    else None
                )
            except (TypeError, ValueError):
                fm_yuan = None
            if fm_yuan is not None and fm_yuan <= 0:
                fm_yuan = None
            tr = evaluate_trend_slippage_alert(
                now_price,
                kline_for_trend,
                closes_pack,
                idx_mult_pack,
                idx5_f,
                sector_bk=str(sector_bk_p).strip() if sector_bk_p else None,
                sector_kline=sector_kline_p if isinstance(sector_kline_p, dict) else None,
                sector_closes=sector_closes_p,
                cfg=cfg,
                stock_code=code,
                float_mv_yuan=fm_yuan,
                dynamic_min_pillars_weak=pack.get("_dynamic_min_pillars_weak"),
            )
            if tr.skipped_by_filter:
                _emit_watch_line(
                    f"      └ {tr.summary}",
                    event="watch_trend_slip_skipped",
                    code=code,
                    rk=rk,
                )
                try:
                    from app_logging import record_alert_event

                    record_alert_event(
                        logging.INFO,
                        _strip_ansi(tr.summary),
                        event="watch_trend_slip_skipped",
                        code=code,
                        rk=rk,
                        section="watch_pack",
                        skipped_by_filter=tr.skipped_by_filter,
                    )
                except Exception:
                    pass
            anchor_td = str(kline_for_trend.get("kline_last_trade_date") or "").strip()
            if len(anchor_td) < 10:
                anchor_td = datetime.now().strftime("%Y-%m-%d")
            else:
                anchor_td = anchor_td[:10]
            nconf = max(1, int(trend_cfg.get("require_consecutive_trade_days", 1) or 1))
            mkt_raw = str(rule.get("market") or "").strip().lower()
            if mkt_raw in ("1", "sse", "sh"):
                mkt_slip = "sh"
            elif mkt_raw in ("0", "szse", "sz"):
                mkt_slip = "sz"
            else:
                mkt_slip = _infer_market(code)
            try:
                slip_secid = secid_for(code, mkt_slip)
            except ValueError:
                slip_secid = secid_for(
                    (normalize_stock_code(code) or code)[:6], _infer_market(code)
                )
            notify_ok, _streak_n, cnote = consecutive_trend_slip_notify_ok(
                cfg,
                root=ROOT,
                rk=rk,
                secid=slip_secid,
                anchor_td=anchor_td,
                raw_fire=bool(tr.fire),
            )
            if tr.fire and (not notify_ok) and nconf > 1:
                summ = tr.summary or ""
                tail = f"{summ[:120]}…" if len(summ) > 120 else summ
                _emit_watch_line(
                    f"      └ 趋势下滑(观察)｜{cnote}；{tail}",
                    event="watch_trend_slip_deferred",
                    code=code,
                    rk=rk,
                )
            ml_prob: float | None = None
            ml_nb_feats: dict[str, float] | None = None
            ml_nb_model_dim: int | None = None
            k_p: float | None = None
            ml_allow = True
            if tr.fire and notify_ok:
                mcfg = cfg.get("ml_filter") or {}
                nb_on = bool(mcfg.get("enabled", False))
                kl_on = bool(mcfg.get("kline_rf_enabled", False))
                ml_prob, ml_nb_feats, ml_nb_model_dim = _ml_prob_for_alert(
                    cfg,
                    alert_type="trend_slip",
                    anchor_price=now_price,
                    pnl_pct=pnl,
                    weak_pillars=tr.weak_pillars,
                    dd_level=None,
                    code6=str(code6_risk or ""),
                    anchor_trade_date=anchor_td[:10],
                )
                if not nb_on:
                    ml_prob = None
                    ml_nb_feats = None
                    ml_nb_model_dim = None
                if kl_on:
                    k_p = _ml_kline_decline_prob_for_trend(
                        cfg,
                        code6=code6_risk,
                        anchor_td=anchor_td,
                    )
                ml_th = float(mcfg.get("bearish_prob_threshold", 0.60) or 0.60)
                k_th = float(mcfg.get("kline_rf_suppress_below", 0.30) or 0.30)
                combo = str(mcfg.get("suppress_combo", "any") or "any").strip().lower()
                suppress, nb_low, kl_low = _dual_ml_trend_suppress(
                    nb_on=nb_on,
                    kl_on=kl_on,
                    ml_prob=ml_prob,
                    k_prob=k_p,
                    nb_th=ml_th,
                    k_th=k_th,
                    combo=combo,
                )
                if suppress and (nb_low or kl_low):
                    ml_allow = False
                    parts: list[str] = []
                    if nb_low:
                        parts.append(f"NB {ml_prob:.1%}<{ml_th:.1%}")
                    if kl_low:
                        parts.append(f"日K {k_p:.1%}<{k_th:.1%}")
                    mode_cn = "需同时满足" if combo == "all" else "任一满足"
                    _emit_watch_line(
                        f"      └ 趋势下滑(ML组合｜{mode_cn})｜" + "；".join(parts),
                        event="watch_trend_slip_ml_combo_suppressed",
                        code=code,
                        rk=rk,
                    )
            if (
                tr.fire
                and notify_ok
                and ml_allow
                and valid_code(code6_risk)
                and not should_suppress_risk_stop_take(code6_risk, state)
            ):
                trend_k = f"trend_slip_{rk}"
                tip = f"【趋势下滑预警】{tr.summary}"
                _emit_watch_line(
                    f"      └ {bold_console(tip)}｜相对成本盈亏 {pnl:+.2f}%",
                    event="watch_trend_slip",
                    code=code,
                    rk=rk,
                )
                if not tr.sector_eligible:
                    pillar_degrade_msg = tr.sector_data_warning or (
                        "⚠️ 板块K线缺失或未计板块柱：当前为「个股技术+大盘」两柱联动；"
                        "建议在 sector_index_overrides 中绑定正确 BK。"
                    )
                    _emit_watch_line(
                        f"      └ {bold_console(pillar_degrade_msg)}",
                        event="watch_trend_pillar_degrade",
                        code=code,
                        rk=rk,
                    )
                else:
                    pillar_degrade_msg = ""
                if bool(trend_cfg.get("verbose_trend_alert", True)):
                    for pk, wk in tr.weak_pillars.items():
                        _emit_watch_line(
                            f"      └ 弱柱｜{pk}={'是' if wk else '否'}",
                            event="watch_trend_pillar_dim",
                            code=code,
                            rk=rk,
                        )
                    for pk, rs in tr.weak_dims_by_pillar.items():
                        if not rs:
                            continue
                        tail = "；".join(rs[:8])
                        _emit_watch_line(
                            f"      └ 子项｜{pk}: {tail}",
                            event="watch_trend_dim_detail",
                            code=code,
                            rk=rk,
                        )
                    try:
                        from app_logging import record_alert_event

                        record_alert_event(
                            logging.INFO,
                            "trend_slip_struct",
                            event="watch_trend_slip_detail",
                            code=code,
                            rk=rk,
                            section="watch_pack",
                            weak_pillars=tr.weak_pillars,
                            weak_dims=tr.weak_dims_by_pillar,
                            sector_data_incomplete=not tr.sector_eligible,
                            sector_data_warning=tr.sector_data_warning or "",
                            ml_bearish_prob=ml_prob,
                            ml_kline_decline_prob=k_p,
                            ml_external_flow_enabled=bool(
                                (cfg.get("ml_filter") or {}).get(
                                    "external_flow_features_enabled"
                                )
                            ),
                            ml_external_flow_snapshot=_ml_external_flow_snapshot(
                                cfg, ml_nb_feats
                            ),
                            # NB 模型 JSON 中 features 长度：开外部流时期望 11；仍为 6 表示未按当前配置重训的旧模型
                            ml_nb_full_dim=ml_nb_model_dim,
                            ml_nb_vector_dim=len(ml_nb_feats) if ml_nb_feats else 0,
                        )
                    except Exception:
                        pass
                if channel_cooldown_ok(state, trend_k, cooldown_min, now_ts) and (
                    not args.no_notify
                ):
                    trend_body = (
                        f"{tr.summary}\n明细：{'；'.join(tr.reasons[:10])}\n盈亏：{pnl:+.2f}%"
                    )
                    if not tr.sector_eligible:
                        trend_body += f"\n{pillar_degrade_msg}"
                    _try_log_watch_alert(
                        cfg,
                        pack,
                        alert_type="trend_slip",
                        rk=rk,
                        summary=tr.summary[:800],
                        extra={
                            "weak_pillars": tr.weak_pillars,
                            "pnl_pct": pnl,
                            "ml_bearish_prob": ml_prob,
                            "ml_kline_decline_prob": k_p,
                            "ml_suppress_combo": str(
                                (cfg.get("ml_filter") or {}).get("suppress_combo") or "any"
                            ),
                            "ml_external_flow_enabled": bool(
                                (cfg.get("ml_filter") or {}).get(
                                    "external_flow_features_enabled"
                                )
                            ),
                            "ml_external_flow_snapshot": _ml_external_flow_snapshot(
                                cfg, ml_nb_feats
                            ),
                            "ml_nb_full_dim": ml_nb_model_dim,
                            "ml_nb_vector_dim": len(ml_nb_feats) if ml_nb_feats else 0,
                        },
                    )
                    notif = cfg.get("notifications") or {}
                    if bool(notif.get("aggregate_trend_alerts")) and (
                        round_trend_digest is not None
                    ):
                        round_trend_digest.append(
                            {
                                "title": f"趋势下滑预警｜{disp_name}",
                                "body": trend_body,
                                "subtitle": f"{code} 成本 {cost:.3f}",
                            }
                        )
                    else:
                        send_notification(
                            f"趋势下滑预警｜{disp_name}",
                            trend_body,
                            f"{code} 成本 {cost:.3f}",
                            sound=True,
                            cfg=cfg,
                            severity="warning",
                        )
                    state[trend_k] = now_ts

        add_info = risk.check_add_order(now_price, cost) if cost > 0 else None
        if add_info:
            if not add_info.get("allow"):
                _emit_watch_line(
                    f"      └ 【补仓禁止】{add_info.get('msg','')}",
                    event="watch_add_forbid",
                    code=code,
                    rk=rk,
                )
            else:
                money = float(add_info["money"])
                after = risk.calc_after_add(cost, hold, now_price, money)
                ns = after["new_share"]
                add_lines = [
                    f"【{add_info['level']}】",
                    f"现价：{now_price:.3f} 元",
                    f"补仓前盈亏：{pnl:+.2f}%（亏损幅度参考上行）",
                    f"建议补仓金额：{money:.0f} 元",
                    f"按现价约合买入：{ns} 股",
                    f"补仓后摊薄成本：{after['new_avg_cost']:.3f} 元",
                    f"补仓后盈亏（相对摊薄成本）：{after['after_profit_pct']:+.2f}%",
                    f"现价涨至摊薄成本约需：{after['need_rise_pct']:.2f}%",
                ]
                if ns <= 0:
                    add_lines.append(
                        "（提示：补仓金额相对现价过小，整数股为 0，仅作测算）"
                    )
                add_text = "\n".join(add_lines)
                for ln in add_lines:
                    mag = style_add_console_line(ln)
                    _emit_watch_line(
                        f"         {mag}",
                        event="watch_add_order_line",
                        code=code,
                        rk=rk,
                    )

                add_k = f"add_{rk}"
                if channel_cooldown_ok(state, add_k, cooldown_min, now_ts) and (
                    not args.no_notify
                ):
                    send_notification(
                        f"补仓测算｜{disp_name}",
                        add_text,
                        subtitle=f"{code} ({disp_name})",
                        sound=True,
                        cfg=cfg,
                        severity="warning",
                    )
                    state[add_k] = now_ts

        fire, reason = should_alert(now_price, rule, buffer)
        if fire and breach_cooldown_ok(state, rk, cooldown_min, now_ts):
            body = f"现价 {now_price:.2f}，{reason}"
            note = rule.get("note")
            if note:
                body += f"（{note}）"
            _emit_watch_line(
                f"      └ 【区间提醒】{body}",
                event="watch_price_band",
                code=code,
                rk=rk,
            )
            _try_log_watch_alert(
                cfg,
                pack,
                alert_type="price_band",
                rk=rk,
                summary=body,
                extra={"reason": reason},
            )
            notif = cfg.get("notifications") or {}
            agg = bool(notif.get("aggregate_interval_alerts"))
            if not args.no_notify:
                if agg and round_notify_digest is not None:
                    round_notify_digest.append(
                        {
                            "title": f"{disp_name} 价格提醒",
                            "body": body,
                            "subtitle": f"{code} ({disp_name})",
                        }
                    )
                else:
                    send_notification(
                        f"{disp_name} 价格提醒",
                        body,
                        subtitle=f"{code} ({disp_name})",
                        sound=True,
                        cfg=cfg,
                        severity="info",
                    )
            if rk not in state or not isinstance(state.get(rk), dict):
                state[rk] = {}
            state[rk]["last_alert_ts"] = now_ts
            state[rk]["last_reason"] = reason

    return mv


def main() -> int:
    ap = argparse.ArgumentParser(description="股价监控｜风控｜策略｜区间提醒")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument(
        "--quiet-trading-check",
        action="store_true",
        help="不按交易日历拉长间隔（调试）",
    )
    ap.add_argument(
        "--scan",
        action="store_true",
        help="全市场分层重筛（默认最多每 3 天一跑，可用 --force-scan）",
    )
    ap.add_argument(
        "--force-scan",
        action="store_true",
        help="忽略上次扫描时间，立即执行全市场重筛（配合 --scan）",
    )
    ap.add_argument(
        "--poll-when-closed",
        action="store_true",
        help="非交易时段仍请求行情（默认休市不请求以省流量）",
    )
    ap.add_argument(
        "--daily-select",
        action="store_true",
        help="盘前全市场量化选股（分策略输出到 daily_picks.json）",
    )
    ap.add_argument(
        "--daily-auto",
        action="store_true",
        help="一键自动：先盘前选股筛选，再直接进入盘中监控",
    )
    ap.add_argument(
        "--skip-daily-select",
        action="store_true",
        help="启动时不跑自动盘前选股（沿用已有 daily_picks.json；选股源不可用时可用）",
    )
    ap.add_argument(
        "--no-sync-after-select",
        action="store_true",
        help="与 --daily-select / --daily-auto 合用：写出 daily_picks 后不自动跑 sync_daily_klines（改由单独命令同步）",
    )
    ap.add_argument(
        "--backtest-code",
        type=str,
        default=None,
        help="执行 1/3/5 年三策略回测，例如 --backtest-code 600711",
    )
    ap.add_argument(
        "--check-bk",
        action="store_true",
        help="打印 watchlist 的趋势板块 BK 解析结果（不写 state、不拉行情）",
    )
    ap.add_argument(
        "--dedupe-watchlist",
        action="store_true",
        help="合并 config.json 里 watchlist 的重复代码（六位归一）并保存后退出",
    )
    ap.add_argument(
        "--verify-config",
        action="store_true",
        help="载入并合并配置，做 Schema + 路径/邮件自检后退出（0=无致命问题）",
    )
    ap.add_argument(
        "--skip-startup-check",
        action="store_true",
        help="跳过启动路径/邮件等非 Schema 自检（不推荐）",
    )
    ap.add_argument(
        "--max-poll-rounds",
        type=int,
        default=0,
        help="完成「完整行情轮询」轮数后退出（0=不限制；用于本地测速）",
    )
    args = ap.parse_args()

    if args.check_bk:
        if not args.config.exists():
            _emit_cli_subcmd_line(
                f"缺少配置: {args.config}\n请复制 config.example.json 为 config.json",
                event="cli_config_missing",
            )
            return 1
        return _run_check_bk_mapping(args)

    if args.dedupe_watchlist:
        if not args.config.exists():
            _emit_cli_subcmd_line(
                f"缺少配置: {args.config}\n请复制 config.example.json 为 config.json",
                event="cli_config_missing",
            )
            return 1
        raw_cfg = json.loads(args.config.read_text(encoding="utf-8"))
        n = dedupe_watchlist_in_cfg(raw_cfg)
        if not save_config_atomic(args.config, raw_cfg):
            _emit_cli_subcmd_line(
                "[dedupe-watchlist] 写入 config 失败（请检查磁盘权限）",
                event="cli_dedupe_watchlist_file_failed",
            )
            return 1
        _emit_cli_subcmd_line(
            f"[dedupe-watchlist] 已合并重复标的，移除 {n} 条重复记录",
            event="cli_dedupe_watchlist_file_ok",
        )
        return 0

    if args.scan:
        from stock_scanner import scan_and_save

        return scan_and_save(args.config, force=bool(args.force_scan))

    if args.daily_select or args.daily_auto:
        rc = _run_auto_daily_select(args)
        if rc != 0:
            return rc
        if args.daily_auto:
            _emit_cli_subcmd_line(
                "[daily-auto] 已完成盘前自动筛选，开始进入盘中监控...",
                event="cli_daily_auto_into_monitor",
            )
        else:
            return 0

    if args.backtest_code and not args.daily_auto:
        _ensure_app_logging_from_config_path(args.config)
        from quant_core.backtest import run_backtest_pack

        report = run_backtest_pack(str(args.backtest_code).strip(), years_list=[1, 3, 5])
        out_path = args.config.parent / "backtest_report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _emit_cli_subcmd_line(
            f"[完成] 回测报告已输出: {out_path}",
            event="cli_backtest_done",
        )
        return 0

    if args.test_notify:
        _ensure_app_logging_from_config_path(args.config)
        send_notification(
            "量化提醒测试",
            "Mac 通知与音效链路正常",
            subtitle="stock-price-alert",
            sound=True,
            skip_disclaimer=True,
        )
        _emit_cli_subcmd_line(
            "[测试] 已请求发送通知",
            event="cli_test_notify_sent",
        )
        return 0

    if not args.config.exists():
        _emit_cli_subcmd_line(
            f"缺少配置: {args.config}\n请复制 config.example.json 为 config.json",
            event="cli_config_missing",
        )
        return 1

    cfg = merge_full_config(
        json.loads(args.config.read_text(encoding="utf-8"))
    )

    if not args.verify_config:
        _backup_user_config_file(args.config)

    from config_startup_check import format_startup_report, run_startup_config_checks

    if args.verify_config:
        errs, warns = run_startup_config_checks(cfg, root=ROOT)
        print(format_startup_report(errs, warns))
        return 1 if errs else 0

    if not args.skip_startup_check:
        errs2, warns2 = run_startup_config_checks(cfg, root=ROOT)
        if errs2 or warns2:
            print(format_startup_report(errs2, warns2), file=sys.stderr)
        if errs2:
            return 1

    # 默认主命令：按配置决定是否在进入监控前执行盘前选股（watchlist_only 等会跳过）
    would_startup_daily = not any(
        (
            args.scan,
            args.daily_select,
            args.daily_auto,
            bool(args.backtest_code),
            args.test_notify,
            args.once,
            args.check_bk,
            args.dedupe_watchlist,
        )
    )
    run_startup_daily = would_startup_daily and _should_run_startup_daily_select(
        cfg, args
    )
    if run_startup_daily:
        _ensure_app_logging_from_config_path(args.config)
        _emit_cli_subcmd_line(
            "[主流程] 自动执行盘前选股+回测筛选...",
            event="cli_auto_daily_flow",
        )
        rc = _run_auto_daily_select(args)
        if rc != 0:
            return rc
    elif would_startup_daily:
        _emit_cli_subcmd_line(
            "[主流程] 按配置跳过启动盘前选股，直接进入监控"
            "（watchlist_only / skip_startup_daily_select / --skip-daily-select）",
            event="cli_startup_daily_select_skipped",
        )

    from app_logging import setup_app_logging

    setup_app_logging(cfg, root=ROOT)
    risk = RiskManager(cfg)
    perf0 = cfg.get("performance") or {}
    configure_kline_performance(
        float(perf0["kline_cache_ttl_sec"]),
        float(perf0["sector_kline_cache_ttl_sec"]),
    )
    configure_index_kline_cache(float(perf0.get("index_kline_cache_ttl_sec", 60)))
    configure_kline_store_from_cfg(cfg, root=ROOT)
    configure_quote_live_from_cfg(cfg)
    from utils import configure_ssl_from_sources

    configure_ssl_from_sources(cfg.get("sources"))
    from utils import configure_request_pacing

    configure_request_pacing(
        float(perf0.get("request_min_interval_sec", 0) or 0)
    )
    from utils import configure_http_domain_token_bucket, configure_safe_get_jitter

    configure_safe_get_jitter(
        float(perf0.get("safe_get_jitter_sec_min", 0.25) or 0),
        float(perf0.get("safe_get_jitter_sec_max", 1.2) or 0),
    )
    _bh = perf0.get("http_domain_bucket_hosts")
    if not isinstance(_bh, list):
        _bh = None
    configure_http_domain_token_bucket(
        float(perf0.get("http_domain_bucket_rps", 0) or 0),
        [str(x).strip() for x in _bh if str(x).strip()] if _bh else None,
    )

    raw_iv = (
        args.interval
        if args.interval is not None
        else int(cfg.get("poll_interval_seconds", DEFAULT_POLL))
    )
    base_interval = max(MIN_INTERVAL, raw_iv)
    closed_iv = max(MIN_INTERVAL, int(cfg.get("trading_closed_interval", DEFAULT_CLOSED_INTERVAL)))
    cooldown_min = float(cfg.get("alert_cooldown_minutes", DEFAULT_COOLDOWN_MIN))
    buffer = float(cfg.get("alert_price_buffer", DEFAULT_BUFFER))
    ut = resolve_ut((cfg.get("sources") or {}).get("eastmoney_ut") or DEFAULT_UT)

    force_include_codes: set[str] = set()
    force_exclude_codes: set[str] = set()
    st_path = state_path(args.config)
    state = load_state(st_path)
    hydrate_runtime_watch_sets(force_include_codes, force_exclude_codes, state)
    read_cmds = sys.stdin.isatty() and not args.once
    if not read_cmds and not args.once and not sys.stdin.isatty():
        _emit_cli_subcmd_line(
            "[提示] stdin 非交互终端，运行时命令（hold/showhold 等）已禁用。",
            event="cli_stdin_not_tty",
        )
    cmd_queue = _start_command_listener(read_stdin_commands=read_cmds)

    watch, watch_mode = _build_watch_from_daily_picks_with_overrides(
        cfg,
        args.config,
        force_include_codes=force_include_codes,
        force_exclude_codes=force_exclude_codes,
    )
    log_dir = args.config.parent

    hub = None
    if not watch:
        _emit_cli_subcmd_line(
            "[提示] watchlist 为空或无 enabled 标的；进程仍保留，用于收盘自动化（ops_automation）"
            "与邮件指令轮询。\n"
            "  有标的后将开始行情轮询；选股可执行：python run_alert.py --scan",
            event="cli_watch_empty_hint",
        )
    else:
        hub = hub_from_cfg(cfg, ut=str(ut))
        if hub is not None:
            hub.set_watch_rules(watch)
            hub.start()

    run_only = cfg.get("run_only_in_trading_hours", True) and not args.poll_when_closed

    if watch:
        _emit_cli_subcmd_line(
            f"[启动] 标的 {len(watch)} | 盘中轮询 {base_interval}s | 非交易 {closed_iv}s | "
            f"冷却 {cooldown_min:g}min | 限价防抖 ±{buffer} 元 | "
            f"本金参照 {cfg['capital']['total']:.0f} 元"
            + (" | 仅交易时段请求行情" if run_only else " | 休市亦请求行情"),
            event="cli_monitor_startup_banner",
        )
        if watch_mode == "quality_only":
            _emit_cli_subcmd_line(
                "[AI筛选] 盘中仅监控 daily_picks.json 的优质股（含持仓标签保留）；"
                "列表顺序每轮随机",
                event="cli_watch_mode_quality_only",
            )
        elif watch_mode == "watchlist_only":
            _emit_cli_subcmd_line(
                "[监控] 已开启 watchlist_only：仅轮询 config.json 的 watchlist（不合并 daily_picks 优质股全表）",
                event="cli_watch_mode_watchlist_only",
            )
        elif watch_mode == "fallback_all":
            _emit_cli_subcmd_line(
                "[AI筛选] 未检测到优质股清单，回退监控全部 watchlist",
                event="cli_watch_mode_fallback_all",
            )
        _emit_cli_subcmd_line(
            "[命令] hold <代码> <股数> <成本> | hold <代码> | unhold | showhold | dedupewatchlist | sell",
            event="cli_runtime_commands_hint",
        )
    else:
        oa0 = cfg.get("ops_automation") or {}
        _emit_cli_subcmd_line(
            f"[启动] 监控池为空｜保留 ops_automation="
            f"{bool(oa0.get('enabled', False))}（收盘后回测+调参）｜"
            f"轮询间隔约 {max(5, min(base_interval, 30))}s 直至有标的",
            event="cli_monitor_idle_ops_banner",
        )

    first_round = True
    last_empty_watch_log_mono = 0.0
    poll_rounds_done = 0

    try:
        while True:
            while True:
                try:
                    line = cmd_queue.get_nowait()
                except queue.Empty:
                    break
                _handle_runtime_command(
                    line,
                    cfg=cfg,
                    config_path=args.config,
                    force_include_codes=force_include_codes,
                    force_exclude_codes=force_exclude_codes,
                )
            watch, watch_mode = _build_watch_from_daily_picks_with_overrides(
                cfg,
                args.config,
                force_include_codes=force_include_codes,
                force_exclude_codes=force_exclude_codes,
            )
            _maybe_run_ops_automation(
                cfg=cfg,
                state=state,
                config_path=args.config,
            )
            _maybe_poll_email_commands(
                cfg=cfg,
                state=state,
                config_path=args.config,
                force_include_codes=force_include_codes,
                force_exclude_codes=force_exclude_codes,
            )

            if not watch:
                now_m = time.monotonic()
                if (
                    last_empty_watch_log_mono == 0.0
                    or now_m - last_empty_watch_log_mono >= EMPTY_WATCH_STATUS_LOG_SEC
                ):
                    _emit_cli_subcmd_line(
                        "[监控池] 当前为空，等待新命令或下一轮筛选（仍已执行收盘自动化/邮件轮询）…",
                        event="cli_watch_pool_empty_wait",
                    )
                    last_empty_watch_log_mono = now_m
                state["__force_include__"] = sorted(force_include_codes)
                state["__force_exclude__"] = sorted(force_exclude_codes)
                save_state(st_path, state)
                time.sleep(max(5, min(base_interval, 30)))
                if args.once:
                    break
                continue

            last_empty_watch_log_mono = 0.0

            if hub is None:
                hub = hub_from_cfg(cfg, ut=str(ut))
                if hub is not None:
                    hub.set_watch_rules(watch)
                    hub.start()
            elif hub is not None:
                hub.set_watch_rules(watch)

            if run_only and not is_trading_session():
                _emit_main_line(
                    f"\n[休市] 已开启仅交易时段轮询，{closed_iv}s 后重试… "
                    f"（需要休市也跑请加 --poll-when-closed）",
                    event="poll_market_closed",
                )
                time.sleep(closed_iv + random.uniform(0.15, 1.1))
                if args.once:
                    break
                continue

            if not first_round:
                time.sleep(base_interval + random.uniform(0.15, 1.1))
            first_round = False

            ts_line = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            round_mono = time.monotonic()
            _emit_main_line(
                f"\n===== 轮询 {ts_line} | 盘中: {is_trading_session()} =====",
                event="poll_round_start",
            )

            fails = 0
            attempted = 0
            total_mv = 0.0
            now_ts = time.time()
            _tseg = time.monotonic()
            seg_ms: dict[str, float] = {}
            index_mult = fetch_index_mood_mult()
            index_5d_ret = fetch_index_5d_return()
            seg_ms["index_mood_ms"] = round(
                (time.monotonic() - _tseg) * 1000.0, 2
            )

            sector_clear_round_cache()
            round_bk_kline: dict[str, dict[str, Any]] = {}
            bk_cache_stats: dict[str, int] = {"bk_kline_fetch": 0, "bk_kline_hit": 0}
            perf = cfg.get("performance") or {}
            _am_chk = perf.get("async_minute_kline") if isinstance(perf, dict) else None
            if isinstance(_am_chk, dict) and bool(_am_chk.get("enabled", False)):
                from async_minute_kline import (
                    ensure_async_minute_kline_worker,
                    update_async_minute_kline_context,
                )

                ensure_async_minute_kline_worker()
                update_async_minute_kline_context(watch, cfg)
            parallel_on = bool(perf.get("enable_parallel_fetch", True))
            max_w = max(1, min(16, int(perf.get("fetch_max_workers", 4))))
            sem_n = max(1, min(max_w, int(perf.get("fetch_max_concurrency", 3))))
            fetch_sem = threading.Semaphore(sem_n)
            bk_round_lock = threading.Lock()
            print_lock = threading.Lock()
            round_notify_digest: list[dict[str, Any]] = []
            round_trend_digest: list[dict[str, Any]] = []
            notif0 = cfg.get("notifications") or {}
            use_digest = bool(notif0.get("aggregate_interval_alerts"))
            use_trend_digest = bool(notif0.get("aggregate_trend_alerts"))

            _hq0 = time.monotonic()
            if parallel_on and len(watch) > 1:
                _emit_main_line(
                    f"[性能] 并行拉取 workers={max_w} 并发信号量={sem_n}",
                    event="poll_parallel_hint",
                )

            if hub is not None:
                hub.set_watch_rules(watch)
                perf_hub = cfg.get("performance") or {}
                wt = float(perf_hub.get("hub_warm_timeout_sec", 12.0) or 12.0)
                frac = float(perf_hub.get("hub_warm_min_fraction", 0.85) or 0.85)
                ok_h, n_h = hub.wait_for_quote_coverage(
                    timeout_sec=max(1.0, wt), min_fraction=frac
                )
                if n_h > 0 and ok_h < max(1, int(frac * n_h)):
                    _emit_main_line(
                        f"[Hub] 缓存预热 {ok_h}/{n_h}（目标≥{frac:.0%}，超时 {wt:g}s），"
                        f"未命中标的将直连行情源",
                        event="poll_hub_warm_partial",
                    )

            prefetched_quotes: dict[tuple[str, str], dict[str, Any]] = {}
            try:
                bulk_items: list[tuple[str, str]] = []
                for r0 in watch:
                    code0 = str(r0.get("code") or "").strip()
                    market0 = str(r0.get("market") or "sh").strip().lower()
                    if valid_code(code0):
                        bulk_items.append((code0, market0))
                if bulk_items:
                    prefetched_quotes = fetch_quote_metrics_bulk(
                        bulk_items, timeout=12.0, ut=str(ut)
                    )
                    if prefetched_quotes:
                        _emit_main_line(
                            f"[性能] 批量现价预取命中 {len(prefetched_quotes)}/{len(bulk_items)}",
                            event="poll_quote_bulk_prefetch",
                        )
            except Exception as e:
                _emit_main_line(
                    f"[性能] 批量现价预取失败，回退单票: {e}",
                    event="poll_quote_bulk_prefetch_fail",
                    level=logging.WARNING,
                )

            seg_ms["hub_quote_bulk_ms"] = round(
                (time.monotonic() - _hq0) * 1000.0, 2
            )
            _fp0 = time.monotonic()

            m_cap = int(perf.get("minute_kline_max_per_round", 0) or 0)
            minute_budget_box: list[int] | None = None
            minute_budget_lock = threading.Lock()
            if bool(perf.get("fetch_minute_kline_today", False)) and m_cap > 0:
                minute_budget_box = [m_cap]

            def _one(idx: int, rule: dict[str, Any]) -> dict[str, Any]:
                _t_item = time.monotonic()
                out = _fetch_watch_item_pack(
                    rule=rule,
                    cfg=cfg,
                    ut=str(ut),
                    index_mult=index_mult,
                    index_5d_ret=index_5d_ret,
                    force_include_codes=force_include_codes,
                    round_bk_kline=round_bk_kline,
                    bk_round_lock=bk_round_lock,
                    fetch_sem=fetch_sem,
                    watch_idx=idx,
                    print_lock=print_lock,
                    hub=hub,
                    prefetched_quotes=prefetched_quotes,
                    bk_cache_stats=bk_cache_stats,
                    minute_budget_box=minute_budget_box,
                    minute_budget_lock=minute_budget_lock,
                )
                wall_ms = round((time.monotonic() - _t_item) * 1000.0, 2)
                if isinstance(out, dict):
                    return {
                        **out,
                        "fetch_wall_ms": wall_ms,
                        "watch_code": str(rule.get("code") or "").strip(),
                    }
                return out

            raw_pack: list[dict[str, Any]] = []
            if parallel_on and len(watch) > 1:
                with ThreadPoolExecutor(max_workers=max_w) as ex:
                    futures = [ex.submit(_one, i, r) for i, r in enumerate(watch)]
                    for fu in as_completed(futures):
                        raw_pack.append(fu.result())
            else:
                for i, r in enumerate(watch):
                    raw_pack.append(_one(i, r))

            raw_pack.sort(key=lambda x: int(x.get("idx", 0)))
            items: list[dict[str, Any]] = []
            for res in raw_pack:
                if res.get("kind") == "invalid":
                    continue
                if res.get("kind") == "fail":
                    fails += 1
                    attempted += 1
                    continue
                if res.get("kind") == "ok":
                    attempted += 1
                    items.append(res["pack"])

            seg_ms["fetch_packs_ms"] = round(
                (time.monotonic() - _fp0) * 1000.0, 2
            )
            if bool(perf.get("log_poll_segment_ms", False)) and raw_pack:
                _pw_rows: list[tuple[str, float, str]] = []
                for _r in raw_pack:
                    _wc = str(_r.get("watch_code") or "").strip() or "?"
                    _wms = float(_r.get("fetch_wall_ms") or 0.0)
                    _wk = str(_r.get("kind") or "")
                    _pw_rows.append((_wc, _wms, _wk))
                _pw_rows.sort(key=lambda x: -x[1])
                _top_n = 24
                _head = _pw_rows[:_top_n]
                _tail = ""
                if len(_pw_rows) > _top_n:
                    _tail = f" …(共{len(_pw_rows)}只)"
                _parts: list[str] = []
                for _c, _ms, _k in _head:
                    _lab = f"{_c}={_ms:.0f}ms"
                    if _k != "ok":
                        _lab += f"[{_k}]"
                    _parts.append(_lab)
                _emit_main_line(
                    "[单票拉取耗时 慢→快] " + " ".join(_parts) + _tail,
                    event="poll_per_watch_fetch_ms",
                )
            _en0 = time.monotonic()

            dyn_mp, dyn_msg = _compute_round_dynamic_min_pillars_weak(cfg)
            if dyn_msg:
                _emit_main_line(dyn_msg, event="poll_dynamic_regime")
            if dyn_mp is not None:
                for _p in items:
                    _p["_dynamic_min_pillars_weak"] = dyn_mp

            _mood_tier = _market_mood_tier_for_position_suggestion(cfg)
            for _p in items:
                _p["_market_mood_tier"] = _mood_tier

            sbf0 = cfg.get("strategy_buy_filter") or {}
            round_buy_mood: str | None = None
            if bool(sbf0.get("enabled", True)) and bool(
                sbf0.get("block_weak_bear", True)
            ):
                da0 = (cfg.get("trend_slippage_alert") or {}).get("dynamic_adaptive")
                round_buy_mood = get_market_mood_three_tier(
                    dynamic_cfg=da0 if isinstance(da0, dict) else {}
                )
            for _p in items:
                _p["_strategy_buy_mood_tier"] = round_buy_mood

            tier_for_sbf = (
                round_buy_mood if round_buy_mood is not None else _mood_tier
            )
            cfg["_runtime_mood_tier_for_buy_filter"] = tier_for_sbf
            cfg["_runtime_effective_strategy_buy_filter"] = (
                resolve_effective_strategy_buy_filter(cfg)
            )

            full_outage = attempted > 0 and fails >= attempted
            dh_cfg = cfg.get("data_health") or {}
            if full_outage:
                from app_logging import record_alert_event
                from data_health import degraded_hosts

                msg = (
                    "[DATA_OUTAGE] 本轮监控标的全部拉取失败；K 线/合成类信号不可用，"
                    "请检查网络、东方财富与备用行情源，以及 sources.ssl_verify / ssl_ca_bundle。"
                )
                bad = degraded_hosts()
                if bad:
                    msg += "\n  近期 HTTP 主机连续失败（data_health）：" + "; ".join(
                        f"{h}×{n}" for h, n in bad[:16]
                    )
                print(msg)
                record_alert_event(
                    logging.WARNING,
                    msg.replace("\n", " | "),
                    event="data_outage",
                    fails=fails,
                    attempted=attempted,
                    degraded_hosts=[
                        {"host": h, "fails": n} for h, n in bad[:16]
                    ],
                )
                apply_poll_outage_state_mutations(
                    state, full_outage=True, dh_cfg=dh_cfg
                )
                streak = int(state.get("__full_outage_streak__") or 0)
                thr = int(dh_cfg.get("full_outage_consecutive_notify_threshold") or 0)
                if thr > 0 and streak >= thr and not state.get(
                    "__full_outage_escalated_sent__"
                ):
                    esc = (
                        f"已连续 {streak} 轮「监控标的全部拉取失败」。"
                        "请检查网络与行情源（含 SSL 配置）。"
                    )
                    if bad:
                        esc += " 主机摘要：" + "; ".join(
                            f"{h}×{n}" for h, n in bad[:8]
                        )
                    if not args.no_notify:
                        send_notification(
                            "数据源连续不可用",
                            esc,
                            subtitle="data_health",
                            sound=True,
                            cfg=cfg,
                            severity="critical",
                        )
                    if bool(dh_cfg.get("full_outage_email_enabled")):
                        send_email_alert(
                            "[股价监控] 数据源连续不可用",
                            esc,
                            app_cfg=cfg,
                        )
                    state["__full_outage_escalated_sent__"] = True
            else:
                old_streak = apply_poll_outage_state_mutations(
                    state, full_outage=False, dh_cfg=dh_cfg
                )
                thr_r = int(dh_cfg.get("full_outage_consecutive_notify_threshold") or 0)
                if (
                    old_streak >= thr_r > 0
                    and bool(dh_cfg.get("recovery_notify_enabled", True))
                ):
                    rec = (
                        "监控拉取已恢复（此前曾出现连续全失败轮次）。"
                        "请留意 K 线与合成信号是否仍异常。"
                    )
                    if not args.no_notify:
                        send_notification(
                            "数据源已恢复",
                            rec,
                            subtitle="data_health",
                            sound=True,
                            cfg=cfg,
                            severity="info",
                        )
                    if bool(dh_cfg.get("full_outage_email_enabled")):
                        send_email_alert(
                            "[股价监控] 数据源已恢复",
                            rec,
                            app_cfg=cfg,
                        )

            seg_ms["pack_enrich_ms"] = round(
                (time.monotonic() - _en0) * 1000.0, 2
            )
            _pw0 = time.monotonic()

            tagged_items = [x for x in items if x["tagged"]]
            untagged_items = [x for x in items if not x["tagged"]]
            untagged_items.sort(key=lambda x: x["sort_score"], reverse=True)
            pick_n = max(1, int(cfg.get("daily_pick_count", 6)))
            top_picks = untagged_items[:pick_n]
            rest_items = untagged_items[pick_n:]

            sections: list[tuple[str, list[dict[str, Any]], bool]] = []
            if tagged_items:
                sections.append(("【我的持仓】", tagged_items, False))
            if top_picks:
                sections.append((f"【今日{pick_n}只低吸优选】", top_picks, True))
            if rest_items:
                sections.append(("【其余监控标的】", rest_items, False))

            _codes_for_names: list[str] = []
            _seen_n: set[str] = set()
            for _pack in items:
                _q = _pack.get("q") or {}
                _ru = _pack.get("rule") or {}
                _c0 = normalize_stock_code(
                    str(_q.get("code") or _ru.get("code") or "")
                )
                if _c0 and _c0 not in _seen_n:
                    _seen_n.add(_c0)
                    _codes_for_names.append(_c0)
            _npw = max(1, min(8, int(perf.get("name_prewarm_max_workers", 4) or 4)))
            if len(_codes_for_names) > 1 and _npw > 1:

                def _pre_name(c: str) -> None:
                    get_stock_name(c)

                with ThreadPoolExecutor(max_workers=_npw) as _exn:
                    _exn.map(_pre_name, _codes_for_names)
            else:
                for _c in _codes_for_names:
                    get_stock_name(_c)

            _pw_workers = max(
                1, min(8, int(perf.get("process_watch_max_workers", 1) or 1))
            )
            _pw_lock = threading.RLock() if _pw_workers > 1 else None

            def _buy_mail_bucket_from_sec(sec: str) -> str:
                if "我的持仓" in sec:
                    return "持仓"
                if "低吸优选" in sec:
                    return "优选"
                if "其余监控" in sec:
                    return "其余"
                return "监控"

            for sec_title, group, show_pick in sections:
                _emit_main_line(
                    f"\n---------- {sec_title} ----------",
                    event="poll_section_header",
                )
                _mail_bkt = _buy_mail_bucket_from_sec(sec_title)
                if _pw_workers > 1:

                    def _one_pw(
                        pack: dict[str, Any],
                        *,
                        bkt: str = _mail_bkt,
                    ) -> float:
                        return process_watch_pack(
                            pack,
                            risk=risk,
                            state=state,
                            cfg=cfg,
                            args=args,
                            buffer=buffer,
                            cooldown_min=cooldown_min,
                            now_ts=now_ts,
                            log_dir=log_dir,
                            show_pick_card=show_pick,
                            round_notify_digest=round_notify_digest
                            if use_digest
                            else None,
                            round_trend_digest=round_trend_digest
                            if use_trend_digest
                            else None,
                            state_mut_lock=_pw_lock,
                            buy_mail_bucket=bkt,
                        )

                    with ThreadPoolExecutor(max_workers=_pw_workers) as _expw:
                        _futs = [_expw.submit(_one_pw, p) for p in group]
                        for _fu in _futs:
                            total_mv += _fu.result()
                else:
                    for pack in group:
                        total_mv += process_watch_pack(
                            pack,
                            risk=risk,
                            state=state,
                            cfg=cfg,
                            args=args,
                            buffer=buffer,
                            cooldown_min=cooldown_min,
                            now_ts=now_ts,
                            log_dir=log_dir,
                            show_pick_card=show_pick,
                            round_notify_digest=round_notify_digest
                            if use_digest
                            else None,
                            round_trend_digest=round_trend_digest
                            if use_trend_digest
                            else None,
                            state_mut_lock=None,
                            buy_mail_bucket=_mail_bkt,
                        )

            seg_ms["process_watch_ms"] = round(
                (time.monotonic() - _pw0) * 1000.0, 2
            )
            _nf0 = time.monotonic()

            if use_digest and round_notify_digest and not args.no_notify:
                _flush_round_notification_merge(
                    round_notify_digest,
                    title="本轮价格区间摘要",
                    subtitle=f"共 {len(round_notify_digest)} 条",
                    cfg=cfg,
                    args=args,
                    max_items=int(notif0.get("aggregate_max_items") or 20),
                    severity="info",
                )
            if use_trend_digest and round_trend_digest and not args.no_notify:
                _flush_round_notification_merge(
                    round_trend_digest,
                    title="本轮趋势下滑预警摘要",
                    subtitle=f"共 {len(round_trend_digest)} 条",
                    cfg=cfg,
                    args=args,
                    max_items=int(notif0.get("aggregate_trend_max_items") or 15),
                    severity="warning",
                )

            seg_ms["notify_flush_ms"] = round(
                (time.monotonic() - _nf0) * 1000.0, 2
            )

            _round_dur_ms = (time.monotonic() - round_mono) * 1000.0
            try:
                from app_logging import record_alert_event

                record_alert_event(
                    logging.INFO,
                    f"poll_round_done ts={ts_line}",
                    event="poll_round_done",
                    section="main_loop",
                    duration_ms=_round_dur_ms,
                )
            except Exception:
                pass
            _emit_main_line(
                f"[轮询完成] 耗时 {_round_dur_ms / 1000.0:.2f}s",
                event="poll_round_done_console",
                duration_ms=_round_dur_ms,
            )

            if bool(perf.get("log_poll_segment_ms", False)):
                try:
                    from app_logging import record_alert_event

                    _line = (
                        f"[分段 ms] idx={seg_ms.get('index_mood_ms')} "
                        f"hub+q={seg_ms.get('hub_quote_bulk_ms')} "
                        f"packs={seg_ms.get('fetch_packs_ms')} "
                        f"enrich={seg_ms.get('pack_enrich_ms')} "
                        f"proc={seg_ms.get('process_watch_ms')} "
                        f"notify={seg_ms.get('notify_flush_ms')} "
                        f"bk_fetch={bk_cache_stats.get('bk_kline_fetch', 0)} "
                        f"bk_hit={bk_cache_stats.get('bk_kline_hit', 0)}"
                    )
                    _emit_main_line(_line, event="poll_segment_console")
                    record_alert_event(
                        logging.INFO,
                        f"poll_round_timing ts={ts_line}",
                        event="poll_round_timing",
                        section="main_loop",
                        duration_ms=_round_dur_ms,
                        metrics={
                            "seg_ms": seg_ms,
                            "bk_kline_fetch": int(
                                bk_cache_stats.get("bk_kline_fetch", 0)
                            ),
                            "bk_kline_hit": int(bk_cache_stats.get("bk_kline_hit", 0)),
                        },
                    )
                except Exception:
                    pass

            cfg.pop("_runtime_effective_strategy_buy_filter", None)
            cfg.pop("_runtime_mood_tier_for_buy_filter", None)

            poll_rounds_done += 1
            if int(getattr(args, "max_poll_rounds", 0) or 0) > 0:
                if poll_rounds_done >= int(args.max_poll_rounds):
                    break

            state["__force_include__"] = sorted(force_include_codes)
            state["__force_exclude__"] = sorted(force_exclude_codes)
            save_state(st_path, state)

            from data_health import maybe_write_data_heartbeat

            maybe_write_data_heartbeat(
                root=ROOT,
                watch_count=len(watch),
                attempted=int(attempted),
                fails=int(fails),
                trading_session=is_trading_session(),
            )

            if attempted > 0 and fails * 10 >= attempted * 7:
                fuse_msg = (
                    f"[熔断] 本轮失败过多 ({fails}/{attempted})，额外等待 {FUSE_MIN_INTERVAL}s"
                )
                print(fuse_msg)
                try:
                    from app_logging import record_alert_event

                    record_alert_event(
                        logging.WARNING,
                        fuse_msg,
                        event="fetch_fuse",
                        fails=fails,
                        attempted=attempted,
                    )
                except Exception:
                    pass
                time.sleep(FUSE_MIN_INTERVAL)

            tot_w = risk.check_total_position_value(total_mv)
            if tot_w:
                _emit_main_line(f"\n【总仓位】{tot_w}", event="poll_total_position")

            if args.once:
                break

    except KeyboardInterrupt:
        try:
            from app_logging import record_alert_event

            record_alert_event(
                logging.INFO,
                "keyboard_interrupt",
                event="shutdown",
            )
        except Exception:
            pass
        _emit_main_line("\n[退出] 已停止", event="shutdown_console")
    finally:
        if hub is not None:
            hub.stop()
        try:
            from async_minute_kline import stop_async_minute_kline_worker

            stop_async_minute_kline_worker()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())