#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_config_thresholds.py — 汇总并检查「合并后」配置里的各类阈值
============================================================

干什么
----
  读入你的 JSON 配置，调用与 run_alert 相同的 merge_full_config（会补全默认值，
  并走 config_schema.json 校验）。然后按模块打印阈值快照；可选导出扁平 JSON、
  可选做 Schema 之外的常识检查（--strict）。

为什么需要
----
  config.json 往往只写覆盖项，真正生效的是「合并后」的数值；本脚本避免你对着
  手写片段猜当前阈值。适合改完配置、发版前、或 cron 每日扫一眼。

前提
----
  - Python 能 import 同目录下的 run_alert（脚本已把 ROOT 加入 sys.path）。
  - 配置文件须能通过 merge_full_config（与启动 run_alert 一致）；否则进程会直接退出。

路径规则（重要）
--------------
  ``-c`` 与 ``--json-out`` 若写成**相对路径**，一律相对于**本脚本所在目录**
  （即 stock-price-alert 项目根，与 ``run_alert.py`` 同级），**不**随你当前 shell 的
  ``cd`` 改变。这样 cron 里即使未先 ``cd``，``-c config.json``、
  ``--json-out logs/thresholds.json`` 仍指向项目内文件。
  若要用任意目录下的文件，请传**绝对路径**。

怎么用（命令行）
--------------
  # 打印人类可读快照（默认读当前目录下的 config.json）
  python3 check_config_thresholds.py

  # 指定配置文件
  python3 check_config_thresholds.py -c /path/to/config.json

  # 同时写出扁平 JSON，便于和历史文件 diff（如 git 或 cp 昨日文件后 diff）
  python3 check_config_thresholds.py -c config.json --json-out logs/thresholds_snapshot.json

  # 开启额外合理性检查；有问题打印到 stderr 且 exit code = 1（适合监控/cron 报警）
  python3 check_config_thresholds.py -c config.json --strict

  # 查看全部参数说明
  python3 check_config_thresholds.py --help

定时任务示例（cron，按你本机路径改）
------------------------------------
  # 可用绝对路径调用脚本；相对 -c / --json-out 已相对项目根，可不先 cd
  15 9 * * 1-5 /usr/bin/python3 /path/to/stock-price-alert/check_config_thresholds.py -c config.json --strict

退出码
------
  0  成功（含 --strict 通过）
  1  --strict 发现常识性问题
  2  配置文件不存在或无法读取
  其它  merge / Schema 校验失败时由 run_alert 侧 exit（与直接跑 run_alert 一致）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 本脚本所在目录 = stock-price-alert 根（与 run_alert.py 同级）
ROOT = Path(__file__).resolve().parent


def _resolve_project_path(p: Path) -> Path:
    """
    绝对路径：原样 resolve。
    相对路径：相对 ROOT（项目根），避免依赖当前工作目录。
    """
    p = Path(p)
    if p.is_absolute():
        return p.resolve()
    return (ROOT / p).resolve()


def _load_merged_config(path: Path) -> dict[str, Any]:
    """读取 JSON 并 merge_full_config；失败时与主程序一致地退出。"""
    if not path.is_file():
        print(f"[错误] 找不到配置文件: {path}", file=sys.stderr)
        raise SystemExit(2)
    raw = json.loads(path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT))
    from run_alert import merge_full_config

    return merge_full_config(dict(raw))


def _fmt_val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:g}"
    if v is None:
        return "null"
    return str(v)


def _walk(prefix: str, obj: Any, out: list[tuple[str, str]]) -> None:
    """深度优先遍历 dict/list，叶子节点记为「点分路径 = 值」（便于阅读与 diff）。"""
    if isinstance(obj, dict):
        for k in sorted(obj.keys(), key=lambda x: str(x)):
            _walk(f"{prefix}.{k}" if prefix else str(k), obj[k], out)
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            _walk(f"{prefix}[{i}]", it, out)
    else:
        out.append((prefix, _fmt_val(obj)))


def _section_report(cfg: dict[str, Any], section: str) -> list[tuple[str, str]]:
    """导出某一顶层键（或标量键）下的所有叶子路径。"""
    rows: list[tuple[str, str]] = []
    sub = cfg.get(section)
    if sub is None:
        return rows
    _walk(section, sub, rows)
    return rows


# 控制台分组顺序：与业务阅读顺序大致一致；未在 cfg 中出现的键会自动跳过
_REPORT_SECTIONS: list[tuple[str, list[str]]] = [
    ("轮询与提醒", ["poll_interval_seconds", "trading_closed_interval", "alert_cooldown_minutes", "alert_price_buffer", "run_only_in_trading_hours"]),
    ("资金与下单", ["capital", "buy_rule", "risk_rule"]),
    ("回撤预警", ["drawdown_alert"]),
    ("趋势下滑", ["trend_slippage_alert"]),
    ("策略分与买入过滤", ["strategy_signal", "strategy_buy_filter"]),
    ("仓位建议", ["position_suggestion"]),
    ("选股阈值", ["quant_selector", "scan_rule"]),
    ("预警库与回测评估", ["alert_log"]),
    ("ML 过滤", ["ml_filter"]),
    ("自动调参", ["auto_tune"]),
    ("性能与 Hub", ["performance", "realtime_hub"]),
    ("运维自动化", ["ops_automation"]),
    ("数据健康", ["data_health"]),
]


def _print_report(cfg: dict[str, Any]) -> None:
    """按分组打印；单组超过 400 行时提示用 --json-out 看全量。"""
    sections = _REPORT_SECTIONS
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"=== config 阈值快照（合并默认值后）=== 生成: {now}\n")
    for title, keys in sections:
        print(f"## {title}")
        for k in keys:
            if k not in cfg:
                continue
            rows = _section_report(cfg, k)
            if not rows:
                continue
            print(f"  [{k}]")
            for path, val in rows[:400]:
                print(f"    {path} = {val}")
            if len(rows) > 400:
                print(f"    … 另有 {len(rows) - 400} 行，请用 --json-out 查看完整")
        print()


def _strict_checks(cfg: dict[str, Any]) -> list[str]:
    """
    Schema 已校验类型；这里只做「业务上容易写反」的检查。
    返回非空列表表示应视为失败（配合 --strict 与 exit 1）。
    """
    issues: list[str] = []

    sbf = cfg.get("strategy_buy_filter") or {}
    if isinstance(sbf, dict):
        mn = float(sbf.get("min_intraday_position", 0) or 0)
        mx = float(sbf.get("max_intraday_position", 1) or 1)
        if not (0.0 <= mn <= 1.0):
            issues.append(f"strategy_buy_filter.min_intraday_position 应在 [0,1]，当前 {mn}")
        if not (0.0 <= mx <= 1.0):
            issues.append(f"strategy_buy_filter.max_intraday_position 应在 [0,1]，当前 {mx}")
        if mn > mx + 1e-9:
            issues.append(
                f"strategy_buy_filter: min_intraday_position ({mn}) > max ({mx})，区间矛盾"
            )
        mvr = float(sbf.get("min_volume_ratio", 0) or 0)
        if mvr < 0:
            issues.append(f"strategy_buy_filter.min_volume_ratio 不应为负，当前 {mvr}")

    mf = cfg.get("ml_filter") or {}
    if isinstance(mf, dict) and bool(mf.get("enabled")):
        th = float(mf.get("bearish_prob_threshold", 0.5) or 0.5)
        if not (0.0 < th < 1.0):
            issues.append(f"ml_filter.bearish_prob_threshold 建议在 (0,1)，当前 {th}")
        kth = float(mf.get("kline_rf_suppress_below", 0.3) or 0.3)
        if not (0.0 < kth < 1.0):
            issues.append(f"ml_filter.kline_rf_suppress_below 建议在 (0,1)，当前 {kth}")

    dda = cfg.get("drawdown_alert") or {}
    if isinstance(dda, dict) and bool(dda.get("enabled", True)):
        w1 = float(dda.get("warn_1_ratio", 0) or 0)
        w2 = float(dda.get("warn_2_ratio", 0) or 0)
        w3 = float(dda.get("warn_3_ratio", 0) or 0)
        if not (w1 >= w2 >= w3):
            issues.append(
                f"drawdown_alert: 建议 warn_1_ratio ≥ warn_2 ≥ warn_3（越负越深），"
                f"当前 {w1}, {w2}, {w3}"
            )

    rr = cfg.get("risk_rule") or {}
    if isinstance(rr, dict):
        sl = float(rr.get("stop_loss_ratio", 0) or 0)
        if sl > 0:
            issues.append(f"risk_rule.stop_loss_ratio 一般为负数，当前 {sl}")

    cap = cfg.get("capital") or {}
    if isinstance(cap, dict):
        mt = float(cap.get("max_total_position_ratio", 0) or 0)
        ms = float(cap.get("max_single_stock_ratio", 0) or 0)
        if not (0.0 <= mt <= 1.0):
            issues.append(f"capital.max_total_position_ratio 应在 [0,1]，当前 {mt}")
        if not (0.0 <= ms <= 1.0):
            issues.append(f"capital.max_single_stock_ratio 应在 [0,1]，当前 {ms}")
        if ms > mt + 1e-9:
            issues.append(
                f"capital: max_single_stock_ratio ({ms}) > max_total_position_ratio ({mt}) 可能不合理"
            )

    ts = cfg.get("trend_slippage_alert") or {}
    if isinstance(ts, dict):
        da = ts.get("dynamic_adaptive")
        if isinstance(da, dict) and bool(da.get("enabled")):
            for name in (
                "strong_bull_min_pillars",
                "range_min_pillars",
                "weak_bear_min_pillars",
            ):
                v = int(da.get(name, 2) or 2)
                if not (1 <= v <= 4):
                    issues.append(f"trend_slippage_alert.dynamic_adaptive.{name} 应在 1～4，当前 {v}")

    qs = cfg.get("quant_selector") or {}
    if isinstance(qs, dict):
        sq = float(qs.get("score_min_quality", 0) or 0)
        sw = float(qs.get("score_min_watch", 0) or 0)
        if sq < sw:
            issues.append(
                f"quant_selector: score_min_quality ({sq}) < score_min_watch ({sw})，请确认是否故意"
            )

    return issues


def _full_flat(cfg: dict[str, Any]) -> dict[str, Any]:
    """整棵合并后配置压成 { 'a.b.c': '值字符串', ... }，方便机器 diff。"""
    rows: list[tuple[str, str]] = []
    _walk("", cfg, rows)
    return {k: v for k, v in rows}


def main() -> int:
    epilog = """
示例:
  %(prog)s
  %(prog)s -c config.json
  %(prog)s -c config.json --json-out logs/thresholds.json
  %(prog)s -c config.json --strict
"""
    ap = argparse.ArgumentParser(
        description="检查 merge_full_config 后的阈值快照（可定期执行）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    ap.add_argument(
        "-c",
        "--config",
        type=Path,
        default=ROOT / "config.json",
        help="配置文件；默认 <项目根>/config.json。相对路径相对项目根，非当前 shell 目录",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="可选。输出 JSON 路径；相对路径相对项目根（同上）",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="可选。启用额外常识校验；失败时向 stderr 打印原因并以退出码 1 结束",
    )
    args = ap.parse_args()

    config_path = _resolve_project_path(args.config)

    # 1) 合并 + Schema（失败则直接退出，与 run_alert 启动前一致）
    cfg = _load_merged_config(config_path)
    # 2) 人类可读分组输出
    _print_report(cfg)

    if args.json_out:
        out_path = _resolve_project_path(args.json_out)
        payload = {
            "generated_iso_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": str(config_path),
            "flat": _full_flat(cfg),
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[写入] {out_path}")

    # 3) 可选：常识检查（不替代 Schema）
    if args.strict:
        bad = _strict_checks(cfg)
        if bad:
            print("=== --strict 发现问题 ===", file=sys.stderr)
            for b in bad:
                print(f"  - {b}", file=sys.stderr)
            return 1
        print("=== --strict 检查通过 ===")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
