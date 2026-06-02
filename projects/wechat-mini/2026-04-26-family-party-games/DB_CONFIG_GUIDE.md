# 🔧 数据库集合 - 权限和索引配置说明

## 快速操作 (5分钟)

### 步骤 1: 打开 CloudBase 控制台

```
https://tcb.cloud.tencent.com/
```

### 步骤 2: 选择环境

```
环境 ID: cloud1-d9g01no7m292bc511-d5e875d
```

### 步骤 3: 进入数据库设置

```
左侧菜单 → 数据库
```

---

## 集合配置详情

### 集合 1: gesture_rooms

**权限设置**:

| 操作 | 设置 |
|------|------|
| 读 | 👤 登录用户 或 ✓ 所有人 (推荐: 所有人) |
| 写 | 🔐 仅管理员 |
| 管理员 | 🔐 仅管理员 |

**索引创建**:

1. 点击「添加索引」
2. 字段: `roomCode`
3. 排序: `升序` (1)
4. 唯一性: ✓ 勾选 「唯一」
5. 稀疏: ✓ 勾选
6. 点击「确定」

**预期结果**:
```
✓ roomCode (唯一索引)
```

---

### 集合 2: gesture_players

**权限设置**:

| 操作 | 设置 |
|------|------|
| 读 | 👤 登录用户 或 ✓ 所有人 (推荐: 所有人) |
| 写 | 🔐 仅管理员 |
| 管理员 | 🔐 仅管理员 |

**索引创建** (复合唯一):

1. 点击「添加索引」
2. 第一个字段: `roomId` (升序)
3. 第二个字段: `openId` (升序)
4. 唯一性: ✓ 勾选 「唯一」
5. 稀疏: ✓ 勾选
6. 点击「确定」

**预期结果**:
```
✓ roomId_1_openId_1 (复合唯一索引)
```

---

### 集合 3: gesture_gameState

**权限设置**:

| 操作 | 设置 |
|------|------|
| 读 | 👤 登录用户 |
| 写 | 🔐 仅管理员 (仅云函数) |
| 管理员 | 🔐 仅管理员 |

**索引创建**:

无需创建索引

---

## 通过微信开发者工具配置 (替代方案)

如果无法访问 CloudBase 控制台，可以通过微信开发者工具配置：

1. 打开微信开发者工具
2. 项目: `/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games`
3. 点击「云开发」选项卡
4. 点击「数据库」
5. 点击对应集合 → 「权限」→ 编辑
6. 点击对应集合 → 「索引」→ 添加

操作方式与上面相同。

---

## 权限表达式详解 (高级)

如果控制台支持自定义权限表达式，可以使用：

**gesture_rooms** (房主管理):
```
read: 'in(db.getOpenId())'  // 登录用户可读
write: 'db.getOpenId() === root.hostOpenId'  // 仅房主和管理员可写
```

**gesture_players** (云函数管理):
```
read: 'in(db.getOpenId())'  // 登录用户可读
write: 'db.getOpenId() === "SYSTEM_OPENID"'  // 仅云函数可写
```

**gesture_gameState** (云函数同步):
```
read: 'in(db.getOpenId())'  // 登录用户可读
write: 'db.getOpenId() === "SYSTEM_OPENID"'  // 仅云函数可写
```

但建议使用简单的「仅管理员」设置，因为云函数默认以管理员权限执行。

---

## 验证配置

配置完成后，应该能在集合列表中看到：

```
✓ gesture_rooms
  索引: roomCode (唯一)
  权限: 读/写 已配置

✓ gesture_players
  索引: roomId_1_openId_1 (复合唯一)
  权限: 读/写 已配置

✓ gesture_gameState
  权限: 读/写 已配置
```

---

## 配置完成后

所有配置完成后，云函数 gestureRoomService 就可以正常操作这些集合了：

- ✅ 创建房间 → gesture_rooms
- ✅ 加入房间 → gesture_players
- ✅ 游戏状态同步 → gesture_gameState

---

## 快速参考

| 集合 | 读 | 写 | 索引 | 作用 |
|------|----|----|------|------|
| gesture_rooms | 所有人 | 管理员 | roomCode (唯一) | 房间主表 |
| gesture_players | 所有人 | 管理员 | roomId+openId (唯一) | 玩家表 |
| gesture_gameState | 登录用户 | 云函数 | 无 | 游戏状态 |

---

**💡 建议**: 直接打开 CloudBase 控制台在线配置，点几下就完成了，比按说明手工操作快得多！

只需 5 分钟即可全部完成。
