# 疯狂猜歌 · 云开发数据设计

## 集合概览

| 集合 | 作用 |
|------|------|
| `music_rooms` | 房间与歌单、状态机（waiting / playing / finished） |
| `music_players` | 每局每人的 openId、昵称、是否房主、累计分 |
| `music_gameState` | 公屏状态，供全端 `watch`：当前曲、轮次、倒计时起点、本轮答中、日志等 |

所有写操作由云函数 `musicRoomService` 完成。客户端优先用 **`syncState`**（每秒轮询 + `watch` 兜底）拉公屏与本人视角；`music_gameState` 建议「登录用户可读、仅云函数可写」。

## `music_rooms` 文档字段

| 字段 | 说明 |
|------|------|
| `roomCode` | 6 位数字字符串，唯一（查询用） |
| `hostOpenId` | 房主的 `OPENID` |
| `status` | `waiting` \| `playing` \| `finished` |
| `totalRounds` | 5 / 10 / 15，与开局随机抽题数量一致 |
| `roundDuration` | 每轮秒数，默认 30，用于云函数判题超时 |
| `rounds` | 数组。每项含 `id`, `title`, `aliases[]`, `audioUrl`（开局时从云函数内曲库 `shuffle` 后写入） |
| `createdAt` / `updatedAt` | 时间戳 |

## `music_players` 文档字段

| 字段 | 说明 |
|------|------|
| `roomId` | 对应 `music_rooms._id` |
| `openId` | 用户 `OPENID` |
| `nickName` | 昵称，≤12 字 |
| `isHost` | 是否房主（与 `hostOpenId` 一致时为 true） |
| `score` | 本局累计分；首中 +3、再中 +1 由 `submitAnswer` 更新 |
| `joinedAt` / `updatedAt` | 可选 |

建索引建议：`roomId` + `openId` 组合查询；若用「房间码进房」较多，可给 `music_rooms.roomCode` 建唯一索引（逻辑上在应用层也做了冲突重试）。

## `music_gameState` 文档字段

文档 `_id` **等于** `roomId`（`music_rooms._id` 的字符串形式），方便客户端 `doc(roomId).watch()`。

| 字段 | 说明 |
|------|------|
| `roomId` / `roomCode` / `status` / `hostOpenId` | 与房同步的摘要 |
| `totalRounds` / `roundDuration` | 同上 |
| `currentIndex` | 当前第几首（0-based），未开局可为 -1 |
| `playToken` | 每开始一首或切歌自增（保留字段，便于以后扩展） |
| `roundStartTime` | 本轮开始时间（ms），用于端上倒计时与云端超时判题 |
| `roundHostOpenId` / `roundHostNickName` | **组长（房主）**固定为当轮主持，公屏只显示 Ta 的昵称，**不**公布歌名 |
| `phase` | `waiting` \| `round_playing` \| `finished` |
| `publicPlayers` | 按分数排序的 `{ openId, nickName, score }[]` |
| `roundHits` | 本轮已答中列表：`openId`, `nickName`, `order`, `points` |
| `publicLog` | 简短系统文案数组 |
| `finishedAt` | 结束时时间戳，可选 |

## 权限与索引（建议）

- **仅云函数写** `music_rooms`、`music_players`：在控制台将这两集合的「增删改」限制为仅管理端/云函数（具体以当前微信云开发安全规则为准），避免客户端改分、改歌单。
- **`music_gameState`**：可设为「所有登录用户可读」、仅云函数可写，便于多机 `watch` 同步；**歌名/答案不写入公屏**，仅 `getView` 对**当轮主持**返回 `hostPlayTitle` / 别名，供其在本机用音乐 App 外放。

**玩法说明**：不依赖小程序内嵌音频统一播放；**轮次主持**用手机自行搜索、外放，其他人抢答。`rounds` 中仍可有 `audioUrl` 字段（曲库元数据），客户端可不使用。

## 云函数 `musicRoomService` 的 action

| action | 说明 |
|--------|------|
| `create` | 建 `music_rooms`、房主进 `music_players`、写初始 `music_gameState` |
| `join` | 凭 `roomCode` 进房；满员/已结束/无效码时返回错误信息 |
| `setRounds` | 仅房主、等待中：设置 `totalRounds` |
| `startGame` | 仅房主：洗牌抽题、写 `rounds`、**组长为当轮主持**、`status=playing`、首轮 `round_playing` |
| `nextSong` | 仅房主：未结束则进下一题、重置 `roundHits` 等（主持仍为组长）；最后一题后再点则全剧终 |
| `submitAnswer` | 非**当轮主持**可抢答；主持提交返回 `hostNoGuess`；首中 +3 等计分规则不变 |
| `getView` | `isHost` 房主；`isRoundHost` 当轮主持；**仅当轮主持**能拿到 `hostPlayTitle` / `hostPlayAliases` 与无 URL 的 `currentSong` 摘要 |

曲库在 `cloudfunctions/musicRoomService/songs.js`；客户端判题以云为准，不重复维护答案逻辑。
