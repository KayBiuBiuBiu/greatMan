# Minium 自动化测试完整指南

## 快速开始

```bash
# 1. 进入项目目录
cd /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games

# 2. 安装 Minium
pip install minium

# 3. 确保微信开发者工具已打开并编译小程序
# Ctrl/Cmd + B

# 4. 运行测试脚本
bash run_minium_tests.sh
# 或直接
python tests/test_gesture_minium.py
```

## 前置环境要求

### 1. 微信开发者工具配置

**步骤 1: 打开项目**
```
微信开发者工具 → 选择项目
项目路径: /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
```

**步骤 2: 编译小程序**
```
菜单栏 → 编译 (或 Ctrl/Cmd + B)
等待预览区显示小程序首页
```

**步骤 3: 启用自动化调试**

选择以下任一方式:

**方式 A: 本地自动化 (推荐)**
```
右上角 ⋮ → 自动化测试 → 本地自动化
URL: http://localhost:9420
```

**方式 B: 远程调试**
```
右上角 ⋮ → 远程调试
获取调试地址
```

### 2. 云函数和数据库

**云函数** ✅
```
- gestureRoomService 已部署
- 状态: 绿色显示
```

**数据库集合** ✅
```
- gesture_rooms
- gesture_players
- gesture_gameState
```

### 3. Minium 安装

```bash
# 使用 pip 安装
pip install minium

# 验证安装
python -c "import minium; print(minium.__version__)"
```

## 运行测试脚本

### 方法 1: 使用快速启动脚本 (推荐)

```bash
bash /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games/run_minium_tests.sh
```

**优点:**
- 自动检查环境
- 显示清晰的检查清单
- 实时反馈测试结果

### 方法 2: 直接运行 Python 脚本

```bash
cd /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
python tests/test_gesture_minium.py
```

### 方法 3: 使用 Minium CLI

```bash
minium run tests/test_gesture_minium.py
```

## 测试覆盖范围

| # | 测试项目 | 说明 | 预期结果 |
|---|---------|------|---------|
| TC-01 | 创建房间 | 进入游戏 → 输入昵称 → 点击创建 | 显示 6 位口令 ✓ |
| TC-02 | 多人加入 | 验证成员列表 | 成员列表显示正确 ✓ |
| TC-03 | 开始游戏 | 点击开始按钮 | 进入表演阶段，显示倒计时 ✓ |
| TC-04 | 答题判题 | 输入答案 → 提交 | 答案已提交，分数更新 ✓ |
| TC-05 | 倒计时 | 验证倒计时准确性 | 倒计时 ±1秒 ✓ |
| TC-06 | 揭示阶段 | 等待倒计时完成 | 显示答案和下一轮按钮 ✓ |
| TC-07 | 多轮游戏 | 验证轮数显示 | 轮数正确递进 ✓ |
| TC-08 | 性能指标 | 获取页面加载时间 | < 2 秒 ✓ |
| TC-09 | 网络状态 | 检查网络连接 | 在线 ✓ |

## 测试执行流程

```
1. 脚本启动
   ↓
2. 环境检查
   ├─ Python ✓
   ├─ Minium ✓
   └─ 测试脚本 ✓
   ↓
3. 前置条件验证
   ├─ 微信开发者工具 ✓
   ├─ 小程序编译 ✓
   ├─ 云函数部署 ✓
   └─ 数据库集合 ✓
   ↓
4. Minium 连接
   ├─ 连接本地调试器 ✓
   └─ 获取小程序上下文 ✓
   ↓
5. 执行 9 个测试用例
   ├─ TC-01: 创建房间 ✓
   ├─ TC-02: 多人加入 ✓
   ├─ TC-03: 开始游戏 ✓
   ├─ TC-04: 答题判题 ✓
   ├─ TC-05: 倒计时 ✓
   ├─ TC-06: 揭示阶段 ✓
   ├─ TC-07: 多轮游戏 ✓
   ├─ TC-08: 性能指标 ✓
   └─ TC-09: 网络状态 ✓
   ↓
6. 生成测试报告
   ├─ 总计: 9
   ├─ 通过: N
   ├─ 失败: 0
   └─ 成功率: X%
```

## 测试输出示例

```
[2026-06-02 10:30:15] ✓ TC-01: 创建房间
         房间码: 123456

[2026-06-02 10:30:20] ✓ TC-02: 多人加入
         当前成员数: 1

[2026-06-02 10:30:25] ✓ TC-03: 开始游戏
         进入游戏阶段

[2026-06-02 10:30:30] ✓ TC-04: 答题判题
         答案已提交

[2026-06-02 10:30:35] ✓ TC-05: 倒计时
         当前倒计时: 45秒

[2026-06-02 10:30:40] ✓ TC-06: 揭示阶段
         进入揭示阶段

[2026-06-02 10:30:45] ✓ TC-07: 多轮游戏
         当前: 第 2 / 5 轮

[2026-06-02 10:30:50] ✓ TC-08: 性能指标
         页面加载时间: 1250ms

[2026-06-02 10:30:55] ✓ TC-09: 网络状态
         网络正常

======================================================================
测试总结
======================================================================
总计: 9 个测试
✓ 通过: 9
✗ 失败: 0
✗ 错误: 0
成功率: 100%
======================================================================
```

## 常见问题排查

### 问题 1: Minium 连接失败

**症状**: `ConnectionRefusedError` 或 `Connection timeout`

**解决方案**:
```bash
1. 确认微信开发者工具已打开
2. 确认自动化模式已启用
   右上角 ⋮ → 自动化测试 → 本地自动化
3. 确认端口 9420 未被占用
   lsof -i :9420
4. 重启微信开发者工具
```

### 问题 2: 找不到元素

**症状**: `NoSuchElementException`

**解决方案**:
```bash
1. 验证小程序已正确编译
2. 检查元素定位器是否正确
   在开发者工具中检查 DOM 结构
3. 增加等待时间
   修改脚本中的 time.sleep(2) 为 time.sleep(3)
4. 检查选择器是否改变
   查看最新的 gesture.wxml
```

### 问题 3: 云函数调用失败

**症状**: 游戏创建房间时失败

**解决方案**:
```bash
1. 检查云函数是否部署
   云开发 → gestureRoomService → 确认绿色显示
2. 查看云函数日志
   云开发 → 日志 → 搜索 gestureRoomService
3. 验证数据库权限
   云开发 → 数据库 → 检查集合权限
4. 检查网络连接
   ping cloud-service.tencent.com
```

### 问题 4: 数据库集合不存在

**症状**: `Database collection not found`

**解决方案**:
```bash
1. 在 CloudBase 控制台创建三个集合:
   - gesture_rooms (权限: ADMINONLY)
   - gesture_players (权限: ADMINONLY)
   - gesture_gameState (权限: 登录可读)
2. 创建必要的索引
3. 确认权限设置正确
```

### 问题 5: 测试超时

**症状**: 测试运行超过 5 分钟未完成

**解决方案**:
```bash
1. 检查小程序是否响应缓慢
2. 增加超时时间
   修改脚本中的 set_page_load_timeout(30) 
3. 检查网络连接
4. 尝试重启微信开发者工具
```

## 性能基准

| 操作 | 期望 | 实测范围 |
|------|------|---------|
| 页面加载 | < 2s | 1-2s |
| 创建房间 | < 2s | 1-2s |
| 加入房间 | < 2s | 1-2s |
| 答题反馈 | < 1s | 0.5-1s |
| 倒计时精度 | ±1s | ±0.5-1s |

## 高级用法

### 自定义测试

```python
# 修改 test_gesture_minium.py
def test_custom_scenario(self):
    """自定义测试场景"""
    # 添加你的测试代码
    pass
```

### 并行测试

```bash
# 运行多个测试实例
for i in {1..3}; do
    python tests/test_gesture_minium.py &
done
wait
```

### 持续集成集成

```yaml
# GitHub Actions 示例
- name: Run Minium Tests
  run: |
    pip install minium
    python tests/test_gesture_minium.py
```

## 技术支持

如遇问题，请参考:
- `tests/MINIUM_TEST_GUIDE.md` - 完整测试指南
- `tests/README.md` - 测试文档汇总
- `DEPLOYMENT_CHECKLIST.md` - 部署检查表

---

**最后更新**: 2026-06-02
**作者**: Claude Code
**版本**: 1.0
