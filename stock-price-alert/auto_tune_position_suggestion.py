#!/usr/bin/env python3
"""
根据 backtest_position_suggestion replay 的「卖出」命中率，自动微调
position_suggestion.rules.sell 中的数值阈值；达标或步进用尽后停止。

用法:
    python auto_tune_position_suggestion.py -c config.json --target-hit-rate 0.55 --max-iter 5
    python auto_tune_position_suggestion.py -c config.json --auto-range --dry-run

建议由 cron 仅在周末执行；长区间回测可配合 --max-iter 限制次数。
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_alert import merge_full_config

# 单轮内依次尝试的卖出规则调优方向：减少「偏早卖出」以提高 T+5 命中（略收紧触发）
DEFAULT_STEPS: list[tuple[str, float]] = [
    ("profit_to_take", 0.02),
    ("bearish_prob_threshold", 0.05),
    ("box_high_threshold", 0.03),
    ("volume_ratio_low", -0.05),
]

CLAMP: dict[str, tuple[float, float]] = {
    "profit_to_take": (0.05, 0.30),
    "bearish_prob_threshold": (0.50, 0.95),
    "box_high_threshold": (0.70, 0.95),
    "volume_ratio_low": (0.30, 1.20),
}


@dataclass
class TuneRecord:
    iteration: int
    key: str
    delta: float
    old_val: float
    new_val: float
    hit_before: float | None
    hit_after: float | None
    n_scored_before: int
    n_scored_after: int
    accepted: bool


@dataclass
class TuneReport:
    initial_hit: float | None
    final_hit: float | None
    initial_n_scored: int
    final_n_scored: int
    target: float
    backup_path: Path | None
    config_path: Path
    since: str
    until: str
    records: list[TuneRecord] = field(default_factory=list)
    diagnostics_tail: dict[str, Any] = field(default_factory=dict)


def _safe_float(x: Any, default: float) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _sell_rules(cfg: dict[str, Any]) -> dict[str, Any]:
    ps = cfg.setdefault("position_suggestion", {})
    if not isinstance(ps, dict):
        ps = {}
        cfg["position_suggestion"] = ps
    rules = ps.setdefault("rules", {})
    if not isinstance(rules, dict):
        rules = {}
        ps["rules"] = rules
    sell = rules.setdefault("sell", {})
    if not isinstance(sell, dict):
        sell = {}
        rules["sell"] = sell
    return sell


def _kline_span(cfg_path: Path) -> tuple[str | None, str | None]:
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    merged = merge_full_config(copy.deepcopy(raw))
    ks = merged.get("kline_store") or {}
    rel = str(ks.get("db_path") or "data/daily_klines.db").strip()
    dbp = Path(rel)
    if not dbp.is_absolute():
        dbp = ROOT / dbp
    if not dbp.is_file():
        return None, None
    conn = sqlite3.connect(str(dbp))
    try:
        row = conn.execute(
            "SELECT MIN(trade_date), MAX(trade_date) FROM daily_klines"
        ).fetchone()
        if not row or row[0] is None:
            return None, None
        return str(row[0])[:10], str(row[1])[:10]
    finally:
        conn.close()


def _write_cfg(path: Path, cfg: dict[str, Any]) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_replay(
    cfg_path: Path,
    *,
    since: str,
    until: str,
    min_bars: int,
    codes: str,
) -> dict[str, Any]:
    fd, out_s = tempfile.mkstemp(suffix=".json", prefix="ps_replay_")
    os.close(fd)
    out = Path(out_s)
    try:
        cmd = [
            sys.executable,
            str(ROOT / "backtest_position_suggestion.py"),
            "-c",
            str(cfg_path),
            "replay",
            "--since",
            since[:10],
            "--until",
            until[:10],
            "--min-bars",
            str(int(min_bars)),
            "--json-out",
            str(out),
        ]
        if codes.strip():
            cmd.extend(["--codes", codes.strip()])
        cp = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if cp.returncode != 0:
            err = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(err or f"exit {cp.returncode}")
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass


def parse_sell_metrics(data: dict[str, Any]) -> tuple[float | None, int, int]:
    sell = (data.get("by_action") or {}).get("卖出") or {}
    hr = sell.get("hit_rate")
    hrf: float | None
    if isinstance(hr, (int, float)):
        hrf = float(hr)
    else:
        hrf = None
    n_scored = int(sell.get("n_scored") or 0)
    n_days = int(sell.get("n_days") or 0)
    return hrf, n_scored, n_days


def apply_one_delta(
    cfg: dict[str, Any], key: str, delta: float
) -> tuple[float, float, bool]:
    """
    修改 sell[key] += delta 并钳制。返回 (old, new, changed)。
    """
    sell = _sell_rules(cfg)
    defaults = {
        "profit_to_take": 0.15,
        "bearish_prob_threshold": 0.7,
        "box_high_threshold": 0.85,
        "volume_ratio_low": 0.8,
    }
    old = _safe_float(sell.get(key, defaults.get(key, 0.0)), defaults[key])
    new = old + float(delta)
    lo, hi = CLAMP[key]
    new = max(lo, min(hi, new))
    new = round(new, 6)
    if new == old:
        return old, new, False
    sell[key] = new
    return old, new, True


def _fmt_hit(x: float | None) -> str:
    if x is None:
        return "N/A"
    return f"{x:.2%}"


def maybe_send_email(report: TuneReport, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        from email_notify import send_email_alert
    except ImportError:
        print("无法导入 email_notify，跳过邮件。", file=sys.stderr)
        return

    lines = [
        f"仓位建议卖出规则自动调优 — {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"配置: {report.config_path}",
        f"备份: {report.backup_path or '（未备份）'}",
        f"回测区间: {report.since} ~ {report.until}",
        f"目标命中率: {report.target:.2%}",
        "",
        f"初始: hit={_fmt_hit(report.initial_hit)} n_scored={report.initial_n_scored}",
        f"最终: hit={_fmt_hit(report.final_hit)} n_scored={report.final_n_scored}",
        "",
        "调整记录:",
    ]
    for r in report.records:
        lines.append(
            f"  iter{r.iteration} {r.key} {r.old_val:g}->{r.new_val:g} (Δ{r.delta:g}) "
            f"hit {_fmt_hit(r.hit_before)}->{_fmt_hit(r.hit_after)} "
            f"scored {r.n_scored_before}->{r.n_scored_after} "
            f"{'✓' if r.accepted else '✗'}"
        )
    if report.diagnostics_tail:
        lines.append("")
        lines.append("末次 diagnostics.hints:")
        for h in report.diagnostics_tail.get("hints") or []:
            lines.append(f"  - {h}")
    body = "\n".join(lines)
    app_cfg = None
    try:
        if report.config_path.is_file():
            raw = json.loads(report.config_path.read_text(encoding="utf-8"))
            app_cfg = merge_full_config(raw)
    except Exception:
        pass
    ok = send_email_alert(
        "【自动调优】仓位建议 卖出规则",
        body,
        append_disclaimer=False,
        app_cfg=app_cfg,
    )
    if ok:
        print("远程通知已发送（邮件/企微见 notifications.remote_channel）。")
    else:
        print(
            "远程通知未发送（未配置 mail_config.json / 企微 webhook，或发送失败）。",
            file=sys.stderr,
        )


def run_tune(args: argparse.Namespace) -> int:
    config_path: Path = args.config.expanduser().resolve()
    if not config_path.is_file():
        print(f"缺少配置: {config_path}", file=sys.stderr)
        return 1

    since = str(args.since or "").strip()
    until = str(args.until or "").strip()
    if args.auto_range or not since or not until:
        db_min, db_max = _kline_span(config_path)
        if db_min is None or db_max is None:
            print("无法从 kline_store 解析日K库或库为空，请显式指定 --since/--until。", file=sys.stderr)
            return 1
        since = since or db_min
        until = until or db_max
        print(f"使用日K库覆盖区间: {since} ~ {until}")

    base_cfg = json.loads(config_path.read_text(encoding="utf-8"))

    work_path = config_path
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.dry_run:
        tmp_dir = tempfile.TemporaryDirectory(prefix="ps_autotune_")
        work_path = Path(tmp_dir.name) / "config.json"
        _write_cfg(work_path, copy.deepcopy(base_cfg))

    try:
        return _run_tune_core(
            args,
            config_path=config_path,
            work_path=work_path,
            base_cfg=base_cfg,
            since=since,
            until=until,
        )
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()


def _run_tune_core(
    args: argparse.Namespace,
    *,
    config_path: Path,
    work_path: Path,
    base_cfg: dict[str, Any],
    since: str,
    until: str,
) -> int:
    initial_data = run_replay(
        work_path,
        since=since,
        until=until,
        min_bars=args.min_bars,
        codes=args.codes,
    )
    init_hit, init_scored, init_days = parse_sell_metrics(initial_data)
    hints0 = (initial_data.get("diagnostics") or {}).get("hints") or []

    report = TuneReport(
        initial_hit=init_hit,
        final_hit=init_hit,
        initial_n_scored=init_scored,
        final_n_scored=init_scored,
        target=float(args.target_hit_rate),
        backup_path=None,
        config_path=config_path,
        since=since[:10],
        until=until[:10],
        diagnostics_tail=initial_data.get("diagnostics") or {},
    )

    print(
        f"初始卖出: hit={_fmt_hit(init_hit)} n_scored={init_scored} n_days={init_days}"
    )
    if hints0:
        for h in hints0:
            print(f"  提示: {h}")

    if init_scored < int(args.min_scored_sell):
        print(
            f"卖出可评分样本 n_scored={init_scored} < {args.min_scored_sell}，不进行调参。",
            file=sys.stderr,
        )
        maybe_send_email(report, enabled=bool(args.email))
        return 2

    if init_hit is not None and init_hit >= report.target:
        print("已达到目标命中率，跳过调整。")
        maybe_send_email(report, enabled=bool(args.email))
        return 0

    if not args.dry_run and not args.no_backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = config_path.with_suffix(config_path.suffix + f".auto_tune_{ts}.bak")
        shutil.copy2(config_path, bak)
        report.backup_path = bak
        print(f"已备份: {bak}")

    if args.dry_run:
        best_cfg = json.loads(work_path.read_text(encoding="utf-8"))
    else:
        best_cfg = json.loads(config_path.read_text(encoding="utf-8"))

    best_hit, best_scored = init_hit, init_scored
    steps = _steps_from_args(args)

    for it in range(int(args.max_iter)):
        if best_hit is not None and best_hit >= report.target:
            break
        round_improved = False
        for key, delta in steps:
            trial = copy.deepcopy(best_cfg)
            old_v, new_v, changed = apply_one_delta(trial, key, delta)
            if not changed:
                continue
            _write_cfg(work_path, trial)
            try:
                data = run_replay(
                    work_path,
                    since=since,
                    until=until,
                    min_bars=args.min_bars,
                    codes=args.codes,
                )
            except RuntimeError as exc:
                print(f"回测失败: {exc}", file=sys.stderr)
                rec = TuneRecord(
                    iteration=it + 1,
                    key=key,
                    delta=delta,
                    old_val=old_v,
                    new_val=new_v,
                    hit_before=best_hit,
                    hit_after=None,
                    n_scored_before=best_scored,
                    n_scored_after=best_scored,
                    accepted=False,
                )
                report.records.append(rec)
                continue

            new_hit, new_scored, _ = parse_sell_metrics(data)
            accept = False
            if new_hit is not None:
                if best_hit is None or new_hit > best_hit:
                    accept = True
                elif new_hit == best_hit and new_scored > best_scored:
                    accept = True

            rec = TuneRecord(
                iteration=it + 1,
                key=key,
                delta=delta,
                old_val=old_v,
                new_val=new_v,
                hit_before=best_hit,
                hit_after=new_hit,
                n_scored_before=best_scored,
                n_scored_after=new_scored,
                accepted=accept,
            )
            report.records.append(rec)
            tag = "保留" if accept else "回滚"
            print(
                f"[iter {it + 1}] {key} {old_v:g}→{new_v:g} | "
                f"hit {_fmt_hit(best_hit)}→{_fmt_hit(new_hit)} | {tag}"
            )

            if accept:
                best_cfg = trial
                best_hit, best_scored = new_hit, new_scored
                report.diagnostics_tail = data.get("diagnostics") or {}
                round_improved = True
                if not args.dry_run:
                    _write_cfg(config_path, best_cfg)
                if best_hit is not None and best_hit >= report.target:
                    break

        if not round_improved:
            print(f"第 {it + 1} 轮无任何改进，停止。")
            break

    report.final_hit = best_hit
    report.final_n_scored = best_scored

    if args.dry_run:
        print("\n[dry-run] 未写入正式 config.json。最优参数相对初始的差异：")
        b_sell = _sell_rules(best_cfg)
        a_sell = _sell_rules(copy.deepcopy(base_cfg))
        for k in CLAMP:
            if _safe_float(b_sell.get(k), float("nan")) != _safe_float(
                a_sell.get(k), float("nan")
            ):
                print(f"  {k}: {a_sell.get(k)} -> {b_sell.get(k)}")
    else:
        _write_cfg(config_path, best_cfg)
        print(f"\n已写入最终配置: {config_path} hit={_fmt_hit(best_hit)}")

    rep_path = args.json_report
    if rep_path:
        p = Path(rep_path)
        p.write_text(
            json.dumps(_report_to_json(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"调整记录 JSON: {p}")

    maybe_send_email(report, enabled=bool(args.email))

    return 0


def _report_to_json(r: TuneReport) -> dict[str, Any]:
    return {
        "initial_hit": r.initial_hit,
        "final_hit": r.final_hit,
        "initial_n_scored": r.initial_n_scored,
        "final_n_scored": r.final_n_scored,
        "target": r.target,
        "backup_path": str(r.backup_path) if r.backup_path else None,
        "config_path": str(r.config_path),
        "since": r.since,
        "until": r.until,
        "diagnostics_tail": r.diagnostics_tail,
        "records": [
            {
                "iteration": x.iteration,
                "key": x.key,
                "delta": x.delta,
                "old_val": x.old_val,
                "new_val": x.new_val,
                "hit_before": x.hit_before,
                "hit_after": x.hit_after,
                "n_scored_before": x.n_scored_before,
                "n_scored_after": x.n_scored_after,
                "accepted": x.accepted,
            }
            for x in r.records
        ],
    }


def _steps_from_args(args: argparse.Namespace) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    if args.step_profit != 0:
        out.append(("profit_to_take", float(args.step_profit)))
    if args.step_ml != 0:
        out.append(("bearish_prob_threshold", float(args.step_ml)))
    if args.step_box != 0:
        out.append(("box_high_threshold", float(args.step_box)))
    if args.step_vol != 0:
        out.append(("volume_ratio_low", float(args.step_vol)))
    return out if out else list(DEFAULT_STEPS)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="自动调优 position_suggestion.rules.sell（基于 replay 卖出命中率）"
    )
    ap.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    ap.add_argument("--target-hit-rate", type=float, default=0.55)
    ap.add_argument("--max-iter", type=int, default=5, help="外层轮数，每轮遍历所有步长")
    ap.add_argument("--since", type=str, default="", help="回测起始（可配合 --auto-range）")
    ap.add_argument("--until", type=str, default="", help="回测结束")
    ap.add_argument(
        "--auto-range",
        action="store_true",
        help="从 kline_store 日K库取 MIN/MAX trade_date 作为默认区间",
    )
    ap.add_argument("--min-bars", type=int, default=60)
    ap.add_argument("--codes", type=str, default="", help="传给 replay 的 --codes")
    ap.add_argument(
        "--min-scored-sell",
        type=int,
        default=5,
        help="卖出 n_scored 低于此值则不调参",
    )
    ap.add_argument("--dry-run", action="store_true", help="不写 config，仅打印试算结果")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--email", action="store_true", help="结束后尝试发送邮件摘要")
    ap.add_argument(
        "--json-report",
        type=str,
        default="",
        help="将调整记录写入该路径（JSON）",
    )
    ap.add_argument(
        "--step-profit",
        type=float,
        default=0.02,
        help="profit_to_take 每步增量；置 0 可跳过该维度",
    )
    ap.add_argument("--step-ml", type=float, default=0.05)
    ap.add_argument("--step-box", type=float, default=0.03)
    ap.add_argument("--step-vol", type=float, default=-0.05)
    args = ap.parse_args()
    return run_tune(args)


if __name__ == "__main__":
    raise SystemExit(main())
