#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动网格搜索 select_candidate_filters 阈值并（可选）写回 config.json。

由 ops_automation.auto_tune_selector_filters 配置；逻辑复用 optimize_selector_thresholds 模块。
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optimize_selector_thresholds import (
    evaluate_mask,
    grid_search_selector_filters,
    load_enriched_selector_optimization_frame,
)
from run_alert import merge_full_config

LOG_PATH = ROOT / "data" / "auto_tune.log"
BACKUP_DIR = ROOT / "data" / "config_backups"
BACKUP_PREFIX = "config_before_selector_tune_"


def _setup_logging() -> logging.Logger:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("auto_tune_selector_filters")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    log.addHandler(fh)
    return log


def _prune_backups(backup_dir: Path, *, prefix: str, keep: int) -> None:
    if keep <= 0 or not backup_dir.is_dir():
        return
    files = sorted(
        [p for p in backup_dir.iterdir() if p.is_file() and p.name.startswith(prefix)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in files[int(keep) :]:
        try:
            p.unlink()
        except OSError:
            pass


def _backup_config(config_path: Path, *, keep: int) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{BACKUP_PREFIX}{ts}.json"
    shutil.copy2(config_path, dest)
    _prune_backups(BACKUP_DIR, prefix=BACKUP_PREFIX, keep=keep)
    return dest


def validate_new_threshold_on_history(
    df: Any,
    *,
    old_range_max: float,
    old_sell_max: float,
    new_range_max: float,
    new_sell_max: float,
    require_range_pos: bool,
) -> dict[str, Any]:
    """
    在同一套 enriched 历史样本上，分别用旧/新阈值模拟过滤，对比 mean_ret 与胜率（理论提升，非未来实盘一周）。
    返回字典含 old/new 统计与 improvement_*。
    """
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        empty = {"n": 0, "mean_ret": None, "win_rate": None}
        return {
            "old": empty,
            "new": empty,
            "improvement_mean_ret": None,
            "improvement_win_rate": None,
            "note": "empty_frame",
        }

    def _pack(
        ev: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if ev is None:
            return {"n": 0, "mean_ret": None, "win_rate": None}
        return {
            "n": int(ev["n"]),
            "mean_ret": float(ev["mean_ret"]),
            "win_rate": float(ev["win_rate"]),
        }

    old_ev = evaluate_mask(
        df,
        range_max=float(old_range_max),
        sell_max=float(old_sell_max),
        require_range_pos=require_range_pos,
    )
    new_ev = evaluate_mask(
        df,
        range_max=float(new_range_max),
        sell_max=float(new_sell_max),
        require_range_pos=require_range_pos,
    )
    po, pn = _pack(old_ev), _pack(new_ev)
    imp_r = imp_w = None
    if po["mean_ret"] is not None and pn["mean_ret"] is not None:
        imp_r = pn["mean_ret"] - po["mean_ret"]
    if po["win_rate"] is not None and pn["win_rate"] is not None:
        imp_w = pn["win_rate"] - po["win_rate"]
    return {
        "old": po,
        "new": pn,
        "improvement_mean_ret": imp_r,
        "improvement_win_rate": imp_w,
    }


def _format_threshold_comparison_human(
    cmp: dict[str, Any],
    *,
    old_range: float,
    old_sell: float,
    new_range: float,
    new_sell: float,
) -> str:
    def _line(label: str, d: dict[str, Any] | None) -> str:
        if not d:
            return f"{label}: （无数据）"
        n = int(d.get("n", 0))
        mr = d.get("mean_ret")
        wr = d.get("win_rate")
        bits = [f"n={n}"]
        bits.append(f"mean_ret={mr:.4f}" if mr is not None else "mean_ret=—")
        bits.append(f"win_rate={wr:.2%}" if wr is not None else "win_rate=—")
        return f"{label}: " + ", ".join(bits)

    o = cmp.get("old") if isinstance(cmp.get("old"), dict) else None
    n = cmp.get("new") if isinstance(cmp.get("new"), dict) else None
    lines = [
        f"阈值: 旧 range≤{old_range:.3f} sell≤{old_sell:.1f} | 新 range≤{new_range:.3f} sell≤{new_sell:.1f}",
        _line("旧过滤样本", o),
        _line("新过滤样本", n),
    ]
    imp_r = cmp.get("improvement_mean_ret")
    imp_w = cmp.get("improvement_win_rate")
    if imp_r is not None and imp_w is not None:
        lines.append(
            f"理论提升: Δmean_ret={imp_r:+.4f}  Δwin_rate={imp_w:+.2%}"
        )
    elif imp_r is not None:
        lines.append(f"理论提升: Δmean_ret={imp_r:+.4f}  Δwin_rate=—")
    else:
        lines.append("理论提升: 一侧无有效过滤样本，未计算 Δ。")
    lines.append("说明: 基于 picks_history 锚定样本与当前过滤逻辑的回溯对比，非下一周实盘。")
    note = cmp.get("note")
    if note:
        lines.append(f"备注: {note}")
    return "\n".join(lines)


def _summary_trade_net_and_activity(tr: Any) -> tuple[bool, float]:
    """从 daily_summary 的 trades 块判断是否纳入调参，并取 net_profit（元）。"""
    if not isinstance(tr, dict):
        return False, 0.0
    buys = tr.get("buys") or []
    sells = tr.get("sells") or []
    n_b = len(buys) if isinstance(buys, list) else 0
    n_s = len(sells) if isinstance(sells, list) else 0
    n_p = len(tr.get("sell_monitor_pauses") or []) if isinstance(tr.get("sell_monitor_pauses"), list) else 0
    n_hw = len(tr.get("hold_watch_only") or []) if isinstance(tr.get("hold_watch_only"), list) else 0
    raw_net = tr.get("net_profit", tr.get("realized_profit"))
    try:
        net = float(raw_net) if raw_net is not None else 0.0
    except (TypeError, ValueError):
        net = 0.0
    activity = n_b > 0 or n_s > 0 or n_p > 0 or n_hw > 0 or abs(net) > 1e-6
    return activity, net


def _trade_norm_from_daily_summary_file(path: Path, scale_yuan: float) -> tuple[float, bool]:
    """返回 (tanh 归一化得分, 当日是否有交易/盈亏记录可参与优化)。"""
    if not path.is_file():
        return 0.0, False
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0.0, False
    if not isinstance(j, dict):
        return 0.0, False
    act, net = _summary_trade_net_and_activity(j.get("trades"))
    if not act:
        return 0.0, False
    sc = max(float(scale_yuan), 1.0)
    return math.tanh(net / sc), True


def _attach_trade_norm_for_dataframe(
    df: Any,
    *,
    config_path: Path,
    scale_yuan: float,
    log: logging.Logger,
) -> tuple[Any, bool]:
    """
    按 anchor_date 对齐 data/daily_summary_history/YYYY-MM-DD.json，写入 trade_norm 列。
    若任意锚点日存在可参与优化的 trades，返回 (df, True)；否则不增列并返回 (df, False)。
    """
    import pandas as pd

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df, False
    if "anchor_date" not in df.columns:
        return df, False

    root = config_path.parent
    hdir = root / "data" / "daily_summary_history"
    if not hdir.is_dir():
        log.info("trade_norm: 无目录 %s", hdir)
        return df, False

    ad_series = pd.to_datetime(df["anchor_date"], errors="coerce")
    dates = sorted({d.strftime("%Y-%m-%d") for d in ad_series.dropna().tolist()})
    norm_by_date: dict[str, float] = {}
    any_signal = False
    for d in dates:
        path = hdir / f"{d}.json"
        norm, ok = _trade_norm_from_daily_summary_file(path, scale_yuan)
        norm_by_date[d] = float(norm)
        if ok:
            any_signal = True

    if not any_signal:
        return df, False

    def _map_one(v: Any) -> float:
        if pd.isna(v):
            return 0.0
        try:
            ds = pd.Timestamp(v).strftime("%Y-%m-%d")
        except Exception:
            return 0.0
        return float(norm_by_date.get(ds, 0.0))

    out = df.copy()
    out["trade_norm"] = ad_series.map(_map_one).astype(float)
    return out, True


def _self_improve_blend_kwargs(
    oa: dict[str, Any],
    *,
    config_path: Path,
    now: datetime,
    log: logging.Logger,
) -> dict[str, Any]:
    """self_improve_from_summary 时：叠短窗 anchor 网格目标；依赖 data/daily_summary_history 已有若干份。"""
    if not bool(oa.get("self_improve_from_summary_enabled", False)):
        return {}
    lb = max(1, int(oa.get("self_improve_lookback_days", 5) or 5))
    try:
        w = float(oa.get("self_improve_blend_weight", 0.25) or 0.25)
    except (TypeError, ValueError):
        w = 0.25
    w = max(0.0, min(1.0, w))
    root = config_path.parent
    hdir = root / "data" / "daily_summary_history"
    n_hist = len(list(hdir.glob("*.json"))) if hdir.is_dir() else 0
    min_hist = min(3, lb)
    if n_hist < min_hist:
        log.info(
            "self_improve: daily_summary_history 仅 %s 份 < %s，本轮不叠短窗",
            n_hist,
            min_hist,
        )
        return {}
    cutoff = (now - timedelta(days=lb)).strftime("%Y-%m-%d")
    try:
        min_recent = max(3, int(oa.get("self_improve_min_recent_samples", 5) or 5))
    except (TypeError, ValueError):
        min_recent = 5
    log.info(
        "self_improve: recent_anchor_cutoff=%s blend_weight=%s summary_hist=%s",
        cutoff,
        w,
        n_hist,
    )
    return {
        "recent_blend_weight": w,
        "recent_anchor_cutoff": cutoff,
        "min_recent_samples": min_recent,
    }


def _self_improve_trade_blend_weight(
    oa: dict[str, Any],
    *,
    config_path: Path,
    df: Any,
    log: logging.Logger,
) -> tuple[float, float, Any]:
    """
    self_improve_use_trade_profit + self_improve_trade_weight；
    若开启但历史总结中无有效 trades，则权重降为 0（与旧行为一致）。
    返回 (trade_blend_weight, trade_scale_yuan, df_maybe_augmented)。
    """
    if not bool(oa.get("self_improve_use_trade_profit", False)):
        return 0.0, 5000.0, df
    try:
        w = float(oa.get("self_improve_trade_weight", 0.2) or 0.2)
    except (TypeError, ValueError):
        w = 0.2
    w = max(0.0, min(1.0, w))
    try:
        scale = float(oa.get("self_improve_trade_scale_yuan", 5000.0) or 5000.0)
    except (TypeError, ValueError):
        scale = 5000.0
    scale = max(1.0, scale)
    if w <= 1e-12:
        return 0.0, scale, df
    df2, ok = _attach_trade_norm_for_dataframe(
        df, config_path=config_path, scale_yuan=scale, log=log
    )
    if not ok:
        log.info(
            "self_improve_use_trade_profit: 未在 daily_summary_history 找到含有效 trades 的锚点日，"
            "本轮仅用 forward 收益目标"
        )
        return 0.0, scale, df
    log.info(
        "self_improve_use_trade_profit: 已附加 trade_norm（scale_yuan=%s, weight=%s）",
        scale,
        w,
    )
    return w, scale, df2


def _maybe_notify(cfg: dict[str, Any], subject: str, body: str) -> None:
    try:
        from email_notify import send_email_alert

        send_email_alert(subject, body, app_cfg=cfg)
    except Exception:
        pass


def run_auto_tune_selector_filters(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    state: dict[str, Any],
    now: datetime,
    force: bool = False,
    dry_apply: bool = False,
) -> None:
    """由 run_alert 收盘后调用；根据配置决定是否执行、是否写回。
    force=True 时忽略 enabled/排期/去重，并将 min_snapshot_files 视为 1、略放宽网格样本门槛（供 CLI）。
    dry_apply=True 时强制 apply=false（不写 config）。"""
    log = _setup_logging()
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    box = oa.get("auto_tune_selector_filters")
    if not isinstance(box, dict):
        box = {}
    box = dict(box)
    if dry_apply:
        box["apply"] = False
    if not force and not bool(box.get("enabled")):
        return

    sched_run_on = str(box.get("run_on") or "weekly_friday").strip().lower()
    if not force and bool(oa.get("self_improve_from_summary_enabled", False)):
        sched_run_on = "daily"
    mark_key: str | None = None
    mark_val: str | None = None
    if not force:
        if sched_run_on in ("weekly_friday", "weekly", "friday"):
            if now.weekday() != 4:
                return
            week_tag = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
            if state.get("__ops_selector_filters_tune_week__") == week_tag:
                return
            mark_key, mark_val = "__ops_selector_filters_tune_week__", week_tag
        elif sched_run_on == "daily":
            today = now.strftime("%Y-%m-%d")
            if state.get("__ops_selector_filters_tune_day__") == today:
                return
            mark_key, mark_val = "__ops_selector_filters_tune_day__", today
        else:
            log.warning("auto_tune_selector_filters.run_on 无效: %s", sched_run_on)
            return

    min_files = max(1, int(box.get("min_snapshot_files", 20) or 20))
    if force:
        min_files = 1
    hdir_raw = box.get("history_dir")
    if isinstance(hdir_raw, str) and hdir_raw.strip():
        history_dir = (
            Path(hdir_raw.strip()).resolve()
            if Path(hdir_raw.strip()).is_absolute()
            else (config_path.parent / hdir_raw.strip()).resolve()
        )
    else:
        history_dir = (config_path.parent / "data" / "picks_history").resolve()

    n_files = len(list(history_dir.glob("*.json"))) if history_dir.is_dir() else 0
    if n_files < min_files:
        msg = f"快照不足: {n_files} < {min_files}（{history_dir}），跳过 auto_tune_selector_filters"
        log.warning(msg)
        if bool(box.get("notify", False)):
            _maybe_notify(cfg, "[选股过滤] 自动调参跳过", msg)
        return

    horizon = max(1, int(box.get("horizon", 5) or 5))
    min_grid = max(1, int(box.get("min_grid_eligible_samples", 15) or 15))
    min_best_n = max(1, int(box.get("min_best_filtered_samples", 20) or 20))
    if force:
        min_grid = 1
        min_best_n = 1
    range_only = bool(box.get("range_only", False))
    require_rp = bool(box.get("require_range_pos", True))

    try:
        df, _n_paths, _n_rec, _rl = load_enriched_selector_optimization_frame(
            cfg,
            config_path=config_path,
            history_dir=history_dir,
            horizon=horizon,
            range_lookback_days=box.get("range_lookback_days"),
            include_quality=not bool(box.get("no_quality", False)),
            include_watch=not bool(box.get("no_watch", False)),
            include_reject=bool(box.get("include_reject", False)),
        )
    except FileNotFoundError as e:
        log.warning("%s", e)
        if bool(box.get("notify", False)):
            _maybe_notify(cfg, "[选股过滤] 自动调参失败", str(e))
        return

    if df.empty:
        log.warning("enriched 样本为空，跳过")
        return

    blend_kw = _self_improve_blend_kwargs(
        oa, config_path=config_path, now=now, log=log
    )
    w_trade, _scale, df_eff = _self_improve_trade_blend_weight(
        oa, config_path=config_path, df=df, log=log
    )
    _grid, best = grid_search_selector_filters(
        df_eff,
        range_min=float(box.get("range_min", 0.5)),
        range_max=float(box.get("range_max", 0.85)),
        range_step=float(box.get("range_step", 0.05)),
        sell_min=float(box.get("sell_min", 50.0)),
        sell_max=float(box.get("sell_max", 85.0)),
        sell_step=float(box.get("sell_step", 5.0)),
        range_only=range_only,
        require_range_pos=require_rp,
        min_samples=min_grid,
        trade_blend_weight=w_trade,
        **blend_kw,
    )
    del _grid
    if best is None:
        log.warning("网格无 eligible 组合（min_grid_eligible_samples=%s）", min_grid)
        if bool(box.get("notify", False)):
            _maybe_notify(
                cfg,
                "[选股过滤] 自动调参无结果",
                f"无满足 n≥{min_grid} 的阈值组合，请积累快照或降低 min_grid_eligible_samples。",
            )
        return

    qs = cfg.get("quant_selector") if isinstance(cfg.get("quant_selector"), dict) else {}
    scf = qs.get("select_candidate_filters") if isinstance(qs.get("select_candidate_filters"), dict) else {}

    new_rm = float(best["range_position_max"])
    new_sm = float(best["strategy_sell_score_max"])
    if range_only or new_sm >= 1e6:
        new_sm = float(scf.get("strategy_sell_score_max", 70.0))

    old_rm = float(scf.get("range_position_max", new_rm))
    old_sm = float(scf.get("strategy_sell_score_max", new_sm))

    thr_cmp = validate_new_threshold_on_history(
        df_eff,
        old_range_max=old_rm,
        old_sell_max=old_sm,
        new_range_max=new_rm,
        new_sell_max=new_sm,
        require_range_pos=require_rp,
    )
    comp_report = _format_threshold_comparison_human(
        thr_cmp,
        old_range=old_rm,
        old_sell=old_sm,
        new_range=new_rm,
        new_sell=new_sm,
    )
    if bool(box.get("log_history_comparison", True)):
        log.info("历史快照回溯对比（同样本集，理论提升）:\n%s", comp_report)
    if bool(box.get("notify_history_comparison", False)):
        _maybe_notify(cfg, "[选股过滤] 阈值回溯对比", comp_report)

    if int(best["n"]) < min_best_n:
        log.warning(
            "最优组合过滤后样本 n=%s < min_best_filtered_samples=%s，不写配置",
            best["n"],
            min_best_n,
        )
        if bool(box.get("notify", False)):
            _maybe_notify(
                cfg,
                "[选股过滤] 自动调参未写入",
                f"最优组合 n={best['n']} < {min_best_n}，未更新 config。\n\n{comp_report}",
            )
        return

    d_rm = abs(new_rm - old_rm)
    d_sm = abs(new_sm - old_sm)
    max_d_rm = float(box.get("max_range_delta", 0.10) or 0.10)
    max_d_sm = float(box.get("max_sell_score_delta", 15.0) or 15.0)
    skip_big = bool(box.get("skip_write_if_exceeds_delta", True))

    if skip_big and (d_rm > max_d_rm + 1e-9 or d_sm > max_d_sm + 1e-9):
        msg = (
            f"建议阈值相对当前变化过大，已跳过写入（skip_write_if_exceeds_delta=true）。\n"
            f"当前: range_position_max={old_rm}, strategy_sell_score_max={old_sm}\n"
            f"网格最优: range={new_rm}, sell={new_sm}, n={best['n']}, "
            f"mean_ret={best['mean_ret']:.4f}, win_rate={best['win_rate']:.2%}\n"
            f"Δrange={d_rm:.3f}（上限{max_d_rm}） Δsell={d_sm:.1f}（上限{max_d_sm}）\n\n"
            f"{comp_report}"
        )
        log.warning(msg)
        if bool(box.get("notify", False)):
            _maybe_notify(cfg, "[选股过滤] 自动调参未写入（变化过大）", msg)
        if mark_key is not None:
            state[mark_key] = mark_val  # type: ignore[index]
        return

    if not bool(box.get("apply", True)):
        log.info("apply=false，仅记录最优: %s", best)
        if bool(box.get("notify", False)):
            _maybe_notify(
                cfg,
                "[选股过滤] 自动调参（dry-run）",
                f"最优 range={new_rm}, sell={new_sm}, n={best['n']}, "
                f"mean_ret={best['mean_ret']:.4f}；未写 config（apply=false）。\n\n"
                f"{comp_report}",
            )
        if mark_key is not None:
            state[mark_key] = mark_val  # type: ignore[index]
        return

    keep_bu = max(1, int(box.get("keep_config_backups", 5) or 5))
    backup_p = _backup_config(config_path, keep=keep_bu)
    try:
        from selector_tune_rollback import record_pending_selector_compare

        record_pending_selector_compare(
            config_path=config_path,
            baseline_range=old_rm,
            baseline_sell=old_sm,
            trial_range=new_rm,
            trial_sell=new_sm,
            now=now,
            require_range_pos=require_rp,
        )
    except Exception as exc:
        log.warning("selector_tune_rollback 记录 pending 失败（仍继续写 config）: %s", exc)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw.setdefault("quant_selector", {})
    if not isinstance(raw["quant_selector"], dict):
        raw["quant_selector"] = {}
    raw["quant_selector"].setdefault("select_candidate_filters", {})
    if not isinstance(raw["quant_selector"]["select_candidate_filters"], dict):
        raw["quant_selector"]["select_candidate_filters"] = {}
    raw["quant_selector"]["select_candidate_filters"]["range_position_max"] = new_rm
    raw["quant_selector"]["select_candidate_filters"]["strategy_sell_score_max"] = new_sm
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log.info(
        "已更新 select_candidate_filters: range %.4f→%.4f, sell %.1f→%.1f | "
        "n=%s mean_ret=%.4f win=%.2f%% | backup=%s",
        old_rm,
        new_rm,
        old_sm,
        new_sm,
        best["n"],
        best["mean_ret"],
        best["win_rate"] * 100,
        backup_p,
    )
    if bool(box.get("notify", False)):
        _maybe_notify(
            cfg,
            "[选股过滤] 阈值已自动更新",
            f"range_position_max: {old_rm} → {new_rm}\n"
            f"strategy_sell_score_max: {old_sm} → {new_sm}\n"
            f"过滤样本 n={best['n']}, mean_ret={best['mean_ret']:.4f}, win_rate={best['win_rate']:.2%}\n"
            f"备份: {backup_p}\n\n"
            f"{comp_report}",
        )
    if mark_key is not None:
        state[mark_key] = mark_val  # type: ignore[index]


def main() -> int:
    """CLI：手动执行（需自行保证 picks_history 足够）。"""
    import argparse

    ap = argparse.ArgumentParser(description="自动调优 select_candidate_filters 并写回 config")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--force",
        action="store_true",
        help="忽略 enabled 与排期/去重；快照数门槛降为 1，并略放宽网格/最优样本门槛（仍受 delta、apply 约束）",
    )
    ap.add_argument(
        "--dry-apply",
        action="store_true",
        help="不写回 config（等价 apply=false，仅日志/通知）",
    )
    args = ap.parse_args()
    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 1
    cfg = merge_full_config(json.loads(args.config.read_text(encoding="utf-8")))
    st: dict[str, Any] = {}
    run_auto_tune_selector_filters(
        cfg=cfg,
        config_path=args.config.resolve(),
        state=st,
        now=datetime.now(),
        force=bool(args.force),
        dry_apply=bool(args.dry_apply),
    )
    print("完成。详见 data/auto_tune.log。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
