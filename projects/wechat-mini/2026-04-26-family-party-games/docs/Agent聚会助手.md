# Agent 聚会助手

基于 **云函数 `hostAgent` / `aiPlayer`** + 可选 **云开发 Agent Bot**（`wx.cloud.extend.AI.bot.sendMessage`）。

## 配置（`cloud-env.js`）

```javascript
agentBotId: 'party-host-agent',  // ping 展示用；可改为你自己的标识
agentEnabled: true,
agentAutoHost: true,             // 组长端自动 tick 推进
```

云函数 `hostAgent/config.json`：

| 项 | 值 | 说明 |
|----|-----|------|
| `timeout` | **60** | AI 调用需较长时间（云端若仍为 3s 请重新部署） |
| `envVariables.AGENT_BOT_ID` | `party-host-agent` | 可选；`ping` 返回的 botId |

云函数环境变量（可选，与上表二选一即可）：

- `AGENT_HOST_TOKEN`：默认 `family-party-agent-v1`，与 `drinkRoomService` / `undercoverRoomService` 的 `_agentAuth` 一致
- `AGENT_BOT_ID`：如 `party-host-agent`（未配置不影响 tick / 播报 / 战报等基础功能）

## 部署前检查清单

| 检查项 | 代码状态 | 你需要操作 |
|--------|----------|------------|
| `hostAgent/config.json` | ✅ `timeout: 60`，`triggers.autoTick` 已配置 | 部署前在本地打开文件核对一眼 |
| 云函数重新部署 | — | 微信开发者工具 → 右键 **hostAgent** → **上传并部署：所有文件** |
| 触发器启用 | — | 控制台 → 云函数 → **hostAgent** → **触发器** → `autoTick` 为「启用」 |
| `agent_room_feed` 集合 | — | 数据库 → 添加集合 → 名称 **`agent_room_feed`** |
| `aiPlayer` / 房间服务 | 代码已有 | 建议一并部署 `aiPlayer`、`drinkRoomService`、`undercoverRoomService` |

### `agent_room_feed` 权限建议

仅云函数写入（`notify.js`），客户端只读时可设：

```json
{
  "read": true,
  "write": false
}
```

按房间隔离（需自行调整 `rooms` 路径与字段名）：

```json
{
  "read": "doc.roomId == auth.openid || get('rooms/' + doc.roomId).data.hostOpenid == auth.openid",
  "write": false
}
```

### 定时器与费用（⚠️）

- 当前 cron：`0 */1 * * * * *`（约 **每分钟** 一次）
- `autoTick.js` 单次最多处理 **10** 个活跃房间；有播报才写 `agent_room_feed`
- 有 AI 推进时约 **500–1000 tokens/次**；10 房 × 60 次/小时 ≈ 大量调用，注意额度
- 降频示例（改 `config.json` 后需重新部署）：`0 0 */5 * * * *`（每 5 分钟）
- **暂停定时器**：控制台 → hostAgent → 触发器 → **暂停**（组长端 `runHostTick` 仍可用）

**tccli 改超时**（可选）：`npm run set-scf-timeout` 或单独指定 `hostAgent`。

## 部署步骤（简要）

1. 右键上传 **`hostAgent`**、**`aiPlayer`**（**上传并部署：所有文件**）
2. 控制台确认 **触发器 autoTick**、创建 **`agent_room_feed`**
3. 编译小程序，基础库 ≥ 3.15.1

## 已实现的副主持功能（`hostAgent`）

| action | 功能 |
|--------|------|
| `ping` | 测试连通，返回 `botId` 与 `hasAi` |
| `tick` | 自动推进游戏（组长端定时调用） |
| `playerAssist` | 玩家策略建议（不泄露身份） |
| `hostNarrate` | 主持播报（控场语音，40 字内） |
| `recap` | 游戏战报（MVP、搞笑、高光） |
| `recommend` | 推荐下次游戏与人数配置 |

## 小程序调用示例

```javascript
const { getCallFunctionConfig } = require('../../utils/cloudInit')

// 副主持播报
wx.cloud.callFunction({
  name: 'hostAgent',
  config: getCallFunctionConfig(),
  data: {
    action: 'hostNarrate',
    gameKind: 'werewolf',
    roomId: 'room-123'
  },
  success: (res) => {
    console.log('副主持说：', res.result.speakText || res.result.text)
  }
})

// 自动推进（tick）
wx.cloud.callFunction({
  name: 'hostAgent',
  config: getCallFunctionConfig(),
  data: {
    action: 'tick',
    gameKind: 'drink',
    roomId: 'room-123',
    autoExecute: true
  }
})

// 玩家策略建议
wx.cloud.callFunction({
  name: 'hostAgent',
  config: getCallFunctionConfig(),
  data: {
    action: 'playerAssist',
    gameKind: 'undercover',
    roomId: 'room-123',
    playerHint: '我是平民，怀疑3号是卧底'
  }
})
```

项目内推荐封装：`utils/hostAgentCloud.js`、`utils/agentHelper.js`（Bot 优先，失败降级云函数）。

## Bot 调用示例（客户端，需控制台创建 Agent 并填 `agentBotId`）

```javascript
const res = await wx.cloud.extend.AI.bot.sendMessage({
  data: {
    botId: '<YOUR_AGENT_ID>',
    threadId: '...',
    messages: [{ id: 'msg-1', role: 'user', content: '你好' }],
    tools: [],
    context: [],
    state: {}
  }
})
```

## 部署后验证

```javascript
const { getCallFunctionConfig } = require('../../utils/cloudInit')
const cfg = getCallFunctionConfig()

// 1. ping — 期望 { ok: true, botId: 'party-host-agent', hasAi: true }
wx.cloud.callFunction({
  name: 'hostAgent',
  config: cfg,
  data: { action: 'ping' }
}).then((res) => console.log('ping', res.result))

// 2. 带场景播报 — 期望含 speakText, scene, voiceUrl 或 useClientTTS
wx.cloud.callFunction({
  name: 'hostAgent',
  config: cfg,
  data: {
    action: 'hostNarrate',
    gameKind: 'undercover',
    roomId: 'test-room',
    scene: 'vote',
    customVars: { player: '测试玩家' }
  }
}).then((res) => console.log('hostNarrate', res.result))

// 3. 手动 tick
wx.cloud.callFunction({
  name: 'hostAgent',
  config: cfg,
  data: { action: 'tick', gameKind: 'undercover', roomId: 'test-room' }
}).then((res) => console.log('tick', res.result))

// 4. 定时 autoTick — 等 1 分钟或在控制台手动触发，查 agent_room_feed 是否有新文档
```

**玩法冒烟**：首页长按标题 → AI 连通；趣味抽签开「副主持」→ 自动揭晓；「策略建议」有文案。

## 定时自动 tick（云函数触发器）

`hostAgent/config.json` 已配置：

```json
"triggers": [{
  "name": "autoTick",
  "type": "timer",
  "config": "0 */1 * * * * *"
}]
```

每分钟扫描 `drink_rooms` / `uc_rooms` / `werewolf_state` 中的进行中房间并 `runTick`；播报写入集合 **`agent_room_feed`**（需控制台创建并设读权限）。

部署后须在 **云开发控制台 → 云函数 → hostAgent → 触发器** 确认 `autoTick` 已启用。

## 播报模板与语音

- `templates.js`：按 `gameKind` + `scene`（如 `vote`、`midgame`）选系统提示与预设句
- `voice.js`：尝试 `extend.AI` 的 `speech`；失败则 `useClientTTS: true` 由小程序 Toast/朗读
- `hostNarrate` 返回：`speakText`、`voiceUrl`、`useClientTTS`

```javascript
const { runHostNarrate } = require('../../utils/agentHelper')
runHostNarrate(page, {
  gameKind: 'undercover',
  roomId: 'room-123',
  scene: 'vote',
  customVars: { player: '张三' },
  voiceSpeed: 4
})
```

或原始 `callFunction`：

```javascript
wx.cloud.callFunction({
  name: 'hostAgent',
  config: getCallFunctionConfig(),
  data: {
    action: 'hostNarrate',
    gameKind: 'undercover',
    roomId: 'room-123',
    scene: 'vote',
    customVars: { player: '张三' },
    voiceSpeed: 4
  }
}).then((res) => {
  const { playHostVoice } = require('../../utils/agentTts')
  playHostVoice(res.result)
})
```

## AI 调用链（`hostAgent/ai.js`）

1. **优先** `cloud.extend.AI`（hunyuan / cloudbase 多模型）
2. **失败则** `cloud.callFunction({ name: 'aiPartyService', action: 'chat' })`（含 OpenAPI Key 兜底）

与小程序 `aiHelper.js` 策略一致；`hostAgent` 与 `aiPartyService` 部署在**同一云环境**即可互通。

## 说明

- **组长端 tick**：仍可由页面每 2.5s 调用 `runHostTick`（与定时器并行，注意频率）
- **语音**：云端 TTS 未开通时自动降级 Toast
- Agent 仅辅助聚会，不替代支付等敏感操作
