#!/usr/bin/env bash
# 确保云数据库存在 users 集合并设置安全规则（需 tcb login）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"
TAG="${TCB_DB_TAG:-tnt-bgtah2zps}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
export CI=1
TCB=(npx -p @cloudbase/cli@3.4.0 tcb)
RULE_USERS='{"read":"doc._openid == auth.openid || doc._id == auth.openid","write":"doc._openid == auth.openid || doc._id == auth.openid"}'

cd "$ROOT"
echo "==> 环境 $ENV_ID"

body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"users","PermissionInfo":{"AclTag":"ADMINONLY","EnvId":"$ENV_ID"}}
EOF
)
echo "==> CreateTable users（已存在则跳过）"
"${TCB[@]}" api tcb CreateTable --body "$body" --json 2>&1 | tee /tmp/tcb-create-users.log || true
if grep -q '"RequestId"' /tmp/tcb-create-users.log 2>/dev/null; then
  echo "    已创建 users"
elif grep -qiE 'ResourceExist|resource exist|已存在' /tmp/tcb-create-users.log 2>/dev/null; then
  echo "    users 已存在，跳过"
else
  echo "WARN CreateTable users: $(tail -5 /tmp/tcb-create-users.log)" >&2
fi

echo "==> permission custom users"
yes y | "${TCB[@]}" permission set "collection:users" --level custom --rule "$RULE_USERS" -e "$ENV_ID" --json >/dev/null 2>&1 || true

echo "==> 部署 userService"
(cd "$ROOT/cloudfunctions/userService" && npm install --registry="$NPM_CONFIG_REGISTRY" --silent)
"${TCB[@]}" fn deploy userService --force --json 2>&1 | tail -5

echo ""
echo "完成。users 集合 + userService 已就绪。"
