#!/usr/bin/env bash
# 通过 CloudBase CLI 应用：数据库索引、集合安全规则、hostAgent 定时触发器
# 前置：本机已 tcb login（与 deploy-all-cloudfunctions.sh 相同）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"
# FlexDB 实例 Tag（DescribeEnvs → Databases[0].InstanceId）
TAG="${TCB_DB_TAG:-tnt-bgtah2zps}"
export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
export CI=1

TCB=(npx -p @cloudbase/cli@3.4.0 tcb)
cd "$ROOT"

api_update_table() {
  local body="$1"
  if ! "${TCB[@]}" api tcb UpdateTable --body "$body" --json 2>&1 | tee /tmp/tcb-update-table.log | grep -q '"RequestId"'; then
    echo "WARN UpdateTable: $(tail -3 /tmp/tcb-update-table.log)" >&2
    return 1
  fi
  return 0
}

create_unique_index() {
  local table="$1"
  local fld="$2"
  local idx="idx_${fld}_unique"
  local body
  body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"$table","CreateIndexes":[{"IndexName":"$idx","MgoKeySchema":{"MgoIndexKeys":[{"Name":"$fld","Direction":"1"}],"MgoIsUnique":true}}]}
EOF
)
  echo "==> index unique $table.$fld"
  api_update_table "$body" || true
}

create_compound_unique() {
  local table="$1"
  local idx="$2"
  local body
  body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"$table","CreateIndexes":[{"IndexName":"$idx","MgoKeySchema":{"MgoIndexKeys":[{"Name":"roomId","Direction":"1"},{"Name":"openId","Direction":"1"}],"MgoIsUnique":true}}]}
EOF
)
  echo "==> index compound unique $table (roomId+openId)"
  api_update_table "$body" || true
}

create_compound_index() {
  local table="$1"
  local idx="$2"
  local f1="$3"
  local f2="$4"
  local body
  body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"$table","CreateIndexes":[{"IndexName":"$idx","MgoKeySchema":{"MgoIndexKeys":[{"Name":"$f1","Direction":"1"},{"Name":"$f2","Direction":"1"}],"MgoIsUnique":false}}]}
EOF
)
  echo "==> index compound $table ($f1+$f2)"
  api_update_table "$body" || true
}

create_roomid_index() {
  local table="$1"
  local body
  body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"$table","CreateIndexes":[{"IndexName":"idx_roomId","MgoKeySchema":{"MgoIndexKeys":[{"Name":"roomId","Direction":"1"}],"MgoIsUnique":false}}]}
EOF
)
  echo "==> index roomId $table"
  api_update_table "$body" || true
}

perm_adminonly() {
  local col="$1"
  echo "==> permission adminonly $col"
  yes y | "${TCB[@]}" permission set "collection:$col" --level adminonly -e "$ENV_ID" --json >/dev/null 2>&1 || true
}

perm_custom() {
  local col="$1" rule="$2"
  echo "==> permission custom $col"
  yes y | "${TCB[@]}" permission set "collection:$col" --level custom --rule "$rule" -e "$ENV_ID" --json >/dev/null 2>&1 || true
}

create_table_if_missing() {
  local table="$1"
  local acl="${2:-ADMINONLY}"
  local body
  body=$(cat <<EOF
{"EnvId":"$ENV_ID","Tag":"$TAG","TableName":"$table","PermissionInfo":{"AclTag":"$acl","EnvId":"$ENV_ID"}}
EOF
)
  echo "==> create table $table (skip if exists)"
  if "${TCB[@]}" api tcb CreateTable --body "$body" --json 2>&1 | tee /tmp/tcb-create-table.log | grep -qE '"RequestId"|resource exist|ResourceExist|已存在'; then
    return 0
  fi
  if grep -qiE 'resource exist|ResourceExist|已存在' /tmp/tcb-create-table.log 2>/dev/null; then
    return 0
  fi
  echo "WARN CreateTable $table: $(tail -3 /tmp/tcb-create-table.log)" >&2
  return 1
}

RULE_READ_AUTH_WRITE_FALSE='{"read":"auth != null","write":false}'
RULE_FEED_READ='{"read":true,"write":false}'
RULE_USERS='{"read":"doc._openid == auth.openid || doc._id == auth.openid","write":"doc._openid == auth.openid || doc._id == auth.openid"}'

echo "==> 环境 $ENV_ID Tag=$TAG"

echo "==> users 集合（不存在则创建）"
bash "$ROOT/scripts/ensure-users-collection.sh" || true

echo "==> P0 索引"
for t in drink_rooms uc_rooms werewolf_rooms draw_rooms music_rooms headband_rooms dontdoit_rooms; do
  create_unique_index "$t" roomCode
done
for t in drink_players uc_players draw_players music_players headband_players dontdoit_players; do
  create_compound_unique "$t" "idx_roomId_openId_unique"
done
for t in werewolf_state uc_state drink_gameState draw_gameState draw_canvas music_gameState drink_votes; do
  create_roomid_index "$t"
done
create_unique_index share_tokens token
create_unique_index share_riddles token
create_compound_index share_unlock_users idx_openId_sessionId openId sessionId
create_compound_index agent_room_feed idx_roomId_type roomId type

echo "==> P0 安全规则"
ADMIN_COLS=(
  drink_rooms drink_players drink_votes
  uc_rooms uc_players
  werewolf_rooms
  draw_rooms draw_players
  music_rooms music_players
  headband_rooms headband_players
  dontdoit_rooms dontdoit_players
  rooms
  share_tokens share_unlock_users share_riddles
  game_clicks share_cards analytics_share_unlock
)
for c in "${ADMIN_COLS[@]}"; do perm_adminonly "$c"; done
perm_custom users "$RULE_USERS"
for c in drink_gameState music_gameState draw_gameState draw_canvas uc_state werewolf_state; do
  perm_custom "$c" "$RULE_READ_AUTH_WRITE_FALSE"
done
perm_custom agent_room_feed "$RULE_FEED_READ"

echo "==> P0 hostAgent 触发器 autoTick"
"${TCB[@]}" fn trigger create hostAgent --trigger-name autoTick --cron "0 */1 * * * * *" -e "$ENV_ID" --json 2>&1 | grep -E 'Trigger created|already|exist' || true

echo "==> P1 重部署 shareCardGenerator（wxacode.getUnlimited）"
"${TCB[@]}" fn deploy shareCardGenerator --force --json 2>&1 | tail -3

echo ""
echo "完成。请在控制台核对："
echo "  https://tcb.cloud.tencent.com/dev?envId=${ENV_ID}#/db/doc"
echo "  https://tcb.cloud.tencent.com/dev?envId=${ENV_ID}#/scf"
echo ""
echo "仍需你在控制台手动：开通混元 hunyuan-lite（AI+）；上传小程序。"
