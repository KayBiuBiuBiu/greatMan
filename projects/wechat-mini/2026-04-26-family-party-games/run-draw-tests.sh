#!/bin/bash

# 你画我猜 Canvas 测试运行脚本
# 需要先启动微信开发者工具中的自动化测试

PROJECT_DIR="/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games"
TEST_FILE="tests/draw-guess-canvas.test.js"

echo "=========================================="
echo "你画我猜 Canvas 绘画同步 - Minium 自动化测试"
echo "=========================================="
echo ""

# 检查 minium 是否安装
if ! command -v minium &> /dev/null; then
    echo "❌ 未检测到 Minium CLI，请先安装："
    echo "   npm install -g minium"
    exit 1
fi

# 进入项目目录
cd "$PROJECT_DIR" || exit 1

# 检查测试文件
if [ ! -f "$TEST_FILE" ]; then
    echo "❌ 测试文件不存在: $TEST_FILE"
    exit 1
fi

echo "📝 测试项目: $PROJECT_DIR"
echo "📋 测试文件: $TEST_FILE"
echo ""

# 前置步骤
echo "前置步骤："
echo "1️⃣  打开微信开发者工具"
echo "2️⃣  在本项目运行编译 (Ctrl/Cmd + B)"
echo "3️⃣  进入你画我猜页面"
echo "4️⃣  在开发者工具菜单 → 自动化测试 → 启用"
echo "5️⃣  选择端口（通常是 9420）"
echo ""

# 询问是否继续
read -p "已完成上述步骤？(y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "取消测试"
    exit 1
fi

echo ""
echo "🚀 开始运行测试..."
echo ""

# 运行测试
# 注意：Minium 需要连接到微信开发者工具的自动化服务
# 默认端口是 9420，可根据需要调整

if command -v npx &> /dev/null; then
    # 如果使用 npm 安装的 minium
    npx minium run "$TEST_FILE" --port 9420
else
    # 使用全局安装的 minium
    minium run "$TEST_FILE" --port 9420
fi

TEST_EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "✅ 所有测试通过！"
else
    echo "❌ 测试失败，请查看上面的错误信息"
fi
echo "=========================================="

exit $TEST_EXIT_CODE
