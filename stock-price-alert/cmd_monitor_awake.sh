#!/usr/bin/env bash
# ③ 防睡眠 + 盘中监控（不重复启动盘前选股；选股/同步请先用 ①②）
# 用法: ./cmd_monitor_awake.sh [config.json]
# 等价于: caffeinate -i .venv/bin/python3 run_alert.py -c config.json --skip-daily-select
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python3"
CFG="${1:-config.json}"
if [[ ! -x "$PY" ]]; then
  echo "缺少可执行解释器: ${PY}" >&2
  exit 1
fi
exec caffeinate -i "$PY" "${ROOT}/run_alert.py" -c "$CFG" --skip-daily-select
