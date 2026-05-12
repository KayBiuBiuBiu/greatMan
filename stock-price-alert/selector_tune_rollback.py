#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股过滤阈值写入后的保护：在若干交易日后用 picks_history 锚定样本对比
「写入时基线阈值」与「当前(试验)阈值」的过滤子集 mean_ret，若试验明显更差则回滚 config。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def _state_path(config_path: Path) -> Path:
    return (config_path.parent / "data" / "selector_tune_apply_state.json").resolve()


def record_pending_selector_compare(
    *,
    config_path: Path,
    baseline_range: float,
    baseline_sell: float,
    trial_range: float,
    trial_sell: float,
    now: datetime,
    require_range_pos: bool,
) -> None:
    """成功写入新阈值前调用：记录待对比的基线 vs 试验阈值。"""
    if abs(float(trial_range) - float(baseline_range)) < 1e-9 and abs(
        float(trial_sell) - float(baseline_sell)
    ) < 1e-9:
        return
    p = _state_path(config_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "pending_compare": {
            "applied_date": now.strftime("%Y-%m-%d"),
            "applied_iso": now.isoformat(timespec="seconds"),
            "baseline_range_position_max": float(baseline_range),
            "baseline_strategy_sell_score_max": float(baseline_sell),
            "trial_range_position_max": float(trial_range),
            "trial_strategy_sell_score_max": float(trial_sell),
            "require_range_pos": bool(require_range_pos),
        },
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _LOG.info("selector_tune_rollback: 已记录待对比 pending_compare → %s", p.name)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _notify(cfg: dict[str, Any], subject: str, body: str) -> None:
    try:
        from email_notify import send_email_alert

        send_email_alert(subject, body, app_cfg=cfg)
    except Exception:
        pass


def maybe_rollback_selector_filters(
    *,
    cfg: dict[str, Any],
    config_path: Path,
    now: datetime,
) -> dict[str, Any]:
    """
    每日可调用（如收盘后）：若 pending 已满延迟天数且样本足够，
    在「自 applied_date 起」的锚定子集上对比 trial vs baseline 的 mean_ret，必要时回滚并清 state。
    """
    oa = cfg.get("ops_automation") if isinstance(cfg.get("ops_automation"), dict) else {}
    box = oa.get("auto_tune_selector_filters")
    if not isinstance(box, dict) or not bool(box.get("rollback_guard_enabled")):
        return {"action": "skip", "reason": "disabled"}

    delay = max(1, int(box.get("rollback_eval_delay_calendar_days", 3) or 3))
    min_n = max(5, int(box.get("rollback_min_eval_samples", 12) or 12))
    try:
        drop = float(box.get("rollback_mean_ret_drop", 0.004) or 0.004)
    except (TypeError, ValueError):
        drop = 0.004

    sp = _state_path(config_path)
    st = _load_state(sp)
    pending = st.get("pending_compare")
    if not isinstance(pending, dict):
        return {"action": "skip", "reason": "no_pending"}

    ad = str(pending.get("applied_date") or "").strip()[:10]
    if len(ad) != 10:
        return {"action": "skip", "reason": "bad_applied_date"}
    try:
        applied_d = datetime.strptime(ad, "%Y-%m-%d").date()
    except ValueError:
        return {"action": "skip", "reason": "bad_applied_date_parse"}

    if (now.date() - applied_d).days < delay:
        return {
            "action": "wait",
            "days_left": delay - (now.date() - applied_d).days,
        }

    require_rp = bool(pending.get("require_range_pos", True))
    b_rm = float(pending["baseline_range_position_max"])
    b_sm = float(pending["baseline_strategy_sell_score_max"])
    t_rm = float(pending["trial_range_position_max"])
    t_sm = float(pending["trial_strategy_sell_score_max"])

    horizon = max(1, int(box.get("horizon", 5) or 5))
    hdir_raw = box.get("history_dir")
    if isinstance(hdir_raw, str) and hdir_raw.strip():
        history_dir = (
            Path(hdir_raw.strip()).resolve()
            if Path(hdir_raw.strip()).is_absolute()
            else (config_path.parent / hdir_raw.strip()).resolve()
        )
    else:
        history_dir = (config_path.parent / "data" / "picks_history").resolve()

    try:
        from optimize_selector_thresholds import (
            evaluate_mask,
            load_enriched_selector_optimization_frame,
        )
    except Exception as exc:
        _LOG.warning("selector_tune_rollback: import failed: %s", exc)
        return {"action": "error", "reason": str(exc)}

    try:
        df, _, _, _ = load_enriched_selector_optimization_frame(
            cfg,
            config_path=config_path,
            history_dir=history_dir,
            horizon=horizon,
            range_lookback_days=box.get("range_lookback_days"),
            include_quality=not bool(box.get("no_quality", False)),
            include_watch=not bool(box.get("no_watch", False)),
            include_reject=bool(box.get("include_reject", False)),
        )
    except FileNotFoundError as exc:
        _LOG.info("selector_tune_rollback: 跳过（无 enriched 数据）: %s", exc)
        return {"action": "skip", "reason": "no_frame"}

    if df.empty or "anchor_date" not in df.columns:
        return {"action": "skip", "reason": "empty_frame"}

    import pandas as pd

    ad_ts = pd.Timestamp(ad)
    mask = pd.to_datetime(df["anchor_date"], errors="coerce") >= ad_ts
    df_w = df.loc[mask]
    if df_w.empty or len(df_w) < min_n:
        _LOG.info(
            "selector_tune_rollback: 评估窗口样本不足 n=%s（需≥%s），保留 pending",
            len(df_w),
            min_n,
        )
        return {"action": "wait_samples", "n": int(len(df_w))}

    ev_t = evaluate_mask(
        df_w,
        range_max=t_rm,
        sell_max=t_sm,
        require_range_pos=require_rp,
    )
    ev_b = evaluate_mask(
        df_w,
        range_max=b_rm,
        sell_max=b_sm,
        require_range_pos=require_rp,
    )
    if ev_t is None or ev_b is None:
        _LOG.info("selector_tune_rollback: 一侧无过滤样本，跳过回滚判定")
        sp.write_text(json.dumps({}, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"action": "clear_pending", "reason": "no_eval"}

    mt = float(ev_t["mean_ret"])
    mb = float(ev_b["mean_ret"])
    nt = int(ev_t["n"])
    nb = int(ev_b["n"])

    if nt < min_n or nb < min_n:
        _LOG.info(
            "selector_tune_rollback: 过滤后 n 不足 trial=%s baseline=%s（需≥%s）",
            nt,
            nb,
            min_n,
        )
        return {"action": "wait_filtered", "n_trial": nt, "n_baseline": nb}

    if mt >= mb - drop:
        _LOG.info(
            "selector_tune_rollback: 试验阈值未明显变差 trial_mean=%.5f baseline_mean=%.5f，接受并清除 pending",
            mt,
            mb,
        )
        sp.write_text(json.dumps({}, ensure_ascii=False) + "\n", encoding="utf-8")
        if bool(box.get("rollback_notify_on_accept", False)):
            _notify(
                cfg,
                "[选股过滤] 回滚守护·接受新阈值",
                f"applied≥{ad} 窗口内 trial mean_ret={mt:.5f} (n={nt}) vs baseline {mb:.5f} (n={nb})",
            )
        return {
            "action": "accept_trial",
            "trial_mean_ret": mt,
            "baseline_mean_ret": mb,
        }

    # 回滚：写回基线阈值
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw.setdefault("quant_selector", {})
    if not isinstance(raw["quant_selector"], dict):
        raw["quant_selector"] = {}
    raw["quant_selector"].setdefault("select_candidate_filters", {})
    if not isinstance(raw["quant_selector"]["select_candidate_filters"], dict):
        raw["quant_selector"]["select_candidate_filters"] = {}
    raw["quant_selector"]["select_candidate_filters"]["range_position_max"] = b_rm
    raw["quant_selector"]["select_candidate_filters"]["strategy_sell_score_max"] = b_sm
    config_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sp.write_text(json.dumps({}, ensure_ascii=False) + "\n", encoding="utf-8")
    msg = (
        f"已自动回滚 select_candidate_filters 至写入前基线（试验在锚定≥{ad} 子集上明显偏弱）。\n"
        f"trial mean_ret={mt:.5f} n={nt} | baseline mean_ret={mb:.5f} n={nb}\n"
        f"恢复: range≤{b_rm} sell≤{b_sm}"
    )
    _LOG.warning("selector_tune_rollback: %s", msg.replace("\n", " | "))
    if bool(box.get("rollback_notify", True)):
        _notify(cfg, "[选股过滤] 阈值已自动回滚", msg)
    return {
        "action": "rolled_back",
        "trial_mean_ret": mt,
        "baseline_mean_ret": mb,
        "restored_range": b_rm,
        "restored_sell": b_sm,
    }
