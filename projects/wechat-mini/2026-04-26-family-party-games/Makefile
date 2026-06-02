.PHONY: test minium unit help

# 你比划我猜游戏测试

help:
	@echo "你比划我猜 - 测试命令"
	@echo ""
	@echo "可用命令:"
	@echo "  make minium    - 运行 Minium 自动化测试 (本地微信工具)"
	@echo "  make unit      - 运行单元测试"
	@echo "  make test      - 运行所有测试"
	@echo "  make help      - 显示此帮助"
	@echo ""

# Minium 自动化测试 (需要本地微信开发者工具)
minium:
	@echo "🎮 启动 Minium 自动化测试..."
	@echo ""
	@echo "前置条件检查:"
	@echo "  1. 微信开发者工具已打开"
	@echo "  2. 小程序已编译 (Ctrl/Cmd + B)"
	@echo "  3. 自动化调试已启用"
	@echo ""
	python tests/test_gesture_final.py

# 单元测试 (快速验证后端逻辑)
unit:
	@echo "🧪 运行单元测试..."
	@echo ""
	node tests/test-gesture-quick.js

# 运行所有测试
test: unit
	@echo ""
	@echo "✅ 测试完成"
	@echo ""
	@echo "下一步:"
	@echo "  1. 在本地运行 Minium 测试: make minium"
	@echo "  2. 验证首页卡片: bash run_test_local.sh"
	@echo "  3. 开始使用游戏"
	@echo ""

# 快速测试脚本
.PHONY: quick-test
quick-test:
	bash run_test_local.sh

# 查看日志
.PHONY: logs
logs:
	@if [ -d "outputs" ]; then \
		tail -f outputs/*.log; \
	else \
		echo "❌ 无日志文件"; \
	fi

# 清理
.PHONY: clean
clean:
	@echo "🧹 清理测试输出..."
	rm -rf outputs/
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	@echo "✅ 清理完成"

.DEFAULT_GOAL := help
