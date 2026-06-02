#!/bin/bash

# 你比划我猜 - Minium 快速测试脚本
# 在本地电脑运行此脚本（需要安装 minium）

PROJECT_ROOT="/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games"

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        你比划我猜 - Minium 自动化测试                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# 检查 Minium 是否安装
if ! python -c "import minium" 2>/dev/null; then
    echo "❌ Minium 未安装"
    echo ""
    echo "请先安装 Minium:"
    echo "  pip install minium"
    echo ""
    exit 1
fi

echo "✓ Python: $(python --version 2>&1)"
echo "✓ Minium: 已安装"
echo ""

# 检查项目目录
if [ ! -d "$PROJECT_ROOT" ]; then
    echo "❌ 项目目录不存在: $PROJECT_ROOT"
    exit 1
fi

echo "✓ 项目目录: 存在"
echo ""

# 前置检查
echo "📋 前置条件检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "请确保:"
echo "  1️⃣  微信开发者工具已打开"
echo "     项目路径: $PROJECT_ROOT"
echo ""
echo "  2️⃣  小程序已编译"
echo "     快捷键: Ctrl/Cmd + B"
echo "     确认: 预览区显示首页"
echo ""
echo "  3️⃣  启用自动化调试"
echo "     微信开发者工具 → 右上角 ⋮ → 自动化测试 → 本地自动化"
echo "     URL: http://localhost:9420"
echo ""
echo "  4️⃣  云函数已部署"
echo "     云开发 → gestureRoomService → 状态: 绿色"
echo ""
echo "  5️⃣  数据库集合已创建"
echo "     云开发 → 数据库 → 3个集合"
echo ""

read -p "按 Enter 键继续（确认以上条件都已满足）..."

echo ""
echo "🚀 启动测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "$PROJECT_ROOT"

# 运行测试
python tests/test_gesture_final.py

TEST_RESULT=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $TEST_RESULT -eq 0 ]; then
    echo ""
    echo "✅ 所有测试通过！"
    echo ""
    echo "🎉 你比划我猜游戏已成功验证！"
    echo ""
    echo "现在你可以:"
    echo "  1. 邀请朋友一起玩"
    echo "  2. 分享游戏链接"
    echo "  3. 享受游戏的乐趣！"
    echo ""
else
    echo ""
    echo "❌ 测试失败"
    echo ""
    echo "请检查:"
    echo "  • 微信开发者工具是否正常运行"
    echo "  • 自动化调试是否已启用"
    echo "  • 小程序是否已编译"
    echo "  • 云函数是否已部署"
    echo "  • 数据库集合是否已创建"
    echo ""
fi

exit $TEST_RESULT
