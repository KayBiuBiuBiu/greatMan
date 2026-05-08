#!/usr/bin/env bash
# 防 Mac 睡眠 + 启动监控（等价于：caffeinate -i .venv/bin/python3 run_alert.py "$@"）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "缺少可执行解释器: ${PY}（请在项目根目录创建 .venv）" >&2
  exit 1
fi
exec caffeinate -i "$PY" "${ROOT}/run_alert.py" "$@"
