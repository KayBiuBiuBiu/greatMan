#!/usr/bin/env bash

# 通过 CloudBase HTTP API 创建数据库集合
# 需要先在 CloudBase 控制台生成 API Key

ENV_ID="cloud1-d9g01no7m292bc511-d5e875d"

echo "📦 使用 HTTP API 创建数据库集合"
echo "环境 ID: $ENV_ID"
echo ""

# 注意：这需要手动获取 API Key 和 Database ID
# 步骤：
# 1. 登录 https://tcb.cloud.tencent.com/
# 2. 选择环境: $ENV_ID
# 3. 设置 → API 管理 → 创建 API Key
# 4. 复制 Secret 和 Authorization Header

echo "⚠️  自动创建集合需要 API Key，建议手动通过控制台创建"
echo ""
echo "==================================================="
echo "手动创建步骤"
echo "==================================================="
echo ""
echo "1️⃣  打开 CloudBase 控制台"
echo "   https://tcb.cloud.tencent.com/"
echo ""
echo "2️⃣  选择环境"
echo "   环境 ID: $ENV_ID"
echo ""
echo "3️⃣  进入「数据库」菜单"
echo ""
echo "4️⃣  创建集合 1: gesture_rooms"
echo "   权限: 仅管理员 (ADMINONLY)"
echo "   索引:"
echo "     - 字段: roomCode"
echo "     - 类型: 唯一"
echo ""
echo "5️⃣  创建集合 2: gesture_players"
echo "   权限: 仅管理员 (ADMINONLY)"
echo "   索引:"
echo "     - 字段: roomId + openId"
echo "     - 类型: 复合唯一"
echo ""
echo "6️⃣  创建集合 3: gesture_gameState"
echo "   权限: 登录用户可读、仅云函数可写"
echo "   索引: (无需创建)"
echo ""
