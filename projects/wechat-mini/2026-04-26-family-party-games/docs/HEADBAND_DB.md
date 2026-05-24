# 贴头猜词 · 云数据库

## 概览

| 项目 | 配置 |
|------|------|
| **集合** | `headband_rooms`（房间）、`headband_players`（玩家） |
| **权限** | **ADMINONLY** — 仅云函数可读写；小程序经 `headbandRoomService` 访问 |
| **索引** | `headband_rooms.roomCode` 唯一；`headband_players` 复合唯一 `roomId + openId` |

### 集合与安全规则（已创建）

| 集合 | 状态 | 安全规则 | 说明 |
|------|------|----------|------|
| `headband_rooms` | ✅ | **ADMINONLY** | 房间元数据、状态、配置 |
| `headband_players` | ✅ | **ADMINONLY** | 玩家资料与私密词语 `myWord` |

**ADMINONLY：**

- ✅ 云函数 `headbandRoomService` 可读写
- ❌ 小程序端不得 `db.collection(...)` 直连

前端仅通过 `syncState` / `join` 等接口拿到脱敏 `view`（自己头上为 `？？？`）。

### 索引（已创建）

| 集合 | 索引 | 类型 | 用途 |
|------|------|------|------|
| `headband_rooms` | `roomCode` | **唯一** | 按 6 位口令定位房间；建房时全局不可重复 |
| `headband_players` | `roomId` + `openId` | **复合唯一** | 同一用户在同一房间内仅一条记录 |

> 建房逻辑：`create` 用 `roomCodeTaken` 检查口令是否已被任意房间占用（含已结束），与唯一索引一致。进房仍查 `status != finished` 的活跃房间。

---

## 数据关系

```
headband_rooms (_id)
    │
    ├── roomCode (6 位，进房查询)
    ├── status: waiting → playing → finished
    └── config: { category, difficulty, wordCount }
         │
         ▼ 1 : N
headband_players
    ├── roomId → headband_rooms._id
    ├── openId (微信 OPENID)
    └── myWord (仅云库存储，不下发给自己)
```

---

## headband_rooms 文档结构

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `_id` | string | 自动 | 房间 ID，前端 `roomId` |
| `roomCode` | string | ✅ | 6 位数字口令 |
| `hostOpenId` | string | ✅ | 组长 OPENID |
| `status` | string | ✅ | `waiting` 等待 / `playing` 进行中 / `finished` 已结束 |
| `config` | object | ✅ | 见下表 |
| `winnerOpenId` | string | | 猜对者 OPENID，未分出时 `''` |
| `startedAt` | number | | 开局时间戳 ms，未开局为 `0` |
| `createdAt` | number | ✅ | 创建时间 |
| `updatedAt` | number | ✅ | 最后更新时间 |

### `config` 子字段

| 字段 | 类型 | 可选值 |
|------|------|--------|
| `category` | string | `history` `entertainment` `sports` `anime` `movie` `internet` |
| `difficulty` | string | `easy` `medium` `hard` |
| `wordCount` | number | `10` / `20` / `30`（开局所需词库规模） |

默认值（云函数 `DEFAULT_CONFIG`）：`entertainment` / `easy` / `20`。

---

## headband_players 文档结构

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `_id` | string | 自动 | 玩家记录 ID |
| `roomId` | string | ✅ | 关联 `headband_rooms._id` |
| `openId` | string | ✅ | 微信 OPENID |
| `nickName` | string | ✅ | 昵称（进房/创建时写入，可更新） |
| `avatarUrl` | string | | 头像 URL |
| `isHost` | boolean | ✅ | 是否组长（与 `hostOpenId` 一致时为 true） |
| `myWord` | string | | 头上词语；等待阶段 `''`，开局后由云函数发牌写入 |
| `joinedAt` | number | ✅ | 加入时间戳 ms |

**隐私：** `myWord` 永不原样返回给本人；`buildPublicView` 对本人映射为 `displayWord: '？？？'`，对他人返回真实词。

---

## 前端可见 `view`（由云函数组装，非库表）

`getView` / `syncState` / `join` 返回的 `view` 示例字段：

| 字段 | 说明 |
|------|------|
| `roomId` / `roomCode` | 房间标识 |
| `status` | 同 rooms.status |
| `config` | 同 rooms.config |
| `isHost` | 当前用户是否组长 |
| `players[]` | `{ openId, nickName, avatarUrl, isHost, displayWord }` |
| `winnerNickName` | 结束时展示 |

---

## 状态与写操作

| status | 允许操作 |
|--------|----------|
| `waiting` | `join`、`setConfig`（组长）、`startGame`（组长，≥2 人） |
| `finished` | `startGame` / `playAgain`（组长再来一局，≥2 人） |
| `playing` | `submitGuess`、`endGame`（组长） |
| `finished` | 仅 `getView` / `syncState`；新局需新建房间或后续扩展「再来一局」 |

| action | 写入集合 |
|--------|----------|
| `create` | rooms + players（组长） |
| `join` | players（新成员）或更新昵称 |
| `setConfig` | rooms.config |
| `startGame` | 每人 players.myWord + rooms.status=`playing` |
| `submitGuess` | 猜对 → rooms.status=`finished`, winnerOpenId |
| `endGame` | rooms.status=`finished` |

---

## 云函数 `headbandRoomService` · action 对照

集合与权限与云台一致（`headband_rooms` / `headband_players`，ADMINONLY）。

| 云台 / 文档名 | 小程序实际调用 | 说明 |
|---------------|----------------|------|
| `ping` | `ping` | 连通性 + 集合可读 |
| `createRoom` | **`create`** | 建房，返回 `roomId`、`roomCode` |
| `joinRoom` | **`join`** | 口令或 `roomId` 进房 |
| `getRoom` | **`syncState`** / `getView` | 拉取脱敏 `view`（成员、头上词） |
| `startGame` | `startGame` | 发牌；可传 `wordBank`；`finished` 时可再来一局 |
| `playAgain` | `startGame` | 同 `startGame` |
| `leaveRoom` | （未用） | 别名 `leave`，当前仅占位 |
| `updatePlayerWord` | （未用） | 发牌请走 `startGame` |
| — | `setConfig` | 组长改分类/难度/词条数 |
| — | `submitGuess` | 猜自己头上名字 |
| — | `endGame` | 组长结束本局 |

**部署：** 务必上传本仓库 `cloudfunctions/headbandRoomService/index.js`，并选 **云端安装依赖**（需 `wx-server-sdk`）。

**词库：** `generateCharacters`（已部署，勿改）；前端开局前调用并传 `wordBank`。

**小程序：** `pages/headband/headband` · `utils/headbandCloud.js` · 排查见 `docs/HEADBAND_排查.md`
