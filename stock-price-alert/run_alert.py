#!/usr/bin/env python3
"""
沪深 A 股监控：现价 / 区间提醒 + 1W 风控（补仓摊薄、止盈止损）+
均线箱体策略 + 控制台 & 系统通知双通道。
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import random
import sys
import threading
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macro_risk import fetch_index_mood_mult, macro_score_multiplier
from email_notify import send_buy_signal_email, send_sell_signal_email
from notify_macos import notify, send_notification
from pick_score import composite_pick_score
from position_tags import format_tags_line, has_position_tag
from quote_eastmoney import DEFAULT_UT, fetch_price, fetch_quote_metrics, get_stock_kline_data, resolve_ut
from risk_control import RiskManager
from strategy_engine import ma_box_strategy
from trade_log import log_signal
from quant_core.backtest import run_backtest_pack
from quant_core.selector import run_daily_selector, save_daily_selector_result

# ---------------- 股票名称：本地主表 + 小缓存 + 单次接口补充 ----------------
# 主数据：a_share_names.json（python build_a_share_name_table.py 生成/更新，全市场代码→简称）
# 补充：stock_name_cache.json（接口曾成功写过的简称，退市等可能仅存于此）
CACHE_FILE = ROOT / "stock_name_cache.json"
A_SHARE_NAMES_FILE = ROOT / "a_share_names.json"
_a_share_static: dict[str, str] | None = None

stock_name_cache: dict[str, str] = {}
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
    raw = str(code).strip()
    if not raw:
        return raw
    c6 = _normalized_code6(raw)

    static = _load_a_share_static_names()
    if c6 and len(c6) == 6 and c6.isdigit() and c6 in static and static[c6]:
        return static[c6]

    for k in (c6, raw):
        if k in stock_name_cache:
            cv = stock_name_cache[k]
            if cv and str(cv).strip() != str(k).strip():
                return str(cv).strip()

    c = c6 if (c6 and len(c6) == 6 and c6.isdigit()) else raw

    try:
        import akshare as ak

        info = ak.stock_individual_info_em(symbol=c)
        name = str(info.loc[info["item"] == "股票简称", "value"].values[0])
        stock_name_cache[c6 if c6 else c] = name
        save_stock_name_cache()
        time.sleep(0.1)
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

DEFAULT_CAPITAL = {
    "total": 10000,
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
    sr = dict(DEFAULT_SCAN_RULE)
    sr.update(cfg.get("scan_rule") or {})
    cfg["scan_rule"] = sr
    cfg.setdefault("run_only_in_trading_hours", True)
    cfg.setdefault("scan_pool_max", 800)
    cfg.setdefault("daily_pick_count", 6)
    cfg.setdefault("macro_risk", {})
    cfg.setdefault("scan_meta", {})
    return cfg


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
        c = str(row.get("code") or "").strip()
        if valid_code(c):
            out.add(c)
    return out


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
    by_c = {
        str(w.get("code") or "").strip(): w
        for w in base_watch
        if isinstance(w, dict)
        and w.get("enabled", True)
        and valid_code(str(w.get("code") or "").strip())
    }
    out: list[dict[str, Any]] = []
    for w in base_watch:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        c = str(w.get("code") or "").strip()
        if c in force_exclude_codes and c not in force_include_codes:
            continue
        out.append(dict(w))
    for c in sorted(force_include_codes):
        if c in force_exclude_codes or not valid_code(c):
            continue
        if any(str(x.get("code") or "").strip() == c for x in out):
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
    return out


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

    by_code = {str(w.get("code") or "").strip(): dict(w) for w in base_watch}
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
        out.append(ent)

    # 强制加入 hold 的标的（即使不在优质池）
    for c in sorted(force_include_codes):
        if c in force_exclude_codes:
            continue
        if not valid_code(c):
            continue
        if any(str(x.get("code") or "").strip() == c for x in out):
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
        c = str(w.get("code") or "").strip()
        if c in force_exclude_codes and c not in force_include_codes:
            continue
        if has_position_tag(w) and c and c not in qcodes:
            out.append(dict(w))
    return out, "quality_only"


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


def _upsert_hold_in_cfg(
    cfg: dict[str, Any],
    *,
    code: str,
    hold_shares: int,
    cost_price: float,
    config_path: Path,
) -> bool:
    wl = cfg.get("watchlist")
    if not isinstance(wl, list):
        cfg["watchlist"] = []
        wl = cfg["watchlist"]
    name = get_stock_name(code)
    market = _infer_market(code)
    indices = _watchlist_indices_for_code(wl, code)
    patch = {
        "enabled": True,
        "code": code,
        "name": name,
        "market": market,
        "hold_shares": int(hold_shares),
        "cost_price": float(cost_price),
        "tags": "持仓",
        "alert_mode": "breach",
        "alert_below": None,
        "alert_above": None,
        "note": "终端 hold",
        "industry": "",
    }
    if indices:
        i0 = indices[0]
        old = wl[i0]
        if isinstance(old, dict):
            merged = dict(old)
            merged.update(patch)
            merged["name"] = str(old.get("name") or name)
            merged["industry"] = str(old.get("industry") or "")
            if old.get("note"):
                merged["note"] = str(old.get("note"))
            if old.get("tags"):
                merged["tags"] = str(old.get("tags"))
            wl[i0] = merged
        else:
            wl[i0] = patch
        for j in reversed(indices[1:]):
            wl.pop(j)
    else:
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
        print("[showhold] watchlist 为空或格式异常")
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
    print("")
    print("---------- 当前持仓（config.json watchlist）----------")
    if not rows:
        print("  （无：股数与成本均为 0 的条目已过滤）")
    else:
        print(f"  {'代码':<8}  {'简称':<12}  {'股数':>8}  {'成本':>10}  备注")
        print("  " + "-" * 56)
        for code, name, hs, cp, note in sorted(rows, key=lambda x: x[0]):
            print(f"  {code:<8}  {name[:12]:<12}  {hs:>8}  {cp:>10.4f}  {note}")
    print(f"  共 {len(rows)} 条")
    print("------------------------------------------------------")
    print("")


def _start_command_listener() -> queue.Queue[str]:
    q: queue.Queue[str] = queue.Queue()

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

    if cmd == "unhold" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            print(f"[unhold] 代码无效：{parts[1]!r}")
            return
        n = _remove_hold_from_cfg(cfg, code=code, config_path=config_path)
        force_include_codes.discard(code)
        force_exclude_codes.discard(code)
        if n:
            print(
                f"[unhold] 已从 config 删除 {code}（{get_stock_name(code)}），共移除 {n} 条"
            )
        else:
            print(f"[unhold] config 中未找到 {code}")
        return

    if cmd == "hold" and len(parts) == 4:
        code = normalize_stock_code(parts[1])
        if code is None:
            print(f"[hold] 代码无效：{parts[1]!r}")
            return
        try:
            shares = int(parts[2])
            cost = float(parts[3])
        except ValueError:
            print("[hold] 股数须为整数，成本须为数字，例：hold 000537 3000 10.25")
            return
        if shares < 0:
            print("[hold] 股数不能为负")
            return
        if cost < 0:
            print("[hold] 成本不能为负")
            return
        if not _upsert_hold_in_cfg(
            cfg,
            code=code,
            hold_shares=shares,
            cost_price=cost,
            config_path=config_path,
        ):
            print("[hold] 写入 config 失败（请检查磁盘权限）")
            return
        force_include_codes.add(code)
        force_exclude_codes.discard(code)
        nm = get_stock_name(code)
        print(f"[hold] 已写入 config：{code}（{nm}） 股数 {shares}  成本 {cost:.4f}")
        print("       监控池已更新（本轮内下一段 watch 即生效）")
        return

    if cmd == "hold" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            print(f"[hold] 代码无效：{parts[1]!r}")
            return
        force_include_codes.add(code)
        force_exclude_codes.discard(code)
        print(
            f"[hold] 已加入监控池：{code}（{get_stock_name(code)}）（未改 config 股数/成本）"
        )
        print("       完整持仓请用：hold <代码> <股数> <成本>")
        return

    if cmd == "sell" and len(parts) == 2:
        code = normalize_stock_code(parts[1])
        if code is None:
            print(f"[sell] 代码无效：{parts[1]!r}")
            return
        force_include_codes.discard(code)
        force_exclude_codes.add(code)
        print(f"[sell] 已暂停监控：{code}（{get_stock_name(code)}）（未删 config 条目）")
        print("       删除持仓记录请用：unhold <代码>")
        return

    print("[命令] 用法：")
    print("  hold <代码> <股数> <成本>   例：hold 000537 3000 10.25  （写入 config）")
    print("  hold <代码>                 仅纳入监控池（不写股数成本）")
    print("  unhold <代码>               从 config 删除该标的")
    print("  showhold                    打印当前持仓表")
    print("  sell <代码>                 暂停监控（runtime，不删 config）")


def _run_auto_daily_select(args: Any) -> int:
    """执行盘前自动筛选并输出统计；返回 0 成功，1 失败。"""
    if not args.config.exists():
        print(f"缺少配置: {args.config}")
        return 1
    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    out = run_daily_selector(
        cfg,
        limit=int(cfg.get("scan_pool_max", 250)),
        top_n_per_strategy=20,
    )
    out_path = args.config.parent / "daily_picks.json"
    save_daily_selector_result(out, out_path)
    print(f"[完成] 每日分策略选股已输出: {out_path}")
    print("  - 优质股: " f"{len(out.get('优质股') or out.get('优质标的') or [])}")
    print("  - 观察股: " f"{len(out.get('观察股') or out.get('观察标的') or [])}")
    print("  - 淘汰股: " f"{len(out.get('淘汰股') or out.get('淘汰标的') or [])}")

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
        return f"\033[92m{text}\033[0m"   # 跌 → 绿
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
        out = out.replace(sell_m, f"\033[1;92m{sell_m}\033[0m")
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
        print(
            color_line(
                None,
                f"[{tstr}] {code} ({disp_name}) 现价 — 当日 — "
                f"｜行情暂不可用（持仓/hold 仍展示，下一轮重试）",
            )
        )
        print(format_tags_line(rule))
        return 0.0

    now_price = float(q["price"])
    day_pct = q.get("change_pct")
    dp = day_pct if day_pct is not None else 0.0
    tstr = datetime.now().strftime("%H:%M:%S")
    base_txt = (
        f"[{tstr}] {code} ({get_stock_name(code)}) "
        f"现价 {now_price:.2f} 当日 {dp:+.2f}%"
    )
    print(color_line(day_pct, base_txt))
    print(format_tags_line(rule))

    if show_pick_card and score_row:
        print(
            f"      └ 【优选画像】形态评分 {score_row['pattern_score']:.1f}｜"
            f"盈利概率约 {score_row['profit_prob_pct']:.1f}%｜"
            f"风险 {score_row['risk_level']}｜低吸逻辑：{score_row['dip_logic']}"
        )

    cost = float(rule.get("cost_price") or 0.0)
    hold = int(rule.get("hold_shares") or 0)
    mv = now_price * max(hold, 0)

    if cost > 0:
        pnl = risk.calc_profit_pct(now_price, cost)
        loss_before = pnl if pnl < 0 else 0.0
        print(
            f"      └ 持仓盈亏 {pnl:+.2f}%"
            + (
                f"｜补仓前亏损幅度约 {loss_before:.2f}%"
                if loss_before < 0
                else "｜补仓前为盈利或持平"
            )
        )
    else:
        pnl = 0.0

    sw = risk.check_single_position_value(mv)
    if sw:
        print(f"      └ 【仓位】{sw}")

    sig = ma_box_strategy(now_price, kline) if kline else None
    if sig:
        sig_k = f"sig_{rk}"
        print(f"      └ 【策略】{bold_strategy_buy_sell(sig)}")
        if channel_cooldown_ok(state, sig_k, cooldown_min, now_ts) and (
            not args.no_notify
        ):
            send_notification(
                f"策略｜{disp_name}", sig, f"{now_price:.2f} 元"
            )
            if "【买入信号】" in sig:
                if send_buy_signal_email(
                    "【买入信号】",
                    f"{code} {disp_name} 可以买入\n{sig}\n现价：{now_price:.2f} 元",
                ):
                    print("      └ （已发邮件通知）")
            elif "【卖出信号】" in sig and hold > 0:
                if send_sell_signal_email(
                    "【卖出信号】",
                    f"{code} {disp_name} 可以卖出（持仓 {hold} 股）\n{sig}\n现价：{now_price:.2f} 元",
                ):
                    print("      └ （已发邮件通知）")
            state[sig_k] = now_ts
            log_signal(disp_name, code, sig, now_price, base_dir=log_dir)

    st_msg = risk.check_stop_take(now_price, cost) if cost > 0 else None
    if st_msg:
        risk_k = f"risk_{rk}"
        print(
            f"      └ 【止盈止损】{bold_console(st_msg)}｜相对成本盈亏 {pnl:+.2f}%"
        )
        if channel_cooldown_ok(state, risk_k, cooldown_min, now_ts) and (
            not args.no_notify
        ):
            send_notification(
                f"风控｜{disp_name}",
                f"{st_msg}\n当前相对成本盈亏：{pnl:+.2f}%",
                f"成本 {cost:.3f}",
                sound=True,
            )
            state[risk_k] = now_ts

    add_info = risk.check_add_order(now_price, cost) if cost > 0 else None
    if add_info:
        if not add_info.get("allow"):
            print(f"      └ 【补仓禁止】{add_info.get('msg','')}")
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
                print(f"         {mag}")

            add_k = f"add_{rk}"
            if channel_cooldown_ok(state, add_k, cooldown_min, now_ts) and (
                not args.no_notify
            ):
                send_notification(
                    f"补仓测算｜{disp_name}",
                    add_text,
                    subtitle=f"{code} ({disp_name})",
                    sound=True,
                )
                state[add_k] = now_ts

    fire, reason = should_alert(now_price, rule, buffer)
    if fire and breach_cooldown_ok(state, rk, cooldown_min, now_ts):
        body = f"现价 {now_price:.2f}，{reason}"
        note = rule.get("note")
        if note:
            body += f"（{note}）"
        print(f"      └ 【区间提醒】{body}")
        if not args.no_notify:
            notify(
                f"{disp_name} 价格提醒",
                body,
                subtitle=f"{code} ({disp_name})",
                sound=True,
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
        "--backtest-code",
        type=str,
        default=None,
        help="执行 1/3/5 年三策略回测，例如 --backtest-code 600711",
    )
    args = ap.parse_args()

    if args.scan:
        from stock_scanner import scan_and_save

        return scan_and_save(args.config, force=bool(args.force_scan))

    if args.daily_select or args.daily_auto:
        rc = _run_auto_daily_select(args)
        if rc != 0:
            return rc
        if args.daily_auto:
            print("[daily-auto] 已完成盘前自动筛选，开始进入盘中监控...")
        else:
            return 0

    if args.backtest_code and not args.daily_auto:
        report = run_backtest_pack(str(args.backtest_code).strip(), years_list=[1, 3, 5])
        out_path = args.config.parent / "backtest_report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[完成] 回测报告已输出: {out_path}")
        return 0

    if args.test_notify:
        send_notification(
            "量化提醒测试",
            "Mac 通知与音效链路正常",
            subtitle="stock-price-alert",
            sound=True,
        )
        print("[测试] 已请求发送通知")
        return 0

    if not args.config.exists():
        print(f"缺少配置: {args.config}\n请复制 config.example.json 为 config.json")
        return 1

    # 默认主命令：自动先做盘前筛选，再进入盘中监控
    auto_daily = not any(
        (
            args.scan,
            args.daily_select,
            args.daily_auto,
            bool(args.backtest_code),
            args.test_notify,
        )
    )
    if auto_daily:
        print("[主流程] 自动执行盘前选股+回测筛选...")
        rc = _run_auto_daily_select(args)
        if rc != 0:
            return rc

    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    risk = RiskManager(cfg)

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
    cmd_queue = _start_command_listener()

    watch, watch_mode = _build_watch_from_daily_picks_with_overrides(
        cfg,
        args.config,
        force_include_codes=force_include_codes,
        force_exclude_codes=force_exclude_codes,
    )
    log_dir = args.config.parent

    if not watch:
        print(
            "[提示] watchlist 为空或无 enabled 标的。\n"
            "  可先执行：python run_alert.py --scan\n"
            "  （沪深主板+创业板分层筛选；持仓标签标的永不清理）"
        )
        return 0

    run_only = cfg.get("run_only_in_trading_hours", True) and not args.poll_when_closed

    print(
        f"[启动] 标的 {len(watch)} | 盘中轮询 {base_interval}s | 非交易 {closed_iv}s | "
        f"冷却 {cooldown_min:g}min | 限价防抖 ±{buffer} 元 | "
        f"本金参照 {cfg['capital']['total']:.0f} 元"
        + (" | 仅交易时段请求行情" if run_only else " | 休市亦请求行情")
    )
    if watch_mode == "quality_only":
        print("[AI筛选] 盘中仅监控 daily_picks.json 的优质股（含持仓标签保留）")
    elif watch_mode == "fallback_all":
        print("[AI筛选] 未检测到优质股清单，回退监控全部 watchlist")
    print("[命令] hold <代码> <股数> <成本> | hold <代码> | unhold | showhold | sell")

    first_round = True

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
            if not watch:
                print("[监控池] 当前为空，等待新命令或下一轮筛选...")
                time.sleep(max(5, min(base_interval, 30)))
                if args.once:
                    break
                continue

            if run_only and not is_trading_session():
                print(
                    f"\n[休市] 已开启仅交易时段轮询，{closed_iv}s 后重试… "
                    f"（需要休市也跑请加 --poll-when-closed）"
                )
                time.sleep(closed_iv + random.uniform(0.15, 1.1))
                if args.once:
                    break
                continue

            if not first_round:
                time.sleep(base_interval + random.uniform(0.15, 1.1))
            first_round = False

            ts_line = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n===== 轮询 {ts_line} | 盘中: {is_trading_session()} =====")

            fails = 0
            attempted = 0
            total_mv = 0.0
            now_ts = time.time()
            index_mult = fetch_index_mood_mult()

            items: list[dict[str, Any]] = []
            for rule in watch:
                code = str(rule.get("code", "")).strip()
                market = str(rule.get("market") or "sh")
                rk = rule_key(rule)

                if not valid_code(code):
                    print(f"[跳过] {code} 代码须为 6 位数字")
                    continue

                name = get_stock_name(code)
                attempted += 1
                no_quote = False
                try:
                    qm = fetch_quote_metrics(code, market, ut=str(ut))
                except Exception as e:
                    print(f"[行情失败] {code} ({name}): {e}")
                    try:
                        fp = fetch_price(code, market, ut=str(ut))
                        qm = {
                            **fp,
                            "amount_yuan": 0.0,
                            "float_mv_yuan": 0.0,
                            "total_mv_yuan": 0.0,
                        }
                    except Exception as e2:
                        print(f"[行情二次失败] {code} ({name}): {e2}")
                        pinned = code in force_include_codes or has_position_tag(
                            rule
                        )
                        if not pinned:
                            fails += 1
                            continue
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
                sort_score = float(score_row["sort_score"]) if score_row else -1e18
                items.append(
                    {
                        "rule": rule,
                        "q": q,
                        "kline": kline_pure,
                        "score_row": score_row,
                        "sort_score": sort_score,
                        "tagged": has_position_tag(rule)
                        or code in force_include_codes,
                        "rk": rk,
                        "label": label,
                        "no_quote": no_quote,
                    }
                )

            tagged_items = [x for x in items if x["tagged"]]
            untagged_items = [x for x in items if not x["tagged"]]
            untagged_items.sort(key=lambda x: x["sort_score"], reverse=True)
            pick_n = max(1, int(cfg.get("daily_pick_count", 6)))
            top_picks = untagged_items[:pick_n]
            rest_items = untagged_items[pick_n:]

            sections: list[tuple[str, list[dict[str, Any]], bool]] = []
            if tagged_items:
                sections.append(("【我的持仓（带标签）】", tagged_items, False))
            if top_picks:
                sections.append((f"【今日{pick_n}只低吸优选】", top_picks, True))
            if rest_items:
                sections.append(("【其余监控标的】", rest_items, False))

            for sec_title, group, show_pick in sections:
                print(f"\n---------- {sec_title} ----------")
                for pack in group:
                    mv = process_watch_pack(
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
                    )
                    total_mv += mv

            state["__force_include__"] = sorted(force_include_codes)
            state["__force_exclude__"] = sorted(force_exclude_codes)
            save_state(st_path, state)

            if attempted > 0 and fails * 10 >= attempted * 7:
                print(f"[熔断] 本轮失败过多 ({fails}/{attempted})，额外等待 {FUSE_MIN_INTERVAL}s")
                time.sleep(FUSE_MIN_INTERVAL)

            tot_w = risk.check_total_position_value(total_mv)
            if tot_w:
                print(f"\n【总仓位】{tot_w}")

            if args.once:
                break

    except KeyboardInterrupt:
        print("\n[退出] 已停止")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())