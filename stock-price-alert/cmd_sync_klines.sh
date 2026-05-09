#!/usr/bin/env bash
# ② 日 K 同步到本地 SQLite（watchlist + daily_picks 优质池等，见 kline_store 配置）
# 用法: ./cmd_sync_klines.sh [config.json]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python3"
CFG="${1:-config.json}"
if [[ ! -x "$PY" ]]; then
  echo "缺少可执行解释器: ${PY}" >&2
  exit 1
fi
exec "$PY" "${ROOT}/sync_daily_klines.py" -c "$CFG"
