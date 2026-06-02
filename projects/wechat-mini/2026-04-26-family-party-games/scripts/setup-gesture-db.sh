#!/usr/bin/env bash

# 为「你比划我猜」自动创建数据库集合
# 原理：向集合中插入一条文档会自动创建该集合
# 然后立即删除该文档，保留空集合

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"

echo "📦 环境 ID: $ENV_ID"
echo ""
echo "========================================="
echo "创建数据库集合"
echo "========================================="
echo ""

TCB=(npx -p @cloudbase/cli@3.4.0 tcb)

# 创建集合的函数（通过插入文档自动创建集合）
create_collection() {
  local name=$1
  local description=$2

  echo "✓ 创建集合: $name"

  # 构建插入命令：插入一条临时文档
  local insert_cmd="{\"insert\":\"$name\",\"documents\":[{\"_temp\":true,\"_createTime\":$(date +%s000)}]}"
  local cmd_json="[{\"TableName\":\"$name\",\"CommandType\":\"INSERT\",\"Command\":\"$insert_cmd\"}]"

  # 执行插入 (自动创建集合)
  if "${TCB[@]}" db nosql execute -c "$cmd_json" >/dev/null 2>&1; then
    echo "  ✅ 集合已创建"

    # 删除临时文档
    local delete_cmd="{\"delete\":\"$name\",\"deletes\":[{\"q\":{\"_temp\":true},\"limit\":0}]}"
    local del_json="[{\"TableName\":\"$name\",\"CommandType\":\"DELETE\",\"Command\":\"$delete_cmd\"}]"

    if "${TCB[@]}" db nosql execute -c "$del_json" >/dev/null 2>&1; then
      echo "  ✅ 临时数据已清理"
    fi
  else
    echo "  ⚠️  创建失败 (可能已存在或需要权限)"
  fi
}

cd "$ROOT"

# 创建三个集合
create_collection "gesture_rooms" "房间主表"
create_collection "gesture_players" "玩家表"
create_collection "gesture_gameState" "游戏状态表"

echo ""
echo "✅ 数据库集合创建完成！"
echo ""
echo "📌 验证集合是否存在:"
echo "   1. 打开 CloudBase 控制台: https://tcb.cloud.tencent.com/"
echo "   2. 选择环境: $ENV_ID"
echo "   3. 进入「数据库」菜单"
echo "   4. 应该能看到三个集合:"
echo "      - gesture_rooms"
echo "      - gesture_players"
echo "      - gesture_gameState"
