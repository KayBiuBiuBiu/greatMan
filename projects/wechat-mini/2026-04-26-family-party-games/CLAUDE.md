# CLAUDE.md — 家庭聚会助手

本文档为微信小程序「家庭聚会助手」的开发指南。

> **Coding Plan 与 Agent 测 Minium**：改代码前/改完后读 [`minium-tests/CODING_PLAN.md`](../../minium-tests/CODING_PLAN.md)。

## 项目概述

一个原生微信小程序，为线下同场家庭/亲友聚会提供**互动游戏和辅助工具**。核心特性：
- **面对面私密房间**：通过 4 位数字口令创建房间，参与者同场加入
- **多人同步**：基于云开发（CloudBase）的实时状态同步
- **AI 助手**：游戏 AI 出题、战报文案、建议
- **游戏分类**：A类（主持人驾驭）、B类（快速传递手机）、C类（辅助工具）

## 项目结构

```
2026-04-26-family-party-games/
├── app.js / app.json                    # App 入口和全局配置
├── cloud-env.js                         # 云环境 ID 管理
├── cloudbaserc.json                     # CloudBase 配置
├── 
├── pages/                               # 主要页面（主包）
│   ├── index/                           # 首页（游戏分类导航）
│   ├── setup/                           # 房间创建/加入页
│   └── share/card/                      # 分享卡片页
│
├── packageGames/                        # 游戏子包（代码分割）
│   ├── utils/                           # 游戏通用工具
│   │   ├── roomJoin.js                  # 进入房间逻辑
│   │   ├── roomUi.js                    # 成员列表、开始校验
│   │   ├── roomMemberUi.js              # 成员显示补丁
│   │   ├── roomLobbyReady.js            # 大厅就绪状态
│   │   ├── partyAiRoomHooks.js          # AI 房间生命周期
│   │   ├── aiHelper.js                  # AI 出题、战报
│   │   ├── aiHost.js                    # AI 主持增强菜单
│   │   ├── inRoomCloudSync.js           # 同场状态轮询
│   │   └── roomCopy.js                  # 房间号复制工具
│   │
│   ├── play/                            # 真心话大冒险
│   ├── undercover/                      # 谁是卧底
│   ├── werewolf/                        # 身份推理（狼人杀）
│   ├── draw-guess/                      # 你画我猜
│   ├── song-guess/                      # 疯狂猜歌
│   ├── drink-party/                     # 趣味抽签
│   ├── headband/                        # 贴头猜词
│   ├── dontdoit/                        # 不要做挑战
│   ├── mystery-reason/                  # 秘密身份推理
│   └── data/                            # 游戏题库数据
│
├── cloudfunctions/                      # 云函数（后端）
│   ├── common/                          # 公共模块
│   ├── roomService/                     # 房间管理（核心）
│   ├── undercoverRoomService/           # 谁是卧底
│   ├── werewolfCloud/                   # 身份推理
│   ├── drawRoomService/                 # 你画我猜
│   ├── musicRoomService/                # 疯狂猜歌
│   ├── drinkRoomService/                # 趣味抽签
│   ├── headbandRoomService/             # 贴头猜词
│   ├── dontdoitRoomService/             # 不要做挑战
│   ├── mysteryReasonRoomService/        # 秘密身份推理
│   ├── aiPartyService/                  # AI 聚会助手
│   ├── hostAgent/                       # 主持 Agent（已弃用）
│   └── [其他服务]
│
├── utils/                               # 全局工具库
│   ├── cloudInit.js                     # Cloud 初始化
│   ├── userProfile.js                   # 用户档案
│   ├── userHelper.js                    # 用户辅助
│   ├── shareHelper.js                   # 朋友圈分享
│   ├── shareCard.js                     # 分享卡片 URL
│   ├── aiUnlock.js                      # AI 解锁系统（分享解锁）
│   ├── [游戏特定的 Cloud Wrapper]       # 如 undercoverRoomCloud.js
│   └── [其他通用工具]
│
├── data/
│   ├── game-data.js                     # 游戏分类、描述、词库
│   └── feature-flags.js                 # 功能开关
│
├── docs/                                # 技术文档
│   ├── ROADMAP.md                       # 功能路线
│   ├── UNDERCOVER_V2_DB.md              # 谁是卧底数据库设计
│   ├── WEREWOLF_AI_HOST.md              # 身份推理 AI 主持
│   ├── DRAW_GUESS_DB.md                 # 你画我猜
│   ├── MUSIC_GUESS_DB.md                # 疯狂猜歌
│   ├── [其他 DB 设计文档]
│   ├── UI与逻辑规范.md                   # UI/逻辑规范
│   ├── CLOUDBASE_标准版迁移.md          # 云开发迁移指南
│   ├── AI聚会助手.md                     # AI 能力说明
│   └── Agent聚会助手.md                  # Agent（主持 AI）说明
│
├── scripts/                             # 本地脚本
│   ├── test-room-ui.js                  # 房间 UI 单测
│   └── [其他工具脚本]
│
├── project.config.json                  # 微信开发者工具配置
├── project.private.config.json          # 私有配置（不提交）
├── sitemap.json                         # 小程序路由地图
├── .env.example                         # 环境变量示例
└── README.md / CHANGELOG.md             # 项目说明和变更日志
```

## 关键概念

### 房间（Room）生命周期

**状态机**：`waiting` → `lobby` → `running` → `ended` → `closed`

- **waiting**：初始化中，等待成员就位（主持看不到成员）
- **lobby**：成员已加入，等待主持点击「开始」
- **running**：游戏进行中，依据具体游戏逻辑进展各阶段
- **ended**：游戏结束，展示结果
- **closed**：房间关闭（4 小时 TTL 自动清理）

**核心数据库**：`rooms` 集合（CloudBase）
```javascript
{
  _id: '房间唯一 ID',
  roomCode: '0001',              // 4 位数字口令
  status: 'lobby',               // 房间状态
  game: 'undercover',            // 游戏类型
  hostOpenId: 'wxabc123',        // 主持人 OpenID
  players: [                      // 参与者
    {
      openId: 'wxabc123',
      nickName: '张三',
      avatarUrl: 'https://...',
      isHost: true,
      joinedAt: 1234567890000,
      profileReady: true          // 用户档案已加载
    }
  ],
  gameState: { ... },            // 游戏特定状态
  createdAt: 1234567890000,
  updatedAt: 1234567890000
}
```

### 云函数调用模式

所有游戏通过**统一的 Cloud SDK 包装**与云函数通信：

```javascript
// utils/undercoverRoomCloud.js（示例）
async function callUndercoverService(action, data) {
  // callFunction -> undercoverRoomService/index.js
  // action: 'startGame', 'vote', 'eliminate'...
  // onError 包含 { result } 便于前端解析失败原因
}
```

每个游戏有专属的 Cloud Wrapper（如 `drawRoomCloud`、`werewolfCloud`），统一处理：
- 错误重试逻辑
- 结果验证
- 状态署名对比（减少冗余调用）

### AI 助手能力

**接入点**：`utils/aiHelper.js`

通过 `wx.cloud.extend.AI` 使用 DeepSeek v4-flash 模型：
- **出题**：`runAi(prompt)` → 生成词对、题目、建议
- **战报**：`runAiPoster(prompt)` → 生成趣味文案
- **主持开场**：`runAiOpenings(prompt)` → AI 预设话术

失败后自动兜底到 `aiPartyService` 云函数（基于规则生成）。

### 分享与解锁

**朋友圈分享**：`utils/shareHelper.js`
- 通过 `onShareTimeline` 回调处理分享
- 分享卡片包含房间 ID（`roomId` 查询参数）
- 分享后新用户加入时获得解锁奖励

**分享解锁系统**：`utils/aiUnlock.js`
- `LEVEL`：解锁等级（分享数量对应奖励）
- `shareUnlockFeed`：喂入分享计数，触发 AI 能力解锁
- `shareUnlockCopy`：复制本地分享邀请卡片文案

### 用户档案管理

**核心模块**：`utils/userProfile.js`

```javascript
// 用户档案对象
{
  openId: 'wx...',
  nickName: '用户昵称',
  avatarUrl: 'https://...',
  profileReady: true,           // 首次进入后标记为就绪
  inRoomSince: 1234567890000    // 进房时间戳
}
```

**同步模式**：
1. 前端 `onLoad` 时通过 `withJoinProfile` 收集用户信息
2. 调用 `roomCloud.joinRoom` 传入档案
3. 云函数存储到 `players.profileReady = true`
4. 其他成员通过 `watch` 或轮询检测到就绪状态

## 开发工作流

### 1. 本地开发

**准备环境**：
```bash
# 打开微信开发者工具
# 选择项目目录：/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
# 点击「编译」开始预览
```

**关键配置**：
- `project.config.json`：编译配置、AppID、云函数根目录
- `.env`（可选）：本地环境变量（如模拟用户 OpenID）
- `cloud-env.js`：默认云环境 ID，可按需覆盖

**小程序 IDE 快捷键**：
- `Ctrl/Cmd + B`：编译
- `Ctrl/Cmd + R`：刷新预览
- DevTools 控制台查看日志和错误

### 2. 添加新游戏

**步骤**：

1. **在 `data/game-data.js` 中声明游戏**：
   ```javascript
   {
     title: '新游戏名',
     status: '已实现',
     summary: '游戏描述'
   }
   ```

2. **创建子包页面** `packageGames/<game-name>/`：
   ```
   game-name/
   ├── game-name.js     # 页面逻辑
   ├── game-name.json   # 配置（可复用 roomUi）
   ├── game-name.wxml   # UI 模板
   └── game-name.wxss   # 样式
   ```

3. **页面依赖结构**：
   ```javascript
   // 导入通用工具
   const { enterCloudRoomOnLoad } = require('../utils/roomJoin')
   const { memberCountLine, runStartAction } = require('../utils/roomUi')
   const { enableShareMenus, handleShareAppMessage } = require('../../utils/shareHelper')
   
   Page({
     data: {
       players: [],
       gameState: {}
     },
     onLoad(opts) {
       enterCloudRoomOnLoad(opts, this)  // 加入房间
     },
     async onShow() {
       // 刷新成员列表
       await refreshCloudDoc()
     },
     // 页面事件处理...
   })
   ```

4. **云函数**（如需多人同步）：
   ```
   cloudfunctions/<game-name>RoomService/
   ├── index.js         # 主逻辑
   ├── package.json
   └── wx-server-sdk/   # 依赖
   ```
   - 处理游戏状态转移
   - 验证玩家操作合法性
   - 广播状态变化

5. **在 `app.json` 中注册页面**：
   ```json
   {
     "subpackages": [{
       "root": "packageGames",
       "pages": ["game-name/game-name"]
     }]
   }
   ```

### 3. 状态同步模式

**模式 A：轮询（常用）**
```javascript
// 每隔 N 秒从 Cloud 拉取最新房间状态
const poll = setInterval(async () => {
  const room = await roomCloud.queryRoom(this.data.roomCode)
  this.setData({ gameState: room.gameState })
}, 2000)
```

**模式 B：Watch（推荐做状态签名对比）**
```javascript
// 打开数据库实时监听
const watcher = db.collection('rooms')
  .where({ roomCode })
  .watch({
    onChange: (snapshot) => {
      const room = snapshot.docs[0]
      // 检查签名：仅当关键字段变化时才更新 UI
      if (stateSignatureChanged(room)) {
        this.loadView(room)
      }
    },
    onError: (err) => console.error(err)
  })
```

**减少冗余调用**：
```javascript
// utils/undercoverRoomCloud.js
function buildStateSignature(room) {
  // 阶段、轮次、人数、票数、发言位、日志长度、平票 ID、读词进度
  return `${room.phase}|${room.round}|${room.players.length}|...`
}

// 仅当签名不同时调用 loadView
if (newSignature !== this.data._stateSignature) {
  this.loadView(room)
  this.setData({ _stateSignature: newSignature })
}
```

### 4. 错误处理

**云函数调用错误**：
```javascript
// 云函数通过 result.errMsg 传递错误
callGameService('startGame', { ... })
  .catch(err => {
    const { result, errMsg } = err
    if (result && result.errMsg) {
      wx.showToast({ title: result.errMsg, icon: 'error' })
    } else {
      wx.showToast({ title: errMsg || '网络错误', icon: 'error' })
    }
  })
```

**房间校验失败**：
```javascript
// roomUi.js 中 buildStartChecks() 返回检查结果
const checks = buildStartChecks(players, minPlayers)
if (!checks.pass) {
  wx.showModal({
    title: '无法开始',
    content: checks.reason,  // 如「至少需要 3 人」
    showCancel: false
  })
}
```

## AI 集成指南

### 快速调用 AI

```javascript
const { runAi, runAiPoster } = require('../utils/aiHelper')

// 出题或生成内容
const result = await runAi({
  prompt: '为 3 个人生成一对相反的词语，一个词是真词，一个是卧底词。',
  maxTokens: 200
})

// 如需尝试两次（失败时调用云函数兜底）
const result = await runAi(prompt, true)  // withFallback = true
```

### 战报文案生成

```javascript
const { runAiPoster } = require('../utils/aiHelper')

const recap = await runAiPoster({
  prompt: `
    游戏：谁是卧底
    获胜方：真人队
    词对：(香蕉, 黄瓜)
    请写一段趣味战报文案，50-100字。
  `,
  maxTokens: 150
})
```

### 主持开场词

```javascript
const { runEnhancedAgentMenu } = require('../utils/aiHost')

// 获取 AI 主持建议或开场词
const openings = await runEnhancedAgentMenu('谁是卧底', 6)
```

## 测试与调试

### 单元测试

```bash
# 测试房间 UI 各玩法的开始失败文案
node scripts/test-room-ui.js
```

### 本地模拟多用户

**方法 1：多窗口**
- 打开两个微信开发者工具窗口
- 每个窗口设置不同的 OpenID（修改 `.env`）
- 一个窗口主持，一个窗口加入

**方法 2：模拟云数据**
```javascript
// app.js 中注入测试数据
if (__DEV__) {
  globalThis.TEST_ROOM = {
    roomCode: '0001',
    hostOpenId: 'test-host',
    players: [...]
  }
}
```

### 日志输出

```javascript
// 云函数日志
console.log('房间状态:', room)  // 微信开发者工具云函数管理面板可查看

// 前端日志
console.log('State signature changed')
// 开发者工具 Console 或 wechat_debug.log
```

### 云开发管理

打开微信开发者工具 → 云开发 → 数据库管理：
- 查看 `rooms` 集合中的房间数据
- 查看云函数执行日志
- 监控代码效率（如函数执行时间）

## 常见问题

### 房间成员不同步

**症状**：A 加入房间后，B 看不到 A

**排查**：
1. 检查 `profileReady` 是否标记为 `true`
   - 在 `pages/setup/setup.js` 中调用 `withJoinProfile` 收集用户档案？
   - 通过 `roomCloud.joinRoom` 传递到云函数？
2. 检查轮询或 watch 是否正确启动
   - `onShow` 中调用 `refreshCloudDoc`？
   - 状态签名对比是否正确（避免 `loadView` 过度调用）？
3. 云函数日志中是否有错误

### AI 出题失败

**症状**：AI 对话超时或返回错误

**排查**：
1. 检查 `wx.cloud.extend.AI` 是否初始化（在 `app.js` 中调用了 `wx.cloud.init` 吗？）
2. 云环境 ID 是否正确（见 `cloud-env.js`）
3. 查看控制台或云函数日志中的 AI 调用记录
4. 如持续失败，改用 `aiPartyService` 云函数生成内容（自动兜底）

### 分享卡片不显示

**症状**：分享朋友圈后，新用户点击卡片无反应或崩溃

**排查**：
1. 检查 `onShareAppMessage` 和 `onShareTimeline` 是否定义
2. 确保分享卡片 URL 正确包含 `roomId` 查询参数
3. 新用户通过卡片进入时，`onLoad` 中是否解析了 `roomId`？
4. 分享卡片页面（`pages/share/card/`）是否正确处理了房间加入逻辑

### 云函数部署失败

**症状**：编译后云函数仍显示「未部署」或「部署失败」

**排查**：
1. 确认 `cloudbaserc.json` 中环境 ID 正确
2. 检查云函数文件夹是否包含 `index.js` 和 `package.json`
3. 在微信开发者工具中右键云函数 → 增量上传
4. 查看上传日志（通常在工具右下角通知区域）

## 性能优化建议

1. **减少云函数调用**：
   - 使用状态签名对比，仅在真正变化时更新 UI
   - 批量操作（如多个投票）可合并为一次云调用

2. **加快页面加载**：
   - 子包预加载规则已配置（见 `app.json` 的 `preloadRule`）
   - 游戏数据（词库）通过 `packageGames/data/` 延迟加载

3. **减少网络消耗**：
   - 前端缓存用户档案（避免每次重新拉取）
   - 房间 TTL 设为 4 小时，避免过度查询已关闭的房间

4. **AI 成本控制**：
   - 出题失败后改用规则生成或本地题库
   - 限制 AI 调用频率（如每局仅 1-2 次 AI 出题）

## 部署清单

**发布前**：
- [ ] 所有页面在微信开发者工具中正常运行
- [ ] 测试主持和非主持角色的功能
- [ ] 验证分享卡片和解锁流程
- [ ] 云函数已部署并通过测试
- [ ] 移除 `__DEV__` 模拟数据

**上线步骤**：
1. 在微信开发者工具点击「上传」
2. 在微信公众平台「管理」→ 「版本管理」中配置版本说明
3. 提交审核或直接灰度发布

参考：`docs/2026-05-27-今日部署清单.md`

## 扩展和下一步

见 `ROADMAP.md`：
- **第一阶段**（已完成）：核心游戏 + 云同步
- **第二阶段**：A/B 类剩余互动独立页面
- **第三阶段**：C 类辅助工具、家庭成员档案

新增游戏建议参考「添加新游戏」章节。
