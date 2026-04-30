#!/usr/bin/env python3
"""基于 backtest_alerts 报告自动微调预警准确性参数。"""

from __future__ import annotations

import argparse
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


RULES = {
    "trend_slip": {
        "min_samples": 10,
        "hit_rate_threshold": 0.55,
        "param_path": ("trend_slippage_alert", "min_pillars_weak"),
        "step": 1,
        "max_value": 3,
        "reason": "趋势命中率偏低，提高触发柱数阈值",
    },
    "drawdown": {
        "min_samples": 10,
        "hit_rate_threshold": 0.60,
        "param_path": ("drawdown_alert", "warn_1_ratio"),
        "step": -0.01,
        "min_value": -0.10,
        "reason": "回撤命中率偏低，提高第一档触发严格度",
    },
    "volume_ratio": {
        "min_samples": 20,
        "hit_rate_threshold": 0.55,
        "param_path": ("trend_slippage_alert", "min_volume_ratio"),
        "step": 0.2,
        "max_value": 2.0,
        "reason": "趋势命中率偏低，提高量比过滤阈值",
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


def _trend_changes(cfg: dict[str, Any], by_type: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    ts = by_type.get("trend_slip") or {}
    n = int(ts.get("n", 0) or 0)
    hr = ts.get("hit_rate")
    hrf = float(hr) if isinstance(hr, (int, float)) else None

    # min_pillars_weak
    r = RULES["trend_slip"]
    if n >= int(r["min_samples"]) and hrf is not None and hrf < float(r["hit_rate_threshold"]):
        path = r["param_path"]
        old = int(_safe_float(_get_nested(cfg, path), 2))
        new = min(old + int(r["step"]), int(r["max_value"]))
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

    # min_volume_ratio
    rv = RULES["volume_ratio"]
    if n >= int(rv["min_samples"]) and hrf is not None and hrf < float(rv["hit_rate_threshold"]):
        path_v = rv["param_path"]
        old_v = _safe_float(_get_nested(cfg, path_v), 0.0)
        new_v = min(old_v + float(rv["step"]), float(rv["max_value"]))
        new_v = round(new_v, 4)
        if new_v != old_v:
            _set_nested(cfg, path_v, new_v)
            changes.append(
                Change(
                    path=".".join(path_v),
                    old=old_v,
                    new=new_v,
                    reason=str(rv["reason"]),
                    hit_rate=hrf,
                    samples=n,
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
    changes.extend(_trend_changes(cfg, by_type))
    changes.extend(_drawdown_changes(cfg, by_type))
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
    for k in ("trend_slip", "drawdown"):
        sec = by_type.get(k) or {}
        n = int(sec.get("n", 0) or 0)
        hr = sec.get("hit_rate")
        lines.append(f"- {k}: 样本={n}，命中率={_fmt_pct(hr if isinstance(hr, (int, float)) else None)}")
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
            app_cfg=None,
        )
        if ok:
            print("📧 邮件通知已发送。")
        else:
            ok2 = _send_email_from_config_smtp(cfg, subject, body)
            if ok2:
                print("📧 邮件通知已发送（config.smtp）。")
            else:
                print("⚠️ 邮件未发送（未配置 mail_config.json / 环境变量 / config.smtp，或发送失败）。")
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
        hr = sec.get("hit_rate")
        hrf = float(hr) if isinstance(hr, (int, float)) else None
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
    changes = adjust_config(cfg, report)
    if not changes:
        print("✅ 无需调整参数。")
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

    backup_path = save_config(config_path, cfg)
    print(f"💾 已备份原配置: {backup_path}")
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
