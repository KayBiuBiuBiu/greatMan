#!/usr/bin/env bash

# 为「你比划我猜」创建数据库集合
# 用法: bash scripts/setup-gesture-database.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"

echo "📦 环境 ID: $ENV_ID"
echo ""

TCB=(npx -p @cloudbase/cli@3.4.0 tcb)

# 创建集合的函数
create_collection() {
  local name=$1
  local description=$2

  echo "✓ 创建集合: $name"

  # 使用 tcb db 命令创建集合
  # 注意：tcb CLI 通常需要手动指定环境和权限
  # 这里尝试创建，如果失败可能是因为需要通过控制台手动创建

  if "${TCB[@]}" db createCollection --collection "$name" 2>/dev/null; then
    echo "  ✅ 成功"
  else
    echo "  ℹ️  集合可能已存在或需要手动创建"
  fi
}

echo "========================================="
echo "创建数据库集合"
echo "========================================="
echo ""

cd "$ROOT"

# 创建三个集合
create_collection "gesture_rooms" "房间主表"
create_collection "gesture_players" "玩家表"
create_collection "gesture_gameState" "游戏状态表"

echo ""
echo "✅ 数据库集合创建完成！"
echo ""
echo "📌 如果上述命令返回权限错误，请手动在 CloudBase 控制台创建集合："
echo ""
echo "1. 打开 https://tcb.cloud.tencent.com/"
echo "2. 选择环境: $ENV_ID"
echo "3. 进入数据库 → 创建集合"
echo ""
echo "集合 1: gesture_rooms"
echo "  权限: ADMINONLY"
echo "  索引: roomCode (唯一)"
echo ""
echo "集合 2: gesture_players"
echo "  权限: ADMINONLY"
echo "  索引: roomId + openId (复合唯一)"
echo ""
echo "集合 3: gesture_gameState"
echo "  权限: 登录用户可读，仅云函数可写"
echo "  无需索引"
