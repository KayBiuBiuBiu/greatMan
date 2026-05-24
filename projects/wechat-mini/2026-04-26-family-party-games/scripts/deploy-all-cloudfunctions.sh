#!/usr/bin/env bash
# 将全部云函数部署到 cloudbaserc.json 中的 envId（标准版）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
export CI=1

TCB=(npx -p @cloudbase/cli@3.4.0 tcb)

echo "==> 环境: $ENV_ID"
cd "$ROOT"

for dir in "$ROOT"/cloudfunctions/*/; do
  name="$(basename "$dir")"
  if [[ -f "$dir/package.json" ]]; then
    echo "==> npm install: $name"
    (cd "$dir" && npm install --registry="$NPM_CONFIG_REGISTRY" --silent) || true
  fi
done

echo "==> 批量部署（cloudbaserc.json functions 列表）"
"${TCB[@]}" fn deploy --all --force --json

echo "完成。请在控制台核对: https://tcb.cloud.tencent.com/dev?envId=${ENV_ID}#/scf"
