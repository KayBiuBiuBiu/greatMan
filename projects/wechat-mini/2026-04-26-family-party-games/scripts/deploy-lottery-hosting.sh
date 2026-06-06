#!/usr/bin/env bash
# 部署聚会抽奖静态页到 CloudBase 静态网站托管
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${CLOUDBASE_ENV_ID:-cloud1-d9g01no7m292bc511-d5e875d}"
TCB="${TCB_CLI:-npx -p @cloudbase/cli@3.4.0 tcb}"
HOST_DIR="$ROOT/hosting/lottery"

if [[ ! -f "$HOST_DIR/index.html" ]]; then
  echo "找不到 $HOST_DIR/index.html" >&2
  exit 1
fi

echo "部署目录: $HOST_DIR"
echo "环境 ID:  $ENV_ID"
$TCB hosting deploy "$HOST_DIR" -e "$ENV_ID"
echo "完成。请在 CloudBase 控制台 → 静态网站托管 查看访问域名。"
