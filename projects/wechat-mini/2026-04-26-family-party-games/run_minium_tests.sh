#!/bin/bash

# 你比划我猜 - Minium 自动化测试快速启动脚本

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        你比划我猜 - Minium 自动化测试启动脚本                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"

PROJECT_ROOT="/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games"

echo ""
echo "📋 前置条件检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查 1: 项目目录
if [ -d "$PROJECT_ROOT" ]; then
    echo "✓ 项目目录存在"
else
    echo "✗ 项目目录不存在: $PROJECT_ROOT"
    exit 1
fi

# 检查 2: Python
if command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version 2>&1)
    echo "✓ Python 已安装: $PYTHON_VERSION"
else
    echo "✗ Python 未安装，请先安装 Python 3.7+"
    exit 1
fi

# 检查 3: Minium
if python -c "import minium" 2>/dev/null; then
    echo "✓ Minium 已安装"
else
    echo "⚠ Minium 未安装，正在安装..."
    pip install minium
    if [ $? -eq 0 ]; then
        echo "✓ Minium 安装完成"
    else
        echo "✗ Minium 安装失败"
        exit 1
    fi
fi

# 检查 4: 测试脚本
if [ -f "$PROJECT_ROOT/tests/test_gesture_minium.py" ]; then
    echo "✓ 测试脚本存在"
else
    echo "✗ 测试脚本不存在"
    exit 1
fi

echo ""
echo "📋 前置操作检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "⚠️  在运行 Minium 测试前，请确保:"
echo ""
echo "1️⃣  微信开发者工具已打开"
echo "   位置: 选择项目 → $PROJECT_ROOT"
echo ""
echo "2️⃣  小程序已编译"
echo "   快捷键: Ctrl/Cmd + B"
echo "   确认: 编译完成后预览区显示首页"
echo ""
echo "3️⃣  云函数已部署"
echo "   云开发 → gestureRoomService → 上传并部署"
echo "   确认: 显示为绿色 ✓"
echo ""
echo "4️⃣  数据库集合已创建"
echo "   云开发 → 数据库 → 3个集合（gesture_rooms/players/gameState）"
echo ""
echo "5️⃣  开启 Minium 自动化测试模式"
echo "   在微信开发者工具中:"
echo "   - 点击右上角 ⋮ → 远程调试"
echo "   或"
echo "   - 使用本地自动化: http://localhost:9420"
echo ""

read -p "按 Enter 键继续（确认以上条件都已满足）..."

echo ""
echo "🚀 启动 Minium 测试"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$PROJECT_ROOT"

echo ""
echo "运行命令: python tests/test_gesture_minium.py"
echo ""

python tests/test_gesture_minium.py

TEST_RESULT=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ 所有测试通过！"
    echo ""
    echo "🎉 你比划我猜游戏已成功部署和测试"
    echo ""
    echo "项目上线准备完毕 ✨"
else
    echo "❌ 测试失败，请检查以下项:"
    echo ""
    echo "1. 微信开发者工具是否正常运行"
    echo "2. 云函数是否成功部署"
    echo "3. 数据库集合是否正确创建"
    echo "4. 网络连接是否正常"
    echo ""
    echo "更多帮助，参考: $PROJECT_ROOT/tests/MINIUM_TEST_GUIDE.md"
fi

exit $TEST_RESULT
