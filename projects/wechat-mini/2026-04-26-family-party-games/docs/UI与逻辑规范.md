# 家庭聚会助手 — UI 与逻辑规范

> 本文档约定小程序前端的**界面结构、样式体系、状态驱动、生命周期与复用模块**。  
> 玩法与云函数细节见 [`游戏玩法与逻辑说明.md`](./游戏玩法与逻辑说明.md)；分享解锁见 [`分享解锁AI功能流程.md`](./分享解锁AI功能流程.md)。

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **聚会场景优先** | 大按钮、高对比、少步骤；关键状态用横幅 `statusHint` 一句话说明 |
| **组长权限可见** | 「开始本轮」「结束投票」等仅 `isHost` / `tdIsHost` 时渲染，避免全员误点 |
| **文案统一** | 对用户说「聚会组 / 互动组 / 口令」，不说「房间 room」；6 位是**房号**不是人数 |
| **云页与本地页分离** | 6 位云同场走独立 `*Room` 页 + `room-game.wxss`；本地辅助走 `play` + `app.wxss` |
| **合规** | 界面不宣传饮酒强迫、赌博；AI 按钮未解锁用 🔒 + `ai-locked`，不隐藏入口 |

---

## 2. 设计令牌（Design Tokens）

**源码**：`styles/tokens.wxss`（由 `app.wxss` 首行 `@import` 注入到 `page`）。  
**原则**：新样式优先写 `var(--*)`，避免魔法数字；字重只用 **400 / 500 / 600**，不用 `bold`/`900`（iOS 过粗）。

### 2.1 字体规范

行高约为字号的 **1.43～1.5** 倍；**正文最小 24rpx**（微信推荐）；`22rpx` 仅保留在令牌中供版权/调试，业务 UI 勿用。

| 元素 | 字号 (rpx) | 行高 (rpx) | 字重 | 工具类 / 场景 |
|------|------------|------------|------|----------------|
| 超大标题 | 48 | 64 | 600 | `.text-display`、`.hero-title`、结果页胜利提示 |
| 页面主标题 | 40 | 56 | 500 | `.text-title`、`.section-title`、玩法页头部 |
| 卡片标题 | 32 | 44 | 500 | `.text-card-title`、游戏卡片名、成员列表主行 |
| 正文 | 28 | 40 | 400 | `.text-body`、按钮、描述、状态横幅 |
| 辅助文字 | 24 | 34 | 400 | `.text-caption`、时间、人数、解锁提示 |
| 极小文字 | 22 | 30 | 400 | `.text-tiny`（慎用，非业务主文案） |

### 2.2 间距系统（8rpx 阶梯）

| 令牌 | 值 (rpx) | 使用场景 |
|------|----------|----------|
| `--space-xs` | 8 | 图标与文字、行内 gap |
| `--space-sm` | 16 | 列表项内边距、按钮组间距 |
| `--space-md` | 24 | 卡片内边距、区块垂直间距 |
| `--space-lg` | 32 | 页面左右安全边距、大按钮水平 padding |
| `--space-xl` | 48 | hero 与列表、大区块之间 |
| `--space-2xl` | 64 | 页顶/底留白 |

示例：

```css
.page {
  padding: var(--page-pad-top) var(--page-pad-x) var(--page-pad-bottom);
}
.rg-members-card {
  padding: var(--space-md);
  margin-top: var(--space-md);
}
```

### 2.3 圆角与按钮

**圆角**

| 令牌 | 值 | 对象 |
|------|-----|------|
| `--radius-sm` | 8rpx | 小标签、难度 chip |
| `--radius-md` | 16rpx | 卡片、成员项、次按钮 |
| `--radius-lg` | 24rpx | **主按钮**（与微信主按钮一致） |
| `--radius-xl` | 32rpx | 分享小按钮、弹窗 |
| `--radius-full` | 9999rpx | 头像、胶囊 `.pill` |

**按钮尺寸**

| 类型 | 高度 | 圆角 | 字号 | 类名 |
|------|------|------|------|------|
| 主操作（全宽） | 96rpx | 24rpx | 32rpx | `.btn.main-btn`、`.rg-btn-primary` |
| 次操作 | 72rpx | 16rpx | 28rpx | `.btn-md`、`.rg-btn-ghost` |
| 小按钮（分享等） | 64rpx | 32rpx | 26rpx | `.btn-sm`、`.btn-wechat-invite` |

最小可点击区域：**64×64 rpx**（`--btn-tap-min`）。

**状态**（已在 `app.wxss` / `room-game.wxss` 实现）：

```css
.btn-primary:active { opacity: 0.8; transform: scale(0.98); }
.btn-primary[disabled] { opacity: 0.5; pointer-events: none; }
```

主按钮白字可加 `text-shadow: 0 1rpx 2rpx rgba(0,0,0,0.12)` 提升橙底对比度。

### 2.4 颜色

| 类型 | 变量 | 色值 | 场景 |
|------|------|------|------|
| 品牌 | `--color-brand` | `#FF7A2F` | 主按钮、强调 |
| 品牌深 | `--color-brand-deep` | `#ea580c` | 同场主按钮、进度条 |
| 成功 | `--color-success` | `#07c160` | 就绪、解锁、微信邀请 |
| 警告 | `--color-warning` | `#ff9f00` | 人数不足、预览虚线框 |
| 错误 | `--color-error` | `#fa5151` | 出局、失败 |
| 信息 | `--color-info` | `#1485ee` | 普通提示、链接 |
| 页面背景 | `--color-bg-page` | `#FEF8F0` | `page`、导航栏 |
| 卡片背景 | `--color-bg-card` | `#FFFFFF` | `.card`、成员项 |
| 分割线 | `--color-border` | `#f0f0f0` | 列表分隔 |
| 遮罩 | `--color-mask` | `rgba(0,0,0,0.5)` | 弹窗底层 |

**对比度（米白底）**：正文 `#23212a` ≈ 12:1；辅助 `#7b7280` ≈ 5:1（WCAG AA）；主按钮白字 ≈ 4.5:1（达标，辅以阴影）。

语义文字类：`.text-success` / `.text-warning` / `.text-error` / `.text-info`。

### 2.5 布局与边距

| 组件 | 外边距 | 内边距 |
|------|--------|--------|
| `.page` | — | 上 28 / 左右 32 / 下 48 + safe-area |
| `.card` | `margin-bottom: 24rpx` | 各页 `setup-card` 等自行 `padding: var(--space-md)` |
| `.rg-members-card` | `margin-top: 24rpx` | `24rpx` |
| `.rg-member-item` | 列表 `gap: 16rpx` | `16rpx 24rpx` |

`.page` 设 `max-width: 540px` 居中，适配大屏手机；横屏聚会场景少，不单独布局。

### 2.6 暗色模式

`tokens.wxss` 内 `@media (prefers-color-scheme: dark)` 覆盖背景、卡片、文字、品牌色。  
`app.json` 的 `window.backgroundColor` 仍为浅色；深色下以 `page` 背景为准。真机可在系统设置切换验证。

### 2.7 响应式与例外

- **刘海 / 底部条**：`.page` 使用 `env(safe-area-inset-*)`。
- **rpx 为主**：布局、字号、间距一律 rpx。
- **px 例外**：canvas 导出分享图、部分第三方组件文档要求 px 时单独注明，勿混进令牌表。

---

## 3. 视觉与样式分层

### 3.1 全局（`app.wxss` + `tokens.wxss`）

**布局与组件类**

- `.page`：安全边距 + 最大宽度 540px
- `.hero` / `.hero-title` / `.hero-subtitle`：首页、play 顶区
- `.card`：白底、`--radius-md`、轻阴影（内边距由子类/页面补充）
- `.btn` + `.main-btn`：flex 垂直居中，禁止仅靠 line-height
- `.btn-primary` / `.btn-secondary`：品牌橙 / 浅橙底
- `.btn-ai`：紫色渐变，仅 AI
- `.section-title`、`.pill`、字号工具类见 §2.1

### 3.2 同场聚会组（`styles/room-game.wxss`）

云游戏页（卧底、画猜、猜歌、抽签、身份推理、play 内真心话房）在 **页面 wxss** 顶部：

```css
@import "../../styles/room-game.wxss";
```

**禁止**：在 **自定义组件** 的 wxss 里 `@import room-game.wxss`（含标签选择器，会触发组件样式告警）。组件内需要的样式在组件 wxss 里**复制最小子集**或只用 class 名由页面传入。

**`rg-*` 语义（room-game）**

| 类名 | 用途 |
|------|------|
| `.rg-status-banner` | 顶部状态提示（等待、进行中、错误说明） |
| `.rg-members-card` / `.rg-member-list` | 成员列表容器 |
| `.rg-progress-bar` / `.rg-progress-fill` | 人数进度（当前/目标） |
| `.rg-avatar` / `.rg-member-name` | 旧版首字头像（逐步改用 `member-avatar`） |
| `member-avatar` | 成员列表：云存储头像或首字 fallback；无昵称显示「匿名」 |
| `user-info-modal` | 600rpx 卡片弹窗；**仅**首页点击游戏「开始互动」且资料未齐时弹出；`稍后再说` 关闭且不跳转 |
| `.rg-ready-dot.on` | 就绪绿点 |
| `.rg-settings-card` / `.rg-room-card` | 组长设置卡、大厅白卡片 |
| `.rg-setting-item` + `.rg-stepper-board` | 加减设置行：左标签、右 `-` 数字 `+`（64rpx 圆钮） |
| `.rg-stepper-hint` | 步进器下方辅助说明（24rpx 灰字） |
| `.rg-section` / `.rg-stepper` / `.rg-seg` | 设置区、步进器、分段切换 |
| `.rg-btn-primary` | 全宽主操作（开始本轮等） |
| `.btn-wechat-invite` | 微信绿 `#07c160`，`open-type="share"` |
| `.rg-btn-ghost` | 次要描边按钮 |
| `.ai-locked` | 未解锁 AI：降低透明度，仍可点以弹出分享引导 |
| `.ai-unlock-tip` | 解锁进度说明条 |

各游戏页可再加前缀类（如 `uc-`、`td-`），但**成员区、主按钮、分享按钮**优先复用 `rg-*`。

### 3.3 按钮层级（同一屏内最多一层主操作）

```
1. .rg-btn-primary / .btn.btn-primary.main-btn     → 推进局面的唯一主操作
2. .btn-wechat-invite + open-type="share"          → 邀请进组
3. .btn-secondary / .rg-btn-ghost                   → 设置、次要
4. .btn-ai + ensureAiUnlock                        → AI（可能弹分享解锁）
```

同一区块不要并排两个 `.rg-btn-primary`；次要操作用 `margin-top: var(--space-sm)` 拉开间距。

---

## 4. 页面类型与 UI 结构

### 4.1 首页 `pages/index`

- **结构**：`hero`（标题 + 输入口令 + AI 聚会建议）+ `scroll-view` 游戏卡片网格
- **数据**：`games` 来自 `data/game-data.js`（`displayTitle` / `displaySummary` / `screen`）
- **AI**：`aiUnlock.canRecap` 控制「AI 聚会建议」是否可点；未解锁显示 🔒
- **组件**：按需注册 `ai-share-modal`（见 §7）

### 4.2 建房 `pages/setup`

- 创建 6 位云房或 4 位老聚会组，成功后 `redirectTo` 对应玩法页
- 不在此页做长时间 watch

### 4.3 云同场页（6 位口令）

`werewolf` / `undercover` / `draw-guess` / `song-guess` / `drink-party`

典型区块顺序（WXML）：

1. 状态横幅 `statusHint`（有则显示）
2. 成员卡 `rg-members-card` + `memberCountLine`
3. 房主设置区 `rg-settings-card`（平铺：人数、词库、AI 出题等，`wx:if="{{isHost}}"`）
4. 主按钮「开始互动」/ 阶段内操作区
6. `btn-wechat-invite` 分享
7. 页底 `ai-share-modal`

**状态来源**：`getView` 云函数或 `db.watch` / 轮询刷新 → `setData` 驱动 `wx:if` 切换阶段 UI。

### 4.4 通用玩法 `pages/play`

- **mode** 决定 UI：`truthDareRoom`（4 位云投票）vs 本地 `timer` / `score` / `random` 等
- 本地模式：`hero` + 单卡内容 + 计分/倒计时；AI 用 `runAi` + `ensureAiUnlock`
- 真心话同场：复用 `rg-*` 成员区 + `tdPhase`（`none` / `voting` / `resolved`）

---

## 5. 逻辑与 UI 绑定规范

### 5.1 页面 `data` 命名

| 字段 | 含义 |
|------|------|
| `roomId` / `roomCode` | 云文档 id、6/4 位口令 |
| `isHost` / `tdIsHost` | 是否组长（控制主按钮显示） |
| `statusHint` | 给人看的状态一句 |
| `memberCountLine` | 由 `roomUi.memberCountLine()` 生成，勿手写拼接 |
| `displayPlayers` | 列表展示用（含 `avatarText`、`readyLabel`） |
| `aiUnlock` | `refreshAiUnlockPage` 写入：`canGen` / `canAssist` / `canRecap` / `nextHint` |
| `showAiShareModal` | 分享解锁弹窗 |
| `shareCopy` | 分享文案变体 |

阶段字段各玩法自定（如 `tdPhase`、`phase`），但 **WXML 只用 `data` 与简单表达式**，复杂判断在 JS 里算好再 `setData`。

### 5.2 WXML 约束

- 绑定到属性的字符串用 `{{x || ''}}`，避免 `null` 传入组件 properties（如 `next-hint`）
- `wx:if` 按 **阶段 → 角色 → 权限** 嵌套，先大块阶段再细权限
- `wx:for` 必须 `wx:key`（优先 `openId`）
- 分享按钮：`<button open-type="share" class="btn-wechat-invite">`，文案用「邀请朋友」类口语

### 5.3 JSON 配置

- `app.json`：`"lazyCodeLoading": "requiredComponents"` — **组件只在用到的页面 json 里声明**，不要全局 `usingComponents` 堆满
- 页面 json：**禁止尾逗号**；不要写无效字段（如已废弃的页面级 `enableShareTimeline`）
- 需要分享解锁的页面在 `usingComponents` 注册 `ai-share-modal`

---

## 6. 生命周期与实时刷新

### 6.1 标准钩子顺序

```text
onLoad(query)
  ├─ tryRedeemShareFromQuery(query)     // 好友点开 st= 链接核销
  ├─ 解析 roomId / roomCode / config
  └─ 进房成功后 → onRoomEntered(page, roomId, kind)

onShow
  ├─ onPageShowUnlock(page)             // 解锁 feed / 轮询
  └─ refreshAiUnlockPage(page)
  └─ 恢复 watch / getView

onHide
  ├─ onPageHideUnlock(page)
  └─ 停止 watch / 定时器

onUnload
  ├─ onRoomLeft(page)                   // 结束 AI session、清本地解锁计数
  └─ 释放 watch
```

`kind` 与 `shareHelper.PRESETS` 键一致：`undercover` / `werewolf` / `draw` / `music` / `drink` / `truthDare` / `index`。

### 6.2 云状态同步

| 环境 | 策略 |
|------|------|
| 真机 | 优先 `db.watch`（`utils/cloudRealtime.watchDocument`） |
| 开发者工具 | 默认**不** watch，用 `getView` 轮询（见 `cloud-env.js` 开关） |
| 解锁进度 | `shareUnlockFeed` watch + 60s 轮询兜底 |

页面内保存 watcher 引用（如 `this._wg`），`onHide`/`onUnload` 必须关闭，避免泄漏与 timeout 刷屏。

### 6.3 开始前校验（云房统一）

```javascript
const checks = buildStartChecks({ /* playerCount, phase, isHost, … */ })
runStartAction({
  page: this,
  checks,
  cloudCall: () => xxxRoomService.startRound(...),
  kind: 'drink' // 用于失败文案映射
})
```

失败弹窗用 `roomUi.showRoomBlockModal`，文案按 `kind` 在 `explain*StartFail` 中映射，**不要在页面里散落 Toast 解释同一错误**。

---

## 7. 组件规范

### 7.1 `ai-share-modal`

- **属性**：`visible`、`nextHint`（字符串）、`shareCopy`（对象）
- **事件**：`bind:close`、`bind:timeline`（朋友圈引导）
- **页面职责**：`openAiShareModal` / `closeAiShareModal`；`onShareAppMessage` 里带 `st` token（`getShareTokenForShare`）
- 父页面需提供 `onShareAppMessage` / `onShareTimeline`（`shareHelper.enableShareMenus`）

### 7.2 `party-cd` / `party-vote-sel`

- 纯展示/交互组件，`component: true`，样式自包含
- 由父页面传入秒数、选项，不在组件内调云函数

### 7.3 新增组件 checklist

1. 样式不 import `room-game.wxss`
2. properties 给默认值，WXML 侧防 null
3. 事件用 `triggerEvent('name')`，命名动词过去式：`close`、`submit`
4. 在**使用该组件的页面** json 注册，不写入 `app.json` 全局

---

## 8. AI 相关 UI

### 8.1 解锁梯度（`utils/aiUnlock.js`）

| 好友点开分享 | 解锁能力 |
|-------------|----------|
| 1 人 | `canGen` — AI 出题/词对 |
| 2 人 | `canAssist` — 策略建议 |
| 3 人 | `canRecap` — 战报、首页聚会建议 |

交互：

- 点击 AI 按钮 → `ensureAiUnlock(LEVEL.xxx, '功能名', page)` → 未达标则 `openAiShareModal`
- 按钮 class：`{{aiUnlock.canGen ? '' : 'ai-locked'}}`，可保留 🔒 文案
- 进房 `onRoomEntered` 会 `prepareShareToken`；离房 `onRoomLeft` 重置本场 session 计数

### 8.2 生成中 UI（`utils/aiHelper.runAi`）

- 自动 `wx.showLoading`；超过 3s 改文案「生成时间较长…」
- 同页 800ms 防抖 + `aiBusy`；勿再套一层无意义 loading
- 结果：`showAiModal` 或写入 `aiPreviewPair` 等预览区
- 海报：`runAiPoster`，20s 慢提示，独立 loading 文案

---

## 9. 分享与邀请 UI

| 能力 | 实现 |
|------|------|
| 邀请进组 | 绿色 `btn-wechat-invite` + `open-type="share"` |
| 复制口令 | 点击橙色口令数字（`rg-code-tap`），Toast「口令已复制」；不设单独「复制」链接 |
| 分享标题 | `shareHelper` + `warmShareCard` 预热；有房号用 `roomTitle(code)` |
| 解锁分享 | 必须带 query `st=`；仅菜单分享不计入 |
| 朋友圈 | `onShareTimeline` + 弹窗内 `bind:timeline` 引导 |

各页 `_shareCtx()` 返回 `{ roomId, roomCode }` 供 `onShareAppMessage` 拼 query。

---

## 10. 反馈与异常

| 场景 | UI 方式 |
|------|---------|
| 轻提示 | `wx.showToast`（icon: none / success） |
| 需用户确认 | `wx.showModal`；阻塞型错误 `showCancel: false` |
| 开始失败 | `showRoomBlockModal(title, content)` |
| AI 失败 | `formatAiErr` + modal，或 `showAiModal` |
| 网络/云超时 | 文案避免裸 `Error: timeout`；devtools 已知 watch 超时可忽略 |

---

## 11. 新增云玩法 UI Checklist

1. 新建页面 wxss `@import room-game.wxss`
2. 成员区、主按钮、分享按钮复用 `rg-*` / `btn-wechat-invite`
3. `onLoad` 调 `tryRedeemShareFromQuery`；进房 `onRoomEntered(..., kind)`，离房 `onRoomLeft`
4. 开始流程走 `buildStartChecks` + `runStartAction`
5. `shareHelper.PRESETS` 增加 `kind`，实现 `buildQuery`
6. 页面 json 注册 `ai-share-modal`；`data` 含 `aiUnlock`、`showAiShareModal`
7. `onShareAppMessage` 合并 `st` token
8. 真机验证阶段切换与组长权限隐藏

---

## 12. 相关文件索引

| 模块 | 路径 |
|------|------|
| 设计令牌 | `styles/tokens.wxss` |
| 全局样式 | `app.wxss` |
| 同场 UI | `styles/room-game.wxss` |
| 成员/开始 | `utils/roomUi.js` |
| 分享 | `utils/shareHelper.js` |
| 进房 AI/分享 | `utils/partyAiRoomHooks.js` |
| 解锁 | `utils/aiUnlock.js`、`components/ai-share-modal/` |
| AI 调用 | `utils/aiHelper.js` |
| 实时 | `utils/cloudRealtime.js` |
| 游戏元数据 | `data/game-data.js` |

---

## 13. 文档关系

```text
UI与逻辑规范.md（本文）  →  令牌、怎么画、怎么绑、生命周期
游戏玩法与逻辑说明.md    →  状态机、云函数 action、各游戏规则
分享解锁AI功能流程.md      →  st 核销、云库、部署测试
```

维护建议：改数值先改 `tokens.wxss` 与 §2，再改 `app.wxss` / `room-game.wxss`；新增页面类型时更新 §4 与 §11。

---

## 附录：快速参考表

| 类别 | 属性 | 值 |
|------|------|-----|
| 主色 | 品牌色 | `#FF7A2F`（`--color-brand`） |
| 主色 | 同场深橙 | `#ea580c`（`--color-brand-deep`） |
| 功能 | 成功 / 微信 | `#07c160` |
| 功能 | 警告 | `#ff9f00` |
| 功能 | 错误 | `#fa5151` |
| 背景 | 页面 | `#FEF8F0` |
| 背景 | 卡片 | `#FFFFFF` |
| 圆角 | 按钮 | `24rpx`（`--radius-lg`） |
| 圆角 | 卡片 | `16rpx`（`--radius-md`） |
| 间距 | 页面左右 | `32rpx`（`--page-pad-x`） |
| 间距 | 卡片间距 | `24rpx`（`--space-md`） |
| 字号 | 正文 | `28rpx` / 行高 `40rpx` |
| 字号 | 辅助 | `24rpx` / 行高 `34rpx` |
| 字号 | 超大标题 | `48rpx` / 行高 `64rpx` |
| 按钮 | 主操作高度 | `96rpx` |
| 按钮 | 最小点击 | `64rpx` |
| 字重 | 常规 / 强调 | `400` / `500` / `600` |
