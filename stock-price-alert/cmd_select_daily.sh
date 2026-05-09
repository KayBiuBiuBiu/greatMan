#!/usr/bin/env bash
# ① 盘前量化选股 → daily_picks.json（不触发日 K 入库；与 cmd_sync_klines.sh 拆分）
# 用法: ./cmd_select_daily.sh [config.json]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python3"
CFG="${1:-config.json}"
if [[ ! -x "$PY" ]]; then
  echo "缺少可执行解释器: ${PY}" >&2
  exit 1
fi
exec "$PY" "${ROOT}/run_alert.py" -c "$CFG" --daily-select --no-sync-after-select
