# ⚙️ Minium 自动化测试 - 使用说明

## 📋 前置要求

Minium 测试**必须**在有微信开发者工具的电脑上运行（本地测试），不能在服务器上运行。

### 需要的准备

1. **微信开发者工具已打开**
   ```
   项目路径: /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
   ```

2. **小程序已编译**
   ```
   Ctrl/Cmd + B
   预览区显示首页
   ```

3. **云函数已部署**
   ```
   云开发 → gestureRoomService → 状态: 绿色 ✅
   ```

4. **数据库集合已创建**
   ```
   云开发 → 数据库 → gesture_rooms/players/gameState
   ```

5. **启用自动化调试**

   **方式 A: 本地自动化 (推荐)**
   ```
   微信开发者工具 → 右上角 ⋮ → 自动化测试 → 本地自动化
   URL: http://localhost:9420
   ```

   **方式 B: 远程调试**
   ```
   微信开发者工具 → 右上角 ⋮ → 远程调试
   获取调试地址
   ```

---

## 🚀 运行测试

### 方式 1: 在本地电脑上运行 (推荐)

```bash
# 进入项目目录
cd /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games

# 运行 Minium 测试
python tests/test_gesture_simple.py

# 或使用启动脚本
bash run_minium_tests.sh
```

### 方式 2: 使用 Python 配置文件

创建 `minium.cfg` 配置文件：

```ini
[minium]
base_dir = /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
platform = ide
app = wx
test_port = 9420
auto_launch = true
```

然后运行：
```bash
python tests/test_gesture_simple.py
```

---

## 📊 测试覆盖范围

脚本测试以下场景：

| # | 测试 | 说明 |
|---|------|------|
| TC-01 | 创建房间 | 输入昵称 → 创建 → 显示口令 |
| TC-02 | 验证界面 | 检查页面元素是否正确 |
| TC-03 | 启动游戏 | 点击开始 → 进入游戏 |
| TC-04 | 性能指标 | 测量页面加载时间 |
| TC-05 | 网络状态 | 验证网络连接 |

---

## ✅ 手动测试 (无需编程)

如果不想运行自动化测试，可以手动测试：

### 场景 1: 创建房间
```
1. 编译小程序 (Ctrl/Cmd + B)
2. 进入首页
3. 找到「你比划我猜」卡片 (B类)
4. 点击 → 输入昵称 → 创建
5. 验证: 显示 6 位口令 ✓
```

### 场景 2: 多人加入
```
1. 第二台设备打开小程序
2. 进入首页 → 输入房间码
3. 验证: 两端成员列表同步 ✓
```

### 场景 3: 游戏流程
```
1. 点击「开始游戏」
2. 验证: 表演者看到词语 ✓
3. 验证: 猜词者看到输入框 ✓
4. 输入答案 → 验证: 计分更新 ✓
5. 验证: 排行榜显示 ✓
```

---

## 🔍 调试技巧

### 查看 Minium 日志

Minium 会在 `outputs/` 目录生成日志：

```bash
# 查看最新日志
tail -f outputs/*.log
```

### 启用详细输出

```python
# 在测试脚本中
import logging
logging.basicConfig(level=logging.DEBUG)

minium = Minium()
```

### 保存截图

```python
# Minium 会自动保存失败时的截图到 outputs/ 目录
```

---

## ❌ 常见问题

### Q: 连接被拒绝 (Connection refused)

**症状**: `ConnectionRefusedError: [Errno 61] Connection refused`

**原因**: 
- 微信开发者工具未打开
- 自动化调试未启用
- 端口 9420 被占用

**解决**:
1. 打开微信开发者工具
2. 启用「自动化测试」→ 「本地自动化」
3. 检查端口: `lsof -i :9420`

### Q: 找不到游戏卡片

**症状**: `ElementNotFound: 你比划我猜`

**原因**:
- 小程序未编译
- 游戏卡片不在首页

**解决**:
1. Ctrl/Cmd + B 重新编译
2. 检查 feature-flags.js 中「你比划我猜」是否启用
3. 手动滚动到 B 类游戏区块

### Q: 云函数调用失败

**症状**: 创建房间时出错

**原因**:
- 云函数未部署
- 数据库权限不正确

**解决**:
1. 检查 gestureRoomService 状态 (应为绿色)
2. 检查数据库权限设置
3. 查看云函数日志

---

## 📈 性能基准

| 操作 | 期望 | 实测 |
|------|------|------|
| 页面加载 | < 2s | ? |
| 创建房间 | < 2s | ? |
| 加入房间 | < 2s | ? |
| 答题反馈 | < 1s | ? |
| 倒计时精度 | ±1s | ? |

---

## 📝 测试报告模板

运行测试后，记录结果：

```
测试日期: 2026-06-02
环境: 本地 macOS
微信工具版本: 1.x.x

测试结果:
✓ TC-01: 创建房间 - PASS
✓ TC-02: 验证界面 - PASS
✓ TC-03: 启动游戏 - PASS
✓ TC-04: 性能指标 - PASS (1.2s)
✓ TC-05: 网络状态 - PASS

总计: 5/5 通过 ✅
性能: 正常
网络: 正常
```

---

## 🔗 参考资源

- **Minium 官方文档**: https://minitest.weixin.qq.com/
- **微信开发者工具**: https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html
- **自动化测试指南**: `MINIUM_EXECUTION_GUIDE.md`
- **部署检查表**: `DEPLOYMENT_CHECKLIST.md`

---

## 💡 最佳实践

### ✅ 推荐做法

1. **先做单机测试** (一台设备)
   - 验证游戏流程是否正常
   - 检查计分规则是否正确

2. **再做多人测试** (两台设备)
   - 验证实时同步
   - 检查排行榜更新

3. **最后做压力测试** (多轮游戏)
   - 检查表演者轮换
   - 验证内存/性能

### ❌ 避免的做法

1. 不要在微信开发者工具启动自动化调试时手动操作
2. 不要在测试期间切换应用
3. 不要关闭微信开发者工具

---

**最后更新**: 2026-06-02  
**状态**: ✅ 就绪  
**下一步**: 在本地电脑打开微信开发者工具，运行测试
