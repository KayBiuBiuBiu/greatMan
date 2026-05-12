#!/usr/bin/env python3
"""根据当前星期与时间，提示「一条常驻命令」节奏下此刻该做什么。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


def _parse_hhmm(s: str, default: str) -> time:
    raw = (s or default).strip()
    parts = raw.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return time(h, m)


def _is_cfg_trading_day(cfg_path: Path, d: date) -> bool | None:
    """若 config 提供简单日历则返回是否为交易日；否则 None。"""
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # 常见写法：holidays 列表 或 显式日历（无则跳过）
    holidays = data.get("trading_calendar_holidays") or data.get("holidays")
    if isinstance(holidays, list) and f"{d:%Y-%m-%d}" in {str(x) for x in holidays}:
        return False
    if d.weekday() >= 5:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-c",
        "--config",
        default="config.json",
        help="读取 ops_automation 的 preopen_cutoff_hhmm / after_close_hhmm（缺省用 09:20 / 15:10）",
    )
    ap.add_argument(
        "--tz",
        default="Asia/Shanghai",
        help="时区（默认 Asia/Shanghai）",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    cfg_path = (root / args.config).resolve() if not Path(args.config).is_absolute() else Path(args.config)
    preopen = _parse_hhmm("09:20", "09:20")
    after_close = _parse_hhmm("15:10", "15:10")
    try:
        if cfg_path.is_file():
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            oa = raw.get("ops_automation") or {}
            if isinstance(oa, dict):
                if oa.get("preopen_cutoff_hhmm"):
                    preopen = _parse_hhmm(str(oa["preopen_cutoff_hhmm"]), "09:20")
                if oa.get("after_close_hhmm"):
                    after_close = _parse_hhmm(str(oa["after_close_hhmm"]), "15:10")
    except (OSError, json.JSONDecodeError, ValueError, IndexError):
        pass

    tz = ZoneInfo(args.tz)
    now = datetime.now(tz)
    wd_names = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    wd = wd_names[now.weekday()]

    tday = _is_cfg_trading_day(cfg_path, now.date())
    is_weekday = now.weekday() < 5
    # 无日历配置时：仅按周一至周五粗判「可能是交易日（节假日除外）」
    rough_trading = is_weekday if tday is None else tday

    cmd = f"cd {root} && .venv/bin/python3 run_alert.py -c config.json"

    lines: list[str] = []
    lines.append("=== 此刻指引（约 8 点开机、尽量挂到 18 点以后；法定节假日以交易所为准）===\n")
    lines.append(f"本地时间：{now:%Y-%m-%d}（{wd}） {now:%H:%M}  {tz.key}\n")

    if not is_weekday:
        lines.append("今天周末：日更自动化一般不跑；不炒股可不开进程。\n")
        lines.append("【唯一常驻命令】（若仍想看盘 / 挂机）\n  " + cmd + "\n")
        return print("\n".join(lines)) or 0

    if tday is False:
        lines.append("按当前 config 粗判：今天可能不是交易日（周末或列入休市的日期）。\n")

    lines.append(
        "【只做这一件事】终端里常驻，尽量从早上挂到晚上（不要 15:10 前就关）：\n  " + cmd + "\n"
    )
    lines.append(
        "前提：`ops_automation.enabled` + `preopen_enabled` / `after_close_enabled` 已按你需要打开；"
        f"盘前截止 {preopen:%H:%M}，收盘后任务约 {after_close:%H:%M} 起。\n"
    )

    hm = now.timetz().replace(tzinfo=None)
    # 比较 time
    def before(t1: time, t2: time) -> bool:
        return (t1.hour, t1.minute) < (t2.hour, t2.minute)

    def after_eq(t1: time, t2: time) -> bool:
        return (t1.hour, t1.minute) >= (t2.hour, t2.minute)

    lines.append("【现在该干嘛】")
    if not rough_trading:
        lines.append("- 今天若休市：无需盘前流水线；进程可不开或仅自用看盘。")
        print("\n".join(lines))
        return 0

    if before(hm, time(8, 0)):
        lines.append("- 还不到 8 点：到点后执行上面那条命令并一直挂着。")
    elif after_eq(hm, time(8, 0)) and before(hm, time(9, 0)):
        lines.append(
            "- 8:00～9:00：若**还没**启动 `run_alert`，现在启动；"
            f"务必在 {preopen:%H:%M} 前已常驻，盘前自动任务才会触发。"
        )
    elif after_eq(hm, time(9, 0)) and before(hm, preopen):
        lines.append(
            f"- 9:00～{preopen:%H:%M}：进程应已运行，等待自动「同步日 K → 指标 → 选股」；无需再敲命令。"
        )
    elif after_eq(hm, preopen) and before(hm, time(9, 30)):
        lines.append("- 开盘前片刻：确认进程仍在；9:30 起正常盘中轮询。")
    elif before(hm, time(11, 31)):
        lines.append("- 上午盘中：保持进程运行即可。")
    elif before(hm, time(13, 0)):
        lines.append("- 午休：保持进程运行即可（无需操作）。")
    elif before(hm, time(15, 0)):
        lines.append("- 下午盘中：保持进程运行即可。")
    elif before(hm, after_close):
        lines.append(
            f"- 快收盘：不要关机；{after_close:%H:%M} 后会自动跑收盘后任务（回测/调参等，看你配置）。"
        )
    else:
        lines.append(
            f"- 收盘后（已过 {after_close:%H:%M}）：自动任务应已陆续执行；你 18 点再关电脑一般来得及。"
            " 若白天没挂机，晚上在项目目录补跑 `backtest_alerts` / `auto_tune_accuracy` / 周五的 `ml_train`（见 每日时间与命令对照.md）。"
        )
        if now.weekday() == 4:  # Friday
            lines.append("- 周五：若开了周训练，收盘后还会自动跑 ML 训练（看 config）。")

    lines.append("\n不确定是否交易日：以交易所日历为准；需要可把休市日写进 config 供本脚本粗判。")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
