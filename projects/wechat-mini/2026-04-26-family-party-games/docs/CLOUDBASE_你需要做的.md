# 标准版迁移：我已做的 vs 你需要做的

**目标环境：** `cloud1-d9g01no7m292bc511-d5e875d`  
**控制台：** https://tcb.cloud.tencent.com/dev?envId=cloud1-d9g01no7m292bc511-d5e875d

---

## 一、我已在仓库 / CLI 完成的

| 项 | 状态 |
|----|------|
| `cloud-env.js` / `cloudbaserc.json` 指向标准版 | ✅ |
| 修正迁移文档里错误的 `…-d5e875d-d5e875d` | ✅ |
| 各云函数目录 `npm install` | ✅ |
| **18 个云函数部署到标准版**（`./scripts/deploy-all-cloudfunctions.sh`） | ✅ 2026-05-23 |
| 迁移说明 `docs/CLOUDBASE_标准版迁移.md` + 本清单 | ✅ |

已部署函数：`aiPartyService`、`aiPlayer`、`dontdoitRoomService`、`drawRoomService`、`drinkRoomService`、`gameStatsService`、`headbandRoomService`、`hostAgent`、`hostAgentEnhanced`、`imageService`、`musicRoomService`、`riddleShare`、`roomService`、`shareCardGenerator`、`shareService`、`undercoverRoomService`、`userService`、`werewolfService`。

**CLI 可一键应用**（本机已 `tcb login` 时）：`./scripts/apply-cloudbase-console.sh` — 索引、安全规则、hostAgent 触发器、shareCardGenerator 重部署。

**仍需手动**：开通混元 **hunyuan-lite**、**上传小程序**；跨环境数据/存储迁移（单环境可跳过）。

---

## 二、你需要做的（按顺序，约 30～60 分钟）

### 1. 微信开发者工具（必做）

1. 打开项目 `2026-04-26-family-party-games`
2. **不要选显示名为「cloud1」的环境**——那是**个人版**（EnvId 无 `-d5e875d` 后缀）。  
   请选 **标准版**（在工具里可能显示为 **`cloud1-d9g01no7m292bc511`**，不是 `cloud1`）  
   云开发 → **设置** → 环境 ID 必须是：**`cloud1-d9g01no7m292bc511-d5e875d`**

   | 开发者工具里常见显示名 | 环境 ID | 是否本项目 |
   |------------------------|---------|------------|
   | **cloud1** | `cloud1-d9g01no7m292bc511` | ❌ 个人版，勿用 |
   | **cloud1-d9g01no7m292bc511** | `cloud1-d9g01no7m292bc511-d5e875d` | ✅ 标准版，用这个 |

   `project.private.config.json` 已写入标准版 `env`，重开项目后云函数默认应对准标准版。
3. **仅对 `hostAgent` 再右键部署一次**（上传并部署：所有文件），然后在云开发 → 云函数 → `hostAgent` → **触发器** → 确认 **`autoTick` 启用**。
4. **编译 → 上传** 小程序（体验版/正式版）。

### 2. 真机/模拟器验证（必做）

开发者工具 **Console** 粘贴执行（**不能用 `require`**；本地可复制：`node scripts/verify-console-snippet.js`）：

```javascript
const STD_ENV = 'cloud1-d9g01no7m292bc511-d5e875d'
wx.cloud.callFunction({
  name: 'drinkRoomService',
  config: { env: STD_ENV },
  data: { action: 'getOpenId' },
  timeout: 15000
}).then(r => console.log('drink', r.result)).catch(console.error)
wx.cloud.callFunction({
  name: 'hostAgent',
  config: { env: STD_ENV },
  data: { action: 'ping' },
  timeout: 15000
}).then(r => console.log('hostAgent', r.result)).catch(console.error)
```

建议再测：趣味抽签 10 秒倒计时、贴头猜词「再来一局」、谁是卧底建房。

### 3. 历史数据 / 头像迁移 — **可跳过**

你只有 **一个** 云环境（界面叫 cloud1）时：

- **不用** 再做「个人版 → 标准版」导出/导入；当前库里的数据就是唯一环境的数据。
- **不用** 跨环境拷云存储；新上传的头像会进当前环境。
- 若极少数用户头像显示不出来（旧 `cloud://` 指向已失效的文件），让用户在小程序里 **重新选一次头像** 即可。

---

## 三、CloudBase 控制台必须做的

打开：https://tcb.cloud.tencent.com/dev?envId=cloud1-d9g01no7m292bc511-d5e875d

### A. 数据库 → 索引（不做会建房/进房失败）

对下列集合在 **索引** 页添加（字段名区分大小写）：

#### 各玩法房间 / 玩家（模式相同）

| 集合 | 索引字段 | 类型 |
|------|----------|------|
| `drink_rooms` | `roomCode` | 唯一 |
| `drink_players` | `roomId` + `openId` | 复合唯一 |
| `uc_rooms` | `roomCode` | 唯一 |
| `uc_players` | `roomId` + `openId` | 复合唯一 |
| `werewolf_rooms` | `roomCode` | 唯一 |
| `draw_rooms` | `roomCode` | 唯一 |
| `draw_players` | `roomId` + `openId` | 复合唯一 |
| `music_rooms` | `roomCode` | 唯一 |
| `music_players` | `roomId` + `openId` | 复合唯一 |
| `headband_rooms` | `roomCode` | 唯一 |
| `headband_players` | `roomId` + `openId` | 复合唯一 |
| `dontdoit_rooms` | `roomCode` | 唯一 |
| `dontdoit_players` | `roomId` + `openId` | 复合唯一 |

`werewolf_state`、`uc_state`：按 `roomId` 普通索引即可（文档以 `docs/WEREWOLF_DB.md`、`docs/UNDERCOVER_V2_DB.md` 为准）。

#### 分享 / 海龟汤 / 统计

| 集合 | 索引 | 类型 |
|------|------|------|
| `share_tokens` | `token` | 唯一 |
| `share_unlock_users` | `openId` + `sessionId` | 联合（非必须唯一） |
| `share_riddles` | `token` | 唯一 |
| `agent_room_feed` | `roomId` + `type` | 联合 |
| `game_clicks` | 无硬性要求 | — |

`users`：按 `_id` 读写，**可不建额外索引**（见 `docs/USERS_DB.md`）。

#### 状态表（建议普通索引 `roomId`）

`drink_gameState`、`draw_gameState`、`draw_canvas`、`music_gameState`、`drink_votes` 等。

---

### B. 数据库 → 安全规则

#### 仅云函数可写（ADMINONLY / 自定义 write:false）

若控制台有「仅管理端/云函数」模板，对下列集合统一设置：

`drink_rooms`、`drink_players`、`drink_votes`、`uc_rooms`、`uc_players`、`werewolf_rooms`、`draw_rooms`、`draw_players`、`draw_canvas`、`music_rooms`、`music_players`、`headband_rooms`、`headband_players`、`dontdoit_rooms`、`dontdoit_players`、`rooms`、`share_tokens`、`share_unlock_users`、`share_riddles`、`game_clicks`、`share_cards`、`analytics_share_unlock`、`users`（或按 `docs/USERS_DB.md` 仅本人可写）

#### 特殊：登录用户可读 + 仅云函数写

| 集合 | 说明 |
|------|------|
| `drink_gameState` | 多机 watch；见 `DRINK_ROOM_DB.md` |
| `music_gameState` | 同上，见 `docs/MUSIC_GUESS_DB.md` |
| `draw_gameState`、`draw_canvas` | 见 `docs/DRAW_GUESS_DB.md` |
| `uc_state`、`werewolf_state` | 全场同步；写仍仅云函数 |
| `agent_room_feed` | **read: true, write: false**（见 `docs/Agent聚会助手.md`） |

---

### C. 数据 / 云存储跨环境迁移 — **仅当你有两个环境 ID 时才做**

只有一个 cloud1 时 **跳过本节**。可选：删误建集合 **`game_rooms`**（代码未使用）。

---

### D. 云函数页核对

- 函数列表应有 **18 个**，修改时间为今日
- `shareCardGenerator`：**权限** 含 `wxacode.getUnlimited`（`config.json` 已写，部署后请在控制台确认）
- `hostAgent`：**超时 60s**；**触发器 `autoTick` 启用**
- `aiPartyService` / `hostAgent`：开通 **AI+ / 混元 hunyuan-lite**

路径：**云开发 → 扩展能力 / AI** 或腾讯云 TCB 控制台对应入口。

---

### E. 计费

标准版 `baas_pf_standard` 已确认正常；关注余额与云函数调用量。

---

## 四、快速勾选表

```
[ ] 开发者工具环境 = …-d5e875d
[ ] hostAgent 再部署 + autoTick 触发器启用
[ ] 数据库索引（上表 A）全部建好
[ ] 安全规则补全（上表 B），尤其 agent_room_feed 可读
[ ] （单环境可跳过）跨环境数据/存储迁移
[ ] AI hunyuan-lite 已开通
[ ] 上传小程序 + 真机 ping 通过
[ ] 趣味抽签 / 贴头猜词 / 卧底 各测一局
```

---

## 五、相关文档

- `docs/CLOUDBASE_标准版迁移.md` — 总览
- `DRINK_ROOM_DB.md`、`docs/HEADBAND_DB.md`、`docs/shareUnlock-部署与测试.md` — 各玩法细节
- `./scripts/deploy-all-cloudfunctions.sh` — 日后重部署全部函数
