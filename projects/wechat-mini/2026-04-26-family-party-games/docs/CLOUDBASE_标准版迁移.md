# 云开发：个人版 → 标准版迁移清单

| 项目 | 环境 ID |
|------|---------|
| 原个人版（源，导出数据） | `cloud1-d9g01no7m292bc511` |
| **当前项目 / 目标环境** | `cloud1-d9g01no7m292bc511-d5e875d` |

代码已改：`cloud-env.js`、`cloudbaserc.json`、脚本与文档中的环境 ID。

**操作清单（控制台 + 上传小程序）：** 见 [`CLOUDBASE_你需要做的.md`](./CLOUDBASE_你需要做的.md)

**云函数：** 已通过 CLI 部署 18 个到标准版（含 `hostAgent` 单独重部署）；触发器是否启用请在控制台核对。

---

## 一、微信侧（必做）

### 1. 开发者工具绑定标准版

1. 打开 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 导入本项目 `2026-04-26-family-party-games`
3. 顶部 **云开发** → 环境切换为 **`cloud1-d9g01no7m292bc511-d5e875d`**
4. 若列表里没有：登录 [微信公众平台](https://mp.weixin.qq.com) → **开发** → **云开发** → 确认已开通标准版环境并关联本小程序 AppID

### 2. 部署全部云函数（推荐在工具里）

`cloudfunctions` 下每个文件夹 **右键** → **上传并部署：云端安装依赖**，至少包括：

| 云函数 | 说明 |
|--------|------|
| `drinkRoomService` | 趣味抽签（10 秒倒计时） |
| `undercoverRoomService` | 谁是卧底 |
| `werewolfService` | 狼人/身份推理 |
| `drawRoomService` | 你画我猜 |
| `musicRoomService` | 猜歌 |
| `headbandRoomService` | 贴头猜词 |
| `dontdoitRoomService` | 不要做挑战 |
| `roomService` | 真心话同房 |
| `userService` | 用户资料 |
| `shareService` / `riddleShare` | 分享解锁 |
| `gameStatsService` | 首页统计 |
| `aiPartyService` / `aiPlayer` | AI 词库与文案 |
| `imageService` | 海报生图 |
| `hostAgent` | 副主持（含定时触发器，务必用工具部署） |
| `hostAgentEnhanced` / `shareCardGenerator` | 增强能力（可选） |

或本机执行：

```bash
./scripts/deploy-all-cloudfunctions.sh
```

### 3. 上传小程序

编译 → **上传** → 公众平台选体验版/提审。  
用户端 `callFunction` 会读 `cloud-env.js` 的 `envId`，已指向标准版。

---

## 二、腾讯云 CloudBase 控制台要做的事

打开：https://tcb.cloud.tencent.com/dev?envId=cloud1-d9g01no7m292bc511-d5e875d

### 1. 数据库：迁移集合与数据

标准版是**新环境**，默认没有个人版里的房间/用户数据。任选一种：

**方式 A（推荐）控制台「环境迁移」**

若产品入口仍提供 **个人版 → 标准版 一键迁移**，在控制台按向导迁移数据库、云存储、云函数配置。

**方式 B 手动**

1. 在个人版环境导出各集合 JSON（或使用数据库备份）
2. 在标准版 **数据库** 中 **新建同名集合**
3. 导入数据

主要集合（按玩法）：

- 用户：`users`
- 趣味抽签：`drink_rooms`、`drink_players`、`drink_gameState`、`drink_votes`
- 卧底：`uc_rooms`、`uc_players`、`uc_state`
- 狼人：`werewolf_rooms`、`werewolf_state`
- 你画我猜：`draw_rooms`、`draw_players`、`draw_gameState`、`draw_canvas`
- 猜歌：`music_rooms`、`music_players`、`music_gameState`
- 贴头猜词：`headband_rooms`、`headband_players`
- 不要做：`dontdoit_rooms`、`dontdoit_players`
- 统计/分享：`game_clicks`、`share_tokens`、`share_unlock_users`、`agent_room_feed`、`share_riddles`、`share_cards`（可选）
- **勿用** `game_rooms`：本仓库代码未引用，可删或留空

4. **安全规则**：与各文档一致，业务集合建议 **仅云函数可写**（ADMINONLY），详见 `docs/HEADBAND_DB.md` 等

5. **索引**：重建唯一索引，例如 `roomCode`、复合 `roomId+openId`（建房失败常因缺索引）

### 2. 云存储（若有头像/音频/海报）

**存储** → 将个人版 `assets`、用户上传目录等同步到标准版（控制台迁移或手动上传）。

趣味抽签铃声：包内 `/assets/audio/ring.mp3`，一般不必放云存储。

### 3. 云函数：核对与权限

- **云函数** 页确认上表函数均为「部署完成」、修改时间为迁移后
- `shareCardGenerator`：配置开启 **`wxacode.getUnlimited`**（邀请卡小程序码）
- `hostAgent`：确认 **定时触发器** `autoTick` 已启用（应用 `cloudfunctions/hostAgent/config.json`）
- `aiPartyService` / `hostAgent`：标准版需在控制台开通 **AI+** / 混元 `hunyuan-lite`（与个人版相同能力）

### 4. 可选集合

- `share_cards`（分享卡片记录，无则自动跳过写入）

### 5. 计费与配额

标准版按量计费，确认账户余额/套餐；关注 **云函数调用次数**、**数据库读写**（个人版 20 万次用尽的问题在标准版配额更高）。

---

## 三、迁移后验证

1. 开发者工具 Console：

```javascript
wx.cloud.callFunction({ name: 'drinkRoomService', data: { action: 'ping' } })
```

2. 趣味抽签：2 人进房 → 开始本轮 → **10 秒倒计时** → 响铃  
3. 建房、进房、AI 解说、分享解锁各走一遍

---

## 四、控制台进度对照（你当前状态）

| 项 | 状态 | 说明 |
|----|------|------|
| 30 个集合已建 | ✅ | 与项目一致；`game_rooms` 可忽略或删除 |
| 安全规则（仅云函数可写） | ⚠️ 部分 | 见下表「待补规则」 |
| 数据从个人版导入 | ❌ | 空库可先用；要保留历史房间/用户再导入 |
| 索引 | ❌ | 不建会导致建房/进房报 duplicate / 查不到 |
| 云函数 | ✅ CLI 已部署 18 个 | 请在控制台核对；`hostAgent` 触发器需确认启用 |
| 云存储头像 | ❓ | 仅当 `users.avatarUrl` 为 `cloud://` 时需迁 |
| AI（混元 lite） | ❓ | `aiPartyService` / `hostAgent` 依赖 |

**建议执行顺序：** ① ~~部署云函数~~（已完成）→ ② 建索引 → ③ 补全安全规则 → ④ 确认 hostAgent 触发器 + AI → ⑤ 导入数据（可选）→ ⑥ 迁云存储（可选）→ ⑦ 上传小程序验证。

### 待补安全规则（与已设集合同样：**仅云函数可写**）

`uc_players`、`werewolf_state`（若未设）、`headband_rooms`、`headband_players`、`dontdoit_rooms`、`dontdoit_players`、`rooms`、`share_*`、`game_clicks`、`share_cards`、`analytics_share_unlock`

### 索引清单

| 集合模式 | 索引 | 类型 |
|----------|------|------|
| `*_rooms`（drink / uc / werewolf / draw / music / headband / dontdoit） | `roomCode` | 唯一 |
| `*_players`（同上含 drink / uc / draw / music / headband / dontdoit） | `roomId` + `openId` | 复合唯一 |
| `users` | `openId` 或 `_openid`（以 `userService` 查询字段为准） | 唯一，见 `docs/USERS_DB.md` |

`draw_canvas`、`drink_gameState` 等状态表一般按 `roomId` 普通索引即可，以各 `*_DB.md` 为准。

---

## 五、无需再做的

- 不要再向个人版 `cloud1-d9g01no7m292bc511` 部署新代码
- MCP 绑定标准版 `…-d5e875d` 后，`getFunctionList` 应在部署完成后能看到函数列表

---

## 六、回滚

若需临时回退个人版，把 `cloud-env.js` 的 `envId` 改回 `cloud1-d9g01no7m292bc511` 并重新上传小程序（不推荐长期双环境混用）。
