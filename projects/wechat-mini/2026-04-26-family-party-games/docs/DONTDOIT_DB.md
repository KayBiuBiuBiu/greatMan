# 不要做挑战 · 云数据库

## 集合与权限

| 集合 | 安全规则 | 说明 |
|------|----------|------|
| `dontdoit_rooms` | **ADMINONLY** | 房间、淘汰列表、胜者 |
| `dontdoit_players` | **ADMINONLY** | 玩家、禁止动作 `myAction` |

索引建议（与贴头猜词相同）：

- `dontdoit_rooms.roomCode` — **唯一**
- `dontdoit_players` — `roomId` + `openId` **复合唯一**

## dontdoit_rooms 字段

| 字段 | 说明 |
|------|------|
| `roomCode` | 6 位口令 |
| `hostOpenId` | 组长 |
| `status` | `waiting` / `playing` / `finished` |
| `config` | `{ difficulty: easy\|medium\|hard }` |
| `eliminatedOpenIds` | 已淘汰 openId 数组 |
| `winnerOpenId` | 最后幸存者（单人） |
| `winnerOpenIds` | 结束时存活 openId 列表 |

## dontdoit_players 字段

| 字段 | 说明 |
|------|------|
| `roomId` | 房间 _id |
| `openId` | 微信 OPENID |
| `nickName` / `avatarUrl` | 资料 |
| `myAction` | 禁止动作（仅云函数读写） |
| `isEliminated` | 是否已淘汰 |
| `eliminatedAt` | 淘汰时间戳 |

## 云函数 `dontdoitRoomService`

| action | 说明 |
|--------|------|
| `ping` | 连通性，`buildId: dontdoit-repo-v1` |
| `create` / `createRoom` | 建房 |
| `join` / `joinRoom` | 进房 |
| `setConfig` | 难度 |
| `startGame` / `playAgain` / `restartGame` | 开局或 `finished` 后「再来一盘」：重发禁止动作、清空淘汰 |
| `syncState` / `getView` | 同步 view |
| `submitAction` / `submitGuess` | 自认犯规 → 淘汰 |
| `eliminatePlayer` | 组长强制淘汰 |
| `endGame` | 结束并结算幸存者 |

部署：右键 `cloudfunctions/dontdoitRoomService` → **上传并部署：云端安装依赖**（`wx-server-sdk@2.6.3`）。
