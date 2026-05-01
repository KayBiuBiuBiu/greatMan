#!/usr/bin/env python3
"""外部心跳巡检：若 data_health 写入的心跳文件过旧或缺失，则发邮件。

复用 email_notify.send_email_alert（mail_config.json / MAIL_*）。

crontab 示例（每 5 分钟）::

    */5 * * * * cd /ABS/PATH/stock-price-alert && .venv/bin/python3 check_heartbeat_mail.py -c config.json >>logs/heartbeat_cron.log 2>&1

未配置 heartbeat_path 时直接退出 0（不检查、不发信）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _resolve_heartbeat(
    cfg: dict[str, Any], root: Path
) -> tuple[Path | None, float]:
    dh = cfg.get("data_health") or {}
    hp = str(dh.get("heartbeat_path") or "").strip()
    if not hp:
        return None, 0.0
    try:
        iv = float(dh.get("heartbeat_interval_sec", 0) or 0)
    except (TypeError, ValueError):
        iv = 0.0
    p = Path(hp)
    if not p.is_absolute():
        p = root / p
    return p.resolve(), iv


def _default_max_age_sec(interval_sec: float) -> float:
    if interval_sec > 0:
        return max(300.0, interval_sec * 2.0 + 120.0)
    return 900.0


def _parse_ts_iso(payload: dict[str, Any]) -> datetime | None:
    s = payload.get("ts_iso")
    if not s or not isinstance(s, str):
        return None
    s = s.strip()[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _state_path(root: Path) -> Path:
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / ".heartbeat_stale_mail.json"


def _cooldown_ok(state_file: Path, cooldown_sec: float) -> bool:
    """True 表示仍在冷却期，不应再发。"""
    if cooldown_sec <= 0 or not state_file.is_file():
        return False
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
        last = float(st.get("last_sent_epoch", 0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return (time.time() - last) < cooldown_sec


def _mark_sent(state_file: Path, reason: str) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "last_sent_epoch": time.time(),
                "reason": reason[:800],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _send_stale_alert(
    cfg: dict[str, Any],
    reason: str,
    *,
    state_file: Path,
    cooldown_sec: float,
    dry_run: bool,
) -> int:
    if dry_run:
        print(f"[heartbeat-mail][dry-run] 将发送: {reason}", file=sys.stderr)
        return 0
    if _cooldown_ok(state_file, cooldown_sec):
        print(
            f"[heartbeat-mail] 命中问题但仍在邮件冷却期内（{cooldown_sec:.0f}s），跳过发送。",
            file=sys.stderr,
        )
        return 0
    from email_notify import send_email_alert

    body = (
        f"{reason}\n\n"
        "请检查：run_alert 是否在跑、机器是否休眠、监控池是否为空、网络/行情源是否正常。"
    )
    ok = send_email_alert(
        "[股价监控] 心跳超时或异常",
        body,
        append_disclaimer=True,
        app_cfg=cfg,
    )
    if ok:
        _mark_sent(state_file, reason)
        print("[heartbeat-mail] 已发送告警邮件。", file=sys.stderr)
        return 0
    print(
        "[heartbeat-mail] 发送失败（未配置 SMTP 或网络错误）。",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="检查 data_health 心跳文件并发邮件")
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument(
        "--max-age-sec",
        type=float,
        default=None,
        help="允许的最长心跳年龄（秒）；默认约为 2×heartbeat_interval_sec+120，且不少于 300",
    )
    ap.add_argument(
        "--cooldown-sec",
        type=float,
        default=1800.0,
        help="同类邮件最短间隔（秒），默认 1800",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印判定结果，不发邮件、不写冷却状态",
    )
    args = ap.parse_args()

    if not args.config.is_file():
        print(f"缺少配置: {args.config}", file=sys.stderr)
        return 2

    raw = json.loads(args.config.read_text(encoding="utf-8"))
    from run_alert import merge_full_config

    cfg = merge_full_config(raw)
    hb_path, interval_sec = _resolve_heartbeat(cfg, ROOT)
    if hb_path is None:
        print("[heartbeat-mail] data_health.heartbeat_path 未配置，跳过检查。")
        return 0

    max_age = (
        float(args.max_age_sec)
        if args.max_age_sec is not None
        else _default_max_age_sec(interval_sec)
    )
    state_file = _state_path(ROOT)

    if not hb_path.is_file():
        return _send_stale_alert(
            cfg,
            f"心跳文件不存在: {hb_path}",
            state_file=state_file,
            cooldown_sec=float(args.cooldown_sec),
            dry_run=bool(args.dry_run),
        )

    try:
        payload = json.loads(hb_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return _send_stale_alert(
            cfg,
            f"心跳文件无法解析为 JSON 对象: {hb_path} ({e})",
            state_file=state_file,
            cooldown_sec=float(args.cooldown_sec),
            dry_run=bool(args.dry_run),
        )

    ts = _parse_ts_iso(payload)
    if ts is None:
        return _send_stale_alert(
            cfg,
            f"心跳缺少可解析的 ts_iso: {hb_path} keys={list(payload.keys())[:8]}",
            state_file=state_file,
            cooldown_sec=float(args.cooldown_sec),
            dry_run=bool(args.dry_run),
        )

    age_sec = (datetime.now() - ts).total_seconds()
    if age_sec <= max_age:
        print(
            f"[heartbeat-mail] OK age={age_sec:.0f}s max={max_age:.0f}s path={hb_path}"
        )
        return 0

    return _send_stale_alert(
        cfg,
        f"心跳过旧: age={age_sec:.0f}s > max={max_age:.0f}s "
        f"ts_iso={payload.get('ts_iso')!r} path={hb_path}",
        state_file=state_file,
        cooldown_sec=float(args.cooldown_sec),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
