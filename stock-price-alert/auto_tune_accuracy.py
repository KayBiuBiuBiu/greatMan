#!/usr/bin/env python3
"""基于 backtest_alerts 报告自动微调预警准确性参数。

含（可选）根据 risk_stop_take 命中率切换止盈回测语义：
auto_tune.take_profit_semantics_auto 为 true 时，
在样本量足够前提下可在「卖对」与「旧语义」之间写回 alert_log.risk_stop_take_eval。
收盘后由 ops_automation 调用本脚本（与邮件机器人无关）。"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


@dataclass
class Change:
    path: str
    old: Any
    new: Any
    reason: str
    hit_rate: float | None
    samples: int


# 趋势类：样本足够时按命中率双向微调（类似比例控制，每次小幅移动）
TREND_HR_HIGH = 0.70
TREND_HR_LOW = 0.50
TREND_MIN_SAMPLES = 15

RULES = {
    "drawdown": {
        "min_samples": 10,
        "hit_rate_threshold": 0.60,
        "param_path": ("drawdown_alert", "warn_1_ratio"),
        "step": -0.01,
        "min_value": -0.10,
        "reason": "回撤命中率偏低，提高第一档触发严格度",
    },
}


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"{v:.1%}"


def _get_nested(cfg: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = cfg
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _set_nested(cfg: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur = cfg
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def _safe_float(x: Any, default: float) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def run_backtest_report(config_path: Path, days: int) -> dict[str, Any]:
    since_day = (date.today() - timedelta(days=max(1, int(days)))).isoformat()
    cmd = [
        sys.executable,
        str(ROOT / "backtest_alerts.py"),
        "-c",
        str(config_path),
        "--since",
        since_day,
    ]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip()
        raise SystemExit(f"backtest_alerts.py 执行失败: {err}")
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        body = (cp.stdout or "").strip()
        preview = body[:500] + ("..." if len(body) > 500 else "")
        raise SystemExit(f"无法解析回测输出 JSON: {exc}\n输出片段: {preview}")


def _trend_slip_hit_rate_adjust(cfg: dict[str, Any], by_type: dict[str, Any]) -> list[Change]:
    """
    命中率偏高 → 略收紧（少报）；偏低 → 略放宽（多报）。
    一次运行内每项最多动一档，避免震荡过大。
    """
    changes: list[Change] = []
    ts = by_type.get("trend_slip") or {}
    n = int(ts.get("n", 0) or 0)
    hr = ts.get("hit_rate")
    hrf = float(hr) if isinstance(hr, (int, float)) else None
    if n < TREND_MIN_SAMPLES or hrf is None:
        return changes

    path_p = ("trend_slippage_alert", "min_pillars_weak")
    path_d = ("trend_slippage_alert", "stock_min_weak_dims")
    path_v = ("trend_slippage_alert", "min_volume_ratio")

    def _append(path: tuple[str, ...], old: Any, new: Any, reason: str) -> None:
        if new == old:
            return
        _set_nested(cfg, path, new)
        changes.append(
            Change(
                path=".".join(path),
                old=old,
                new=new,
                reason=reason,
                hit_rate=hrf,
                samples=n,
            )
        )

    if hrf >= TREND_HR_HIGH:
        old_p = int(_safe_float(_get_nested(cfg, path_p), 2))
        new_p = min(old_p + 1, 4)
        _append(
            path_p,
            old_p,
            new_p,
            f"趋势命中率偏高(≥{TREND_HR_HIGH:.0%})，略提高 min_pillars_weak 减少预警",
        )
        old_d = int(_safe_float(_get_nested(cfg, path_d), 2))
        new_d = min(old_d + 1, 5)
        _append(
            path_d,
            old_d,
            new_d,
            "趋势命中率偏高，略提高 stock_min_weak_dims",
        )
        old_v = _safe_float(_get_nested(cfg, path_v), 0.8)
        new_v = min(round(old_v + 0.1, 4), 2.0)
        _append(
            path_v,
            old_v,
            new_v,
            "趋势命中率偏高，略提高 min_volume_ratio",
        )
        return changes

    if hrf <= TREND_HR_LOW:
        old_p = int(_safe_float(_get_nested(cfg, path_p), 2))
        new_p = max(old_p - 1, 1)
        _append(
            path_p,
            old_p,
            new_p,
            f"趋势命中率偏低(≤{TREND_HR_LOW:.0%})，略降低 min_pillars_weak 增加覆盖",
        )
        old_d = int(_safe_float(_get_nested(cfg, path_d), 2))
        new_d = max(old_d - 1, 1)
        _append(
            path_d,
            old_d,
            new_d,
            "趋势命中率偏低，略降低 stock_min_weak_dims",
        )
        old_v = _safe_float(_get_nested(cfg, path_v), 0.8)
        new_v = max(round(old_v - 0.1, 4), 0.2)
        _append(
            path_v,
            old_v,
            new_v,
            "趋势命中率偏低，略降低 min_volume_ratio",
        )
        return changes

    # 中间带：略低于 0.55 时仅小幅提高量比（兼容旧版「假阳性略多」时的温和收紧）
    if hrf < 0.55 and n >= 20:
        old_v = _safe_float(_get_nested(cfg, path_v), 0.8)
        new_v = min(round(old_v + 0.1, 4), 2.0)
        _append(
            path_v,
            old_v,
            new_v,
            "趋势命中率居中略低，仅略提高 min_volume_ratio",
        )
    return changes


def _risk_stop_take_profit_semantics_changes(
    cfg: dict[str, Any], by_type: dict[str, Any]
) -> list[Change]:
    """
    根据 risk_stop_take 的命中率自动切换止盈回测语义（写 alert_log.risk_stop_take_eval）。
    需在 config 中开启 auto_tune.take_profit_semantics_auto。

    - 当前为「卖对」语义 (1) 且 scored 样本足够、命中率过低 → 切换为旧语义 (0)
    - 当前为旧语义 (0) 且命中率过高 → 切回「卖对」语义 (1)（阈值默认较保守，避免震荡）
    """
    at = cfg.get("auto_tune") if isinstance(cfg.get("auto_tune"), dict) else {}
    if not bool(at.get("take_profit_semantics_auto", False)):
        return []
    min_n = max(5, int(at.get("take_profit_semantics_min_samples", 25) or 25))
    hr_to_legacy = float(at.get("take_profit_hr_switch_to_legacy", 0.15) or 0.15)
    hr_to_correctness = float(
        at.get("take_profit_hr_switch_to_correctness", 0.72) or 0.72
    )
    hr_to_legacy = max(0.0, min(1.0, hr_to_legacy))
    hr_to_correctness = max(0.0, min(1.0, hr_to_correctness))

    rst = by_type.get("risk_stop_take") or {}
    n_scored = int(rst.get("n_hit_scored", 0) or 0)
    hr = rst.get("hit_rate")
    hrf = float(hr) if isinstance(hr, (int, float)) else None
    if n_scored < min_n or hrf is None:
        return []

    al = cfg.setdefault("alert_log", {})
    if not isinstance(al, dict):
        cfg["alert_log"] = {}
        al = cfg["alert_log"]
    rte = al.setdefault("risk_stop_take_eval", {})
    if not isinstance(rte, dict):
        al["risk_stop_take_eval"] = {}
        rte = al["risk_stop_take_eval"]
    try:
        cur = int(float(rte.get("take_profit_hit_for_correctness", 1.0)))
    except (TypeError, ValueError):
        cur = 1
    cur = 0 if cur == 0 else 1

    changes: list[Change] = []
    path_label = "alert_log.risk_stop_take_eval.take_profit_hit_for_correctness"

    if cur == 1 and hrf <= hr_to_legacy:
        rte["take_profit_hit_for_correctness"] = 0.0
        changes.append(
            Change(
                path=path_label,
                old=1,
                new=0,
                reason=(
                    f"卖对语义下 risk_stop_take 命中率≤{hr_to_legacy:.0%}，"
                    "切换旧语义（卖飞算 hit）"
                ),
                hit_rate=hrf,
                samples=n_scored,
            )
        )
    elif cur == 0 and hrf >= hr_to_correctness:
        rte["take_profit_hit_for_correctness"] = 1.0
        changes.append(
            Change(
                path=path_label,
                old=0,
                new=1,
                reason=(
                    f"旧语义下 risk_stop_take 命中率≥{hr_to_correctness:.0%}，"
                    "切回卖对语义"
                ),
                hit_rate=hrf,
                samples=n_scored,
            )
        )
    return changes


def _drawdown_changes(cfg: dict[str, Any], by_type: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    dd = by_type.get("drawdown") or {}
    n = int(dd.get("n", 0) or 0)
    hr = dd.get("hit_rate")
    hrf = float(hr) if isinstance(hr, (int, float)) else None
    r = RULES["drawdown"]
    if n >= int(r["min_samples"]) and hrf is not None and hrf < float(r["hit_rate_threshold"]):
        path = r["param_path"]
        old = _safe_float(_get_nested(cfg, path), -0.03)
        new = max(old + float(r["step"]), float(r["min_value"]))
        new = round(new, 4)
        if new != old:
            _set_nested(cfg, path, new)
            changes.append(
                Change(
                    path=".".join(path),
                    old=old,
                    new=new,
                    reason=str(r["reason"]),
                    hit_rate=hrf,
                    samples=n,
                )
            )
    return changes


def adjust_config(cfg: dict[str, Any], report: dict[str, Any]) -> list[Change]:
    by_type = report.get("by_alert_type") or {}
    if not isinstance(by_type, dict):
        by_type = {}
    changes: list[Change] = []
    changes.extend(_trend_slip_hit_rate_adjust(cfg, by_type))
    changes.extend(_drawdown_changes(cfg, by_type))
    changes.extend(_risk_stop_take_profit_semantics_changes(cfg, by_type))
    return changes


def _strategy_buy_r1_grid_changes(cfg: dict[str, Any], days: int) -> list[Change]:
    """
    对 alert_log.strategy_hit_eval.buy_hit_r1_above_pct 做轻量网格搜索（不写库，只读 evaluate）。

    控制项（均在 auto_tune 下）：
    - hit_eval_grid_enabled: 总开关
    - hit_eval_optimize_pause: true 时跳过全部 hit 网格（手动锁住）
    - hit_eval_param_locks: 含 \"buy_hit_r1_above_pct\" 时跳过该参数
    - hit_eval_grid_buy_hit_r1_above_pct: 候选列表（百分数，与 config 一致）
    - hit_eval_grid_window_days / hit_eval_grid_days: 窗口自然日（优先前者；默认 CLI --days）
    - hit_eval_grid_min_strategy_scored: strategy 计分样本下限
    """
    at = cfg.get("auto_tune") if isinstance(cfg.get("auto_tune"), dict) else {}
    if not bool(at.get("hit_eval_grid_enabled", False)):
        return []
    if bool(at.get("hit_eval_optimize_pause", False)):
        return []
    locks_raw = at.get("hit_eval_param_locks")
    locks = {str(x).strip() for x in (locks_raw or []) if str(x).strip()}
    if "buy_hit_r1_above_pct" in locks:
        return []

    grid = at.get("hit_eval_grid_buy_hit_r1_above_pct")
    if not isinstance(grid, list) or len(grid) < 2:
        grid = [-0.5, 0.0, 0.5, 1.0]
    grid_vals: list[float] = []
    for x in grid:
        try:
            grid_vals.append(float(x))
        except (TypeError, ValueError):
            pass
    if len(grid_vals) < 2:
        return []

    win_raw = at.get("hit_eval_grid_window_days", at.get("hit_eval_grid_days", days))
    win_days = int(win_raw if win_raw is not None else days) or days
    since_day = (date.today() - timedelta(days=max(1, win_days))).isoformat()
    min_scored = max(5, int(at.get("hit_eval_grid_min_strategy_scored", 25) or 25))

    al = cfg.setdefault("alert_log", {})
    if not isinstance(al, dict):
        cfg["alert_log"] = {}
        al = cfg["alert_log"]
    she = al.get("strategy_hit_eval")
    if not isinstance(she, dict):
        she = {}
        al["strategy_hit_eval"] = she
    try:
        current = float(she.get("buy_hit_r1_above_pct", 0.0))
    except (TypeError, ValueError):
        current = 0.0

    from backtest_alerts import evaluate_hit_report_only
    from run_alert import merge_full_config

    best_v: float | None = None
    best_key: tuple[float, int] = (-1.0, -1)

    for cand in grid_vals:
        raw_t = copy.deepcopy(cfg)
        al_t = raw_t.setdefault("alert_log", {})
        if not isinstance(al_t, dict):
            raw_t["alert_log"] = {}
            al_t = raw_t["alert_log"]
        she_t = al_t.setdefault("strategy_hit_eval", {})
        if not isinstance(she_t, dict):
            she_t = {}
            al_t["strategy_hit_eval"] = she_t
        she_t["buy_hit_r1_above_pct"] = cand
        merged = merge_full_config(copy.deepcopy(raw_t))
        rep = evaluate_hit_report_only(merged, root=ROOT, since=since_day)
        st = (rep.get("by_alert_type") or {}).get("strategy") or {}
        ns = int(st.get("n_hit_scored", 0) or 0)
        hr = st.get("hit_rate")
        hrf = float(hr) if isinstance(hr, (int, float)) else None
        if hrf is None or ns < min_scored:
            continue
        key = (hrf, ns)
        if key > best_key:
            best_key = key
            best_v = cand

    if best_v is None:
        return []
    if abs(float(best_v) - current) < 1e-12:
        return []

    she["buy_hit_r1_above_pct"] = float(best_v)
    return [
        Change(
            path="alert_log.strategy_hit_eval.buy_hit_r1_above_pct",
            old=current,
            new=float(best_v),
            reason=(
                f"网格优化 buy_hit_r1_above_pct（{win_days}d 窗口，"
                f"strategy 计分≥{min_scored}）"
            ),
            hit_rate=best_key[0],
            samples=int(best_key[1]),
        )
    ]


def _normalized_ignore_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if s.isdigit() and len(s) <= 6:
            out.append(s.zfill(6))
    return sorted(set(out))


def merge_fp_user_feedback_into_ignore(
    cfg: dict[str, Any], lookback_days: int, *, root: Path | None = None
) -> list[Change]:
    """
    将 alert_events 中邮件标记为 fp 的股票代码并入
    trend_slippage_alert / drawdown_alert 的 alert_ignore_codes。
    """
    from alert_log_store import distinct_fp_codes_since

    base = root if root is not None else ROOT
    since = (date.today() - timedelta(days=max(1, int(lookback_days)))).isoformat()
    fp_codes = distinct_fp_codes_since(cfg, base, anchor_since=since)
    if not fp_codes:
        return []
    changes: list[Change] = []

    path_trend = ("trend_slippage_alert", "alert_ignore_codes")
    old_t = _normalized_ignore_list(_get_nested(cfg, path_trend))
    new_t = sorted(set(old_t) | set(fp_codes))
    if new_t != old_t:
        _set_nested(cfg, path_trend, new_t)
        added = [c for c in fp_codes if c not in old_t]
        changes.append(
            Change(
                path="trend_slippage_alert.alert_ignore_codes",
                old=old_t,
                new=new_t,
                reason=f"合并最近 {lookback_days} 日内 user_feedback=fp 的代码（{len(added)} 只新增）",
                hit_rate=None,
                samples=len(added),
            )
        )

    path_dd = ("drawdown_alert", "alert_ignore_codes")
    old_d = _normalized_ignore_list(_get_nested(cfg, path_dd))
    new_d = sorted(set(old_d) | set(fp_codes))
    if new_d != old_d:
        _set_nested(cfg, path_dd, new_d)
        added_d = [c for c in fp_codes if c not in old_d]
        changes.append(
            Change(
                path="drawdown_alert.alert_ignore_codes",
                old=old_d,
                new=new_d,
                reason=f"合并最近 {lookback_days} 日内 user_feedback=fp 的代码（{len(added_d)} 只新增）",
                hit_rate=None,
                samples=len(added_d),
            )
        )
    return changes


def _build_mail_body(
    *,
    days: int,
    report: dict[str, Any],
    changes: list[Change],
    config_path: Path,
    backup_path: Path,
) -> str:
    by_type = report.get("by_alert_type") or {}
    lines = [
        f"自动调参完成：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"配置文件：{config_path}",
        f"备份文件：{backup_path}",
        "",
        f"统计窗口：最近 {days} 天（按 anchor_trade_date）",
        "",
        "回测摘要：",
    ]
    for k in ("trend_slip", "drawdown", "risk_stop_take", "strategy"):
        sec = by_type.get(k) or {}
        n = int(sec.get("n", 0) or 0)
        ns = int(sec.get("n_hit_scored", 0) or 0)
        hr = sec.get("hit_rate")
        hrf = hr if isinstance(hr, (int, float)) else None
        if k == "risk_stop_take":
            lines.append(
                f"- {k}: 事件={n}，计分样本={ns}，命中率={_fmt_pct(hrf)}"
            )
        else:
            lines.append(f"- {k}: 样本={n}，命中率={_fmt_pct(hrf)}")
    lines.append("")
    lines.append("参数调整：")
    for ch in changes:
        lines.append(
            f"- {ch.path}: {ch.old} -> {ch.new} "
            f"(命中率={_fmt_pct(ch.hit_rate)}, 样本={ch.samples}, 原因={ch.reason})"
        )
    lines.append("")
    lines.append("如需回滚：")
    lines.append(f"cp {backup_path} {config_path}")
    return "\n".join(lines)


def maybe_send_email(
    *,
    enabled: bool,
    days: int,
    report: dict[str, Any],
    changes: list[Change],
    cfg: dict[str, Any],
    config_path: Path,
    backup_path: Path,
) -> None:
    if not enabled or not changes:
        return
    try:
        from email_notify import send_email_alert
        from run_alert import merge_full_config

        notify_cfg = merge_full_config(copy.deepcopy(cfg))

        subject = f"【自动调参】已调整 {len(changes)} 项参数"
        body = _build_mail_body(
            days=days,
            report=report,
            changes=changes,
            config_path=config_path,
            backup_path=backup_path,
        )
        ok = send_email_alert(
            subject,
            body,
            append_disclaimer=False,
            app_cfg=notify_cfg,
        )
        if ok:
            print("📧 远程通知已发送（邮件/企微见 notifications.remote_channel）。")
        else:
            ok2 = _send_email_from_config_smtp(cfg, subject, body)
            if ok2:
                print("📧 远程通知已发送（config.smtp 兜底）。")
            else:
                print(
                    "⚠️ 远程通知未发送（未配置 mail_config.json / 企微 webhook / config.smtp，或发送失败）。"
                )
    except Exception as exc:
        print(f"⚠️ 邮件发送异常：{exc}")


def _send_email_from_config_smtp(cfg: dict[str, Any], subject: str, body: str) -> bool:
    smtp_cfg = cfg.get("smtp")
    if not isinstance(smtp_cfg, dict):
        return False
    if not bool(smtp_cfg.get("enabled", False)):
        return False
    host = str(smtp_cfg.get("server") or "").strip()
    user = str(smtp_cfg.get("user") or "").strip()
    password = str(smtp_cfg.get("password") or "").strip()
    sender = str(smtp_cfg.get("from") or user).strip()
    to_raw = smtp_cfg.get("to")
    if isinstance(to_raw, list):
        receivers = [str(x).strip() for x in to_raw if str(x).strip()]
    else:
        receivers = [x.strip() for x in str(to_raw or "").split(",") if x.strip()]
    if not (host and user and password and sender and receivers):
        return False
    port = int(_safe_float(smtp_cfg.get("port"), 465))
    starttls = bool(smtp_cfg.get("starttls", False))
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        if starttls:
            server = smtplib.SMTP(host, port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port)
        server.login(user, password)
        server.sendmail(sender, receivers, msg.as_string())
        server.quit()
        return True
    except Exception:
        return False


def print_report(report: dict[str, Any]) -> None:
    print("当前回测统计：")
    by_type = report.get("by_alert_type") or {}
    if not isinstance(by_type, dict) or not by_type:
        print("- 无可用 alert_type 数据")
        return
    for alert_type, sec in sorted(by_type.items()):
        if not isinstance(sec, dict):
            continue
        n = int(sec.get("n", 0) or 0)
        ns = int(sec.get("n_hit_scored", 0) or 0)
        hr = sec.get("hit_rate")
        hrf = float(hr) if isinstance(hr, (int, float)) else None
        if alert_type == "risk_stop_take":
            print(
                f"- {alert_type}: 事件={n}, 计分样本={ns}, 命中率={_fmt_pct(hrf)}"
            )
        else:
            print(f"- {alert_type}: 样本={n}, 命中率={_fmt_pct(hrf)}")


def save_config(config_path: Path, cfg: dict[str, Any]) -> Path:
    backup_path = config_path.with_suffix(".json.bak")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return backup_path


def main() -> int:
    ap = argparse.ArgumentParser(description="根据 backtest 命中率自动调参")
    ap.add_argument("--days", type=int, default=7, help="统计窗口天数，默认 7")
    ap.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config.json",
        help="配置文件路径，默认 ./config.json",
    )
    ap.add_argument("--dry-run", action="store_true", help="仅输出建议，不写回配置")
    ap.add_argument("--email", action="store_true", help="写回后发送邮件通知")
    args = ap.parse_args()

    config_path = args.config.resolve()
    if not config_path.is_file():
        print(f"缺少配置文件: {config_path}", file=sys.stderr)
        return 1

    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"配置文件读取失败: {exc}", file=sys.stderr)
        return 1
    if not isinstance(cfg, dict):
        print("配置文件格式错误：顶层必须为 JSON 对象", file=sys.stderr)
        return 1

    report = run_backtest_report(config_path, int(args.days))
    print_report(report)
    at_sec = cfg.get("auto_tune") if isinstance(cfg.get("auto_tune"), dict) else {}
    fb_days = at_sec.get("feedback_fp_lookback_days")
    if fb_days is None:
        fb_lookback = max(int(args.days), 30)
    else:
        fb_lookback = max(1, int(fb_days))
    fb_changes = merge_fp_user_feedback_into_ignore(cfg, fb_lookback)
    hit_changes = adjust_config(cfg, report)
    grid_changes = _strategy_buy_r1_grid_changes(cfg, int(args.days))
    changes = fb_changes + hit_changes + grid_changes
    if not changes:
        print(
            "✅ 无需调整参数（fp 合并 / 规则调参 / strategy 网格 / 止盈语义均无变更）。"
        )
        return 0

    print("建议调整：")
    for ch in changes:
        print(
            f"- {ch.path}: {ch.old} -> {ch.new} "
            f"(命中率={_fmt_pct(ch.hit_rate)}, 样本={ch.samples})"
        )

    if args.dry_run:
        print("🔍 dry-run 模式：未写入配置。")
        return 0

    # 使用版本管理器记录参数变更
    try:
        from config_version_manager import ConfigVersionManager, ParameterChange

        vm = ConfigVersionManager(config_path)

        # 转换 Change 对象为 ParameterChange
        param_changes = [
            ParameterChange(
                param_path=c.path,
                old_value=c.old,
                new_value=c.new,
                reason=c.reason,
                performance_metric=f"hit_rate: {c.hit_rate:.0%} (n={c.samples})" if c.hit_rate else None,
            )
            for c in changes
        ]

        reason = f"自动调参: {args.days}天回测"
        success, msg = vm.apply_parameter_changes(
            param_changes,
            reason=reason,
            source="auto_tune",
            dry_run=False,
        )

        if success:
            print(f"💾 {msg}")
        else:
            print(f"❌ {msg}")
            return 1

    except ImportError:
        # 版本管理器不可用时降级为旧逻辑
        backup_path = save_config(config_path, cfg)
        print(f"💾 已备份原配置: {backup_path}")
        print(f"✅ 已写回配置: {config_path}")

    print(f"✅ 已写回配置: {config_path}")
    maybe_send_email(
        enabled=bool(args.email),
        days=int(args.days),
        report=report,
        changes=changes,
        cfg=cfg,
        config_path=config_path,
        backup_path=backup_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
