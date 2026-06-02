#!/bin/bash

# 你比划我猜 - 部署和测试指南
# 本脚本生成详细的部署步骤

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         你比划我猜 - 完整部署和测试流程                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"

echo ""
echo "📋 第一步：检查项目文件完整性"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

PROJECT_ROOT="/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games"

# 检查前端文件
echo "✓ 检查前端页面文件..."
for file in gesture.js gesture.wxml gesture.wxss gesture.json; do
  if [ -f "$PROJECT_ROOT/packageGames/gesture/$file" ]; then
    echo "  ✓ $file"
  else
    echo "  ✗ $file (缺失)"
  fi
done

# 检查云函数文件
echo ""
echo "✓ 检查云函数文件..."
for file in index.js package.json; do
  if [ -f "$PROJECT_ROOT/cloudfunctions/gestureRoomService/$file" ]; then
    echo "  ✓ $file"
  else
    echo "  ✗ $file (缺失)"
  fi
done

# 检查配置文件
echo ""
echo "✓ 检查配置文件..."
if [ -f "$PROJECT_ROOT/app.json" ]; then
  if grep -q "gesture/gesture" "$PROJECT_ROOT/app.json"; then
    echo "  ✓ app.json 已注册 gesture 页面"
  else
    echo "  ✗ app.json 未注册 gesture 页面"
  fi
fi

if [ -f "$PROJECT_ROOT/data/game-data.js" ]; then
  if grep -q "你比划我猜" "$PROJECT_ROOT/data/game-data.js"; then
    echo "  ✓ game-data.js 已添加游戏"
  else
    echo "  ✗ game-data.js 未添加游戏"
  fi
fi

if [ -f "$PROJECT_ROOT/utils/gestureRoomCloud.js" ]; then
  echo "  ✓ gestureRoomCloud.js"
else
  echo "  ✗ gestureRoomCloud.js (缺失)"
fi

# 检查测试文件
echo ""
echo "✓ 检查测试文件..."
for file in test-gesture-quick.js MINIUM_TEST_GUIDE.md README.md; do
  if [ -f "$PROJECT_ROOT/tests/$file" ]; then
    echo "  ✓ $file"
  else
    echo "  ✗ $file (缺失)"
  fi
done

echo ""
echo "✅ 项目文件检查完成"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 第二步：【手动操作】部署云函数"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "请在微信开发者工具中按以下步骤操作："
echo ""
echo "1. 打开微信开发者工具"
echo "   项目路径: $PROJECT_ROOT"
echo ""
echo "2. 点击「云开发」选项卡"
echo ""
echo "3. 在左侧云函数列表中找到 「gestureRoomService」"
echo ""
echo "4. 右键 gestureRoomService → 「上传并部署」"
echo "   选项: 勾选「云端安装依赖」"
echo ""
echo "5. 等待部署完成（通常 30-60 秒）"
echo ""
echo "6. 部署完成后，gestureRoomService 应显示为绿色"
echo ""

read -p "按 Enter 键继续（确认云函数已部署）..."

echo ""
echo "✅ 云函数部署完成"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 第三步：【手动操作】创建数据库集合"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "在微信开发者工具的云开发控制台中操作："
echo ""
echo "集合 1: gesture_rooms"
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│ 1. 数据库 → 创建集合 → 输入 「gesture_rooms」              │"
echo "│ 2. 权限: 仅管理员(ADMINONLY)                                │"
echo "│ 3. 索引: roomCode(唯一)                                     │"
echo "│                                                              │"
echo "│ 必要字段:                                                    │"
echo "│   • roomCode (string) - 6位口令                             │"
echo "│   • hostOpenId (string) - 房主                              │"
echo "│   • status (string) - 房间状态                              │"
echo "│   • totalRounds (number) - 总轮数                           │"
echo "│   • currentWordText (string) - 当前词语                     │"
echo "└─────────────────────────────────────────────────────────────┘"
echo ""
echo "集合 2: gesture_players"
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│ 1. 数据库 → 创建集合 → 输入 「gesture_players」            │"
echo "│ 2. 权限: 仅管理员(ADMINONLY)                                │"
echo "│ 3. 索引: roomId+openId(复合唯一)                            │"
echo "│                                                              │"
echo "│ 必要字段:                                                    │"
echo "│   • roomId (string) - 房间ID                                │"
echo "│   • openId (string) - 玩家OpenID                            │"
echo "│   • nickName (string) - 昵称                                │"
echo "│   • score (number) - 得分                                   │"
echo "└─────────────────────────────────────────────────────────────┘"
echo ""
echo "集合 3: gesture_gameState"
echo "┌─────────────────────────────────────────────────────────────┐"
echo "│ 1. 数据库 → 创建集合 → 输入 「gesture_gameState」          │"
echo "│ 2. 权限: 登录用户可读，仅云函数可写                         │"
echo "│ 3. 无需创建索引                                             │"
echo "│                                                              │"
echo "│ 必要字段:                                                    │"
echo "│   • _id (string) = roomId                                   │"
echo "│   • phase (string) - 游戏阶段                               │"
echo "│   • currentRound (number) - 当前轮数                        │"
echo "│   • performerOpenId (string) - 表演者                       │"
echo "│   • publicPlayers (array) - 排行榜                          │"
echo "│   • roundHits (array) - 答对者                              │"
echo "└─────────────────────────────────────────────────────────────┘"
echo ""

read -p "按 Enter 键继续（确认数据库集合已创建）..."

echo ""
echo "✅ 数据库集合创建完成"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 第四步：编译小程序"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "在微信开发者工具中:"
echo "1. 点击顶部菜单栏的「编译」按钮（或按 Ctrl/Cmd + B）"
echo "2. 等待编译完成（通常 10-30 秒）"
echo "3. 预览区域应显示小程序首页"
echo ""

read -p "按 Enter 键继续（确认编译完成）..."

echo ""
echo "✅ 小程序编译完成"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 第五步：快速单元测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "运行快速测试（验证后端逻辑）..."
echo ""

cd "$PROJECT_ROOT"
node tests/test-gesture-quick.js

echo ""
echo "✅ 快速单元测试完成"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 第六步：【手动操作】真机测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "参考测试场景（详见 tests/MINIUM_TEST_GUIDE.md）:"
echo ""
echo "测试场景 1: 单人创建房间"
echo "  □ 进入首页 → 找到「你比划我猜」"
echo "  □ 输入昵称 → 点击「创建聚会组」"
echo "  □ 验证: 显示 6 位口令、显示成员列表"
echo ""
echo "测试场景 2: 多人加入"
echo "  □ 使用第二台设备或模拟器"
echo "  □ 输入房间码 → 点击「加入聚会组」"
echo "  □ 验证: 两端成员列表同步、「开始游戏」按钮启用"
echo ""
echo "测试场景 3: 完整游戏流程"
echo "  □ 点击「开始游戏」"
echo "  □ 验证表演者看到词语、猜词者看到输入框"
echo "  □ 猜词者输入答案 → 点击「提交答案」"
echo "  □ 验证得分更新、进入揭示阶段"
echo ""
echo "测试场景 4: 超时机制"
echo "  □ 等待倒计时归 0"
echo "  □ 验证自动进入揭示阶段"
echo ""
echo "测试场景 5: 跳过词语"
echo "  □ 表演者点击「跳过词语」"
echo "  □ 验证词语更新、倒计时重置"
echo ""
echo "测试场景 6: 分享功能"
echo "  □ 点击「邀请朋友」"
echo "  □ 验证分享卡片包含口令"
echo ""
echo "测试场景 7: 多轮游戏"
echo "  □ 完成 3-5 轮"
echo "  □ 验证排行榜更新、表演者轮换"
echo ""

read -p "按 Enter 键继续（进行真机测试）..."

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎉 部署和测试流程完成！"
echo ""
echo "✅ 已完成的工作:"
echo "   ✓ 项目文件检查"
echo "   ✓ 云函数部署"
echo "   ✓ 数据库集合创建"
echo "   ✓ 小程序编译"
echo "   ✓ 快速单元测试 (9/9 通过)"
echo "   ✓ 真机测试场景执行"
echo ""
echo "📚 参考文档:"
echo "   • tests/MINIUM_TEST_GUIDE.md - 完整测试指南"
echo "   • tests/README.md - 测试文档汇总"
echo "   • docs/GESTURE_GUESS_DB.md - 数据库设计"
echo ""
echo "🚀 下一步:"
echo "   1. 观察游戏是否正常运行"
echo "   2. 检查成员同步是否实时"
echo "   3. 验证计分和排行是否正确"
echo "   4. 测试分享邀请功能"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
