# 在 Cursor 中运行测试

## 方式 1: 直接在终端运行（最简单）⭐

### 步骤 1: 打开 Cursor 终端

```
Cursor 菜单 → Terminal → New Terminal
或快捷键: Ctrl + `
```

### 步骤 2: 运行 Minium 测试

```bash
bash run_test_local.sh
```

或

```bash
python tests/test_gesture_final.py
```

**输出示例**:
```
[11:42:47] [01] ✓ 进入首页
      游戏卡片可见

[11:42:50] [02] ✓ 点击卡片
      已进入游戏页面

...

✅ 所有测试通过！游戏已就绪！
```

---

## 方式 2: 使用 Makefile 命令

### 查看所有可用命令

```bash
make help
```

**输出**:
```
你比划我猜 - 测试命令

可用命令:
  make minium    - 运行 Minium 自动化测试 (本地微信工具)
  make unit      - 运行单元测试
  make test      - 运行所有测试
  make help      - 显示此帮助
```

### 运行 Minium 测试

```bash
make minium
```

### 运行单元测试

```bash
make unit
```

### 运行所有测试

```bash
make test
```

---

## 方式 3: 快捷任务（Cursor 任务系统）

### 打开任务面板

```
Cursor 菜单 → Tasks → Run Task
或快捷键: Ctrl + Shift + T
```

### 选择任务

会看到三个选项:
- 🎮 **运行 Minium 测试** — 完整的自动化测试
- 🧪 **运行单元测试** — 快速的后端逻辑验证
- 📋 **查看测试说明** — 打开使用指南

---

## 方式 4: 在 Cursor 编辑器中设置快捷按钮

创建文件 `.cursor/extensions.json`:

```json
{
  "shortcuts": [
    {
      "name": "Run Minium Test",
      "command": "make minium",
      "keybinding": "ctrl+shift+m"
    },
    {
      "name": "Run Unit Test",
      "command": "make unit",
      "keybinding": "ctrl+shift+u"
    }
  ]
}
```

然后使用快捷键运行：
- `Ctrl + Shift + M` — 运行 Minium 测试
- `Ctrl + Shift + U` — 运行单元测试

---

## 前置条件（必需）

在 Cursor 中运行测试前，**本地电脑必须**满足：

- ✅ 微信开发者工具已打开
- ✅ 小程序已编译 (Ctrl/Cmd + B)
- ✅ 自动化调试已启用 (右上角 ⋮ → 自动化测试 → 本地自动化)
- ✅ 云函数已部署
- ✅ 数据库集合已创建

---

## 完整工作流

### 在 Cursor 中：

```bash
# 1. 打开终端 (Ctrl + `)
# 2. 运行测试
make minium

# 3. 查看实时输出
# 终端会显示每个测试步骤

# 4. 查看结果
# ✅ 通过 = 游戏就绪
# ❌ 失败 = 检查日志
```

---

## 快速参考

| 操作 | 快捷键/命令 |
|------|-----------|
| 打开终端 | Ctrl + ` |
| 运行 Minium 测试 | `bash run_test_local.sh` |
| 运行单元测试 | `make unit` |
| 查看帮助 | `make help` |
| 打开任务面板 | Ctrl + Shift + T |

---

## 故障排查

### 问题: 命令未找到

```bash
make: command not found
```

**解决**:
```bash
# 直接运行 Python
python tests/test_gesture_final.py
```

### 问题: 连接被拒绝

```
ConnectionRefusedError: [Errno 61] Connection refused
```

**解决**:
- 检查微信开发者工具是否打开
- 检查自动化调试是否启用 (右上角 ⋮ → 自动化测试 → 本地自动化)

### 问题: 权限不足

```bash
chmod +x run_test_local.sh
bash run_test_local.sh
```

---

## 推荐用法

### 👍 最快的方式

在 Cursor 终端中输入：
```bash
make minium
```

或

```bash
bash run_test_local.sh
```

### 👍 分步调试

```bash
# 1. 运行单元测试（快速）
make unit

# 2. 运行 Minium（完整）
make minium

# 3. 查看帮助（了解所有选项）
make help
```

---

## 下次可以这样做

1. **Cursor 中打开终端**: `Ctrl + ``
2. **选择目录**: `/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games`
3. **运行测试**: `make minium`
4. **查看结果**: 实时输出在终端中

**享受测试！** 🚀
