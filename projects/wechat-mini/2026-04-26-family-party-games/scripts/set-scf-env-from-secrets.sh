#!/usr/bin/env bash
# 从 secrets.local.json 读取 Key，用腾讯云 CLI 写入云函数环境变量
# 前置：pip install tccli && tccli configure（SecretId/SecretKey/region）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS="$ROOT/cloudfunctions/aiPartyService/secrets.local.json"
ENV_ID="cloud1-d9g01no7m292bc511"
FN="aiPartyService"
REGION="${TCCLI_REGION:-ap-shanghai}"

if ! command -v tccli >/dev/null 2>&1; then
  echo "未安装 tccli。请执行: pip install tccli"
  echo "然后: tccli configure"
  exit 1
fi
if [[ ! -f "$SECRETS" ]]; then
  echo "缺少 $SECRETS（可复制 secrets.local.json.example）"
  exit 1
fi

KEY="$(node -e "const s=require('$SECRETS'); process.stdout.write(String(s.HUNYUAN_API_KEY||'').trim())")"
BASE="$(node -e "const s=require('$SECRETS'); process.stdout.write(String(s.HUNYUAN_API_BASE||'https://api.hunyuan.cloud.tencent.com/v1/').trim())")"
if [[ -z "$KEY" ]]; then
  echo "secrets.local.json 中 HUNYUAN_API_KEY 为空"
  exit 1
fi

ENV_JSON="$(node -e "
  console.log(JSON.stringify({
    Variables: [
      { Key: 'HUNYUAN_API_KEY', Value: process.argv[1] },
      { Key: 'HUNYUAN_API_BASE', Value: process.argv[2] }
    ]
  }))
" "$KEY" "$BASE")"

echo "设置 $FN 环境变量 (Namespace=$ENV_ID, Region=$REGION) ..."
tccli scf UpdateFunctionConfiguration \
  --region "$REGION" \
  --FunctionName "$FN" \
  --Namespace "$ENV_ID" \
  --Environment "$ENV_JSON" \
  --Timeout 60

echo "完成。请在云开发控制台确认变量已生效，必要时重新部署 $FN。"
