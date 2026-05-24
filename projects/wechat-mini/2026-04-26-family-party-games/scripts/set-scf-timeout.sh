#!/usr/bin/env bash
# 将云函数超时设为 60 秒（AI / 生图 / 副主持 hostAgent 等）
# 前置：pip install tccli && tccli configure
set -euo pipefail
ENV_ID="${TCCLI_NAMESPACE:-cloud1-d9g01no7m292bc511-d5e875d}"
REGION="${TCCLI_REGION:-ap-shanghai}"
TIMEOUT="${SCF_TIMEOUT:-60}"
NAMES="${*:-aiPartyService imageService hostAgent aiPlayer roomService}"

if ! command -v tccli >/dev/null 2>&1; then
  echo "未安装 tccli。请执行: pip install tccli && tccli configure"
  exit 1
fi

for FN in $NAMES; do
  echo "设置 $FN Timeout=${TIMEOUT}s (Namespace=$ENV_ID, Region=$REGION) ..."
  tccli scf UpdateFunctionConfiguration \
    --region "$REGION" \
    --FunctionName "$FN" \
    --Namespace "$ENV_ID" \
    --Timeout "$TIMEOUT"
done

echo "完成。若刚改过 config.json，仍建议在开发者工具重新「上传并部署」对应云函数。"
