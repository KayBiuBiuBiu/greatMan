#!/usr/bin/env bash
# 部署 hostAgentEnhanced + shareCardGenerator（需先 tcb 登录一次）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
export CI=1

TCB=(npx -p @cloudbase/cli@3.4.0 tcb)

echo "==> 安装依赖…"
(cd "$ROOT/cloudfunctions/hostAgentEnhanced" && npm install --registry="$NPM_CONFIG_REGISTRY")
(cd "$ROOT/cloudfunctions/shareCardGenerator" && npm install --registry="$NPM_CONFIG_REGISTRY")

cd "$ROOT"
echo "==> 部署 hostAgentEnhanced (env=$ENV_ID)"
"${TCB[@]}" fn deploy hostAgentEnhanced --force --json

echo "==> 部署 shareCardGenerator"
"${TCB[@]}" fn deploy shareCardGenerator --force --json

echo "==> ping 校验"
"${TCB[@]}" fn invoke hostAgentEnhanced -e "$ENV_ID" --params '{"action":"ping"}'
"${TCB[@]}" fn invoke shareCardGenerator -e "$ENV_ID" --params '{"action":"ping"}'

echo "完成。"
