# Changelog

## 2026-05-19 同场聚会组：成员刷新与开始失败说明（闭环）

### 统一能力（`utils/roomUi.js`）

- `memberCountLine` / `refreshCloudDoc` / `runStartAction`：各玩法共用「人数展示、返回页拉取、开始前校验 + 失败弹窗」。
- `scripts/test-room-ui.js`：Node 单测各玩法失败文案（`node scripts/test-room-ui.js`）。

### 已覆盖的云同场页面

| 玩法 | 成员刷新 | 开始失败弹窗 | 分享带 roomId |
|------|----------|--------------|---------------|
| 趣味抽签 | onShow + watch | ✓ | ✓ |
| 谁是卧底 | onShow + watch + loadView 修复 | ✓ | ✓ |
| 身份推理 | onShow + watch + loadView 合并成员 | ✓ | ✓ |
| 你画我猜 | onShow + watch | ✓ | ✓ |
| 疯狂猜歌 | onShow + watch | ✓ | ✓ |

### 云调用

- `drawRoomCloud` / `musicRoomCloud` / `werewolfCloud` / `drinkRoomCloud`：`onError` 附带 `{ result }` 便于弹窗解析。
- `roomCloud`：`success` 时若 `result.errMsg` 走 `onError`（与云函数 throw 对齐）。

### 2026-05-19 AI 聚会助手

- `utils/aiHelper.js`：`wx.cloud.extend.AI` + `deepseek-v4-flash`，失败可兜底 `aiPartyService` 云函数。
- `cloud-env.js` 默认环境 `cloud1-d9g01no7m292bc511-d5e875d`。
- 趣味抽签：结果页 AI 解说 / 趣味任务建议。
- 谁是卧底：AI 出题并发牌（`setCustomPair`）、结束战报文案。
- 你画我猜：AI 出题（`setPendingWord`）。
- 真心话大冒险 / 故事接龙：AI 出新题、加码、同场点评。
- 身份推理 / 猜歌：结束战报、主持开场词。

### 2026-05-19 朋友圈分享

- 新增 `utils/shareHelper.js`：`onShareTimeline`（`query` 参数）、`wx.showShareMenu` 双通道。
- 首页及同场玩法页、`play` 真心话大冒险均已实现；各页 `*.json` 增加 `enableShareTimeline: true`。

### 2026-05-19 补充

- 各同场页 + 真心话大冒险：页内 `<button open-type="share">邀请朋友</button>`（沿用各页 `onShareAppMessage`）。
- `pages/play`：接入 `roomUi`（人数展示、`tdStart` 失败弹窗、`onShow` 刷新）。
- `musicRoomService`：`startGame` 强制至少 2 人（与前端校验一致）。

## 0.1.0

- 新建家庭小游戏微信小程序。
- 实现首页、谁是卧底、真心话大冒险、你画我猜、故事接龙、逛三园。
- 增加内置词库、题库和扩展路线文档。
- 切换回原生微信小程序页面实现，移除小游戏 Canvas 入口。

## 2026-05-16 提审前合规与稳定性优化

### 合规文案调整（消除竞技/排名/对战暗示）

- `pages/song-guess/song-guess.wxml`：「最终排名」→「本环节得分（同场参考）」；输入框占位「用于排行榜」→「用于本局昵称展示」。
- 全局替换「无线上对战/竞技」为「无广域联机」（涉及页面：`setup.wxml`、`setup.js`、`undercover.wxml`、`draw-guess.wxml`）。
- `data/game-data.js` 中「袋鼠跳跳跳」的摘要「排名」→「同场计分参考」。

### 主持权移交（roomService 云函数）

- 新增 `transferHost` action：允许当前主持将主持权移交给指定成员（需传入 `targetOpenId`）。
- 新增 `abdicateHost` action：主持卸任时将主持移交给最早加入房间的成员（按 `joinedAt` 升序）。
- 已在 `exports.main` 中注册对应路由。

### 多人同步优化

- `pages/undercover/undercover.js`：`watch` 回调中增加状态签名比对（阶段、轮次、人数、票数、发言位、日志长度、平票 ID、读词进度等），仅当真正变化时才调用 `loadView`，减少冗余云函数调用。
- `pages/play/play.js`：恢复 2 秒轮询，同时拉取状态与成员列表；主持在「随机选一位」前可通过 `wx.showActionSheet` 主动移交主持权或交给最早进组成员。

### 其他

- `utils/roomCloud.js`：修正注释中关于「全项目仅此处 callFunction」的过时描述。
