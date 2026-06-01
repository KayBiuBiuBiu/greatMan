# 秘密身份推理 — AI 主持人

## 部署

1. 微信开发者工具 → 云开发 → 上传并部署 **`werewolfAIService`**（与 `werewolfService` 同环境）。
2. 确认 `data/feature-flags.js` 中 `WEREWOLF_AI_MODE_ENABLED = true`。
3. 大厅由组长打开 **AI 全自动主持** 开关，人齐且全员准备后点 **开始 AI 主持**。

## 数据（`werewolf_state` 公屏文档）

在原有字段上，AI 局会多出（由 `werewolfAIService` 写入）：

| 字段 | 说明 |
|------|------|
| `aiMode` | 是否 AI 主持 |
| `currentPhaseStartTime` | 阶段开始时间戳 |
| `phaseDuration` | 阶段时长（秒） |
| `remainingSeconds` | 剩余秒数（计算字段） |
| `nightSteps` / `nightStepIndex` / `currentNightStep` | 夜间身份组顺序 |
| `witchPhaseStep` | 女巫 1=救 2=毒 |
| `wolfVotes` / `wolfVoteCount` / `wolfTotal` | 狼人票 |
| `speakOrder` / `currentSpeakerIndex` / `currentSpeakerOpenId` | 发言 |
| `voteResults` | 投票 |
| `lastNightDeaths` | 昨夜出局 openId 列表 |
| `needTransfer` | 是否处于警长移交警徽阶段 |
| `transferRemainingSeconds` | 移交倒计时剩余秒数 |
| `sheriffTransferFrom` | 待移交警徽的出局警长 openId |
| `sheriffPhase` | 警长竞选子阶段：`signup` / `withdraw` / `speak` / `vote` / `done` |
| `withdrawRemainingSeconds` | 退水窗口剩余秒数 |

权威状态在 `werewolf_rooms.game.ai` 子对象；`werewolf_state` 为公屏同步。

## 云函数 API

| action | 说明 |
|--------|------|
| `startAIMode` | 组长开局：发牌 + 进入第 1 夜 |
| `getCurrentState` | 轮询；超时自动推进 |
| `reportAction` | 玩家操作（kill/check/save/poison/vote/finishSpeak/shoot 等） |
| `transferSheriff` | 出局警长将警徽移交给存活玩家（`targetOpenId`） |
| `skipTransfer` | 出局警长放弃移交，警徽流失 |
| `withdraw` | 上警玩家在退水窗口内放弃竞选 |
| `advancePhase` | 前端倒计时兜底强制推进 |

## 胜负

**屠边**：狼人数量为 0 → 村民侧胜；神职全灭或村民全灭 → 暗位侧胜。

## 板子（含组长，每人一张牌）

| 人数 | 配置 |
|------|------|
| 6 | 狼、白狼王、预、巫、守、民×1 |
| 8 | 狼、白狼王、预、巫、守、猎、民×2 |
| 10 | 狼×2、白狼王、预、巫、守、猎、民×3 |
| 12 | 狼×3、白狼王、预、巫、守、猎、民×4 |

## 守卫 / 白狼王（state 扩展）

| 字段 | 说明 |
|------|------|
| `game.ai.lastGuardTarget` | 上一夜守护对象（不可连守） |
| `game.ai.nightGuardTarget` | 当夜守护对象 |
| `game.night.guardTarget` | 手动模式当夜守护 |
| `game.ai.whiteWolfBoomStep` | `pick` 表示白狼王选人带走 |
| `game.ai.whiteWolfBoomOpenId` | 自爆中的白狼王 openId |

**同守同救则死**：当夜被刀目标同时被守卫守护且女巫救，仍出局。

## 警长竞选（仅第 1 天白天）

流程（AI 自动）：

1. `day_announce` 天亮公布死讯  
2. `sheriff_signup`（25s）全员选择上警 / 不上警  
3. `sheriff_withdraw`（10s，仅当上警≥2 人）上警玩家可退水；0 人→无警长，1 人→直接当选，≥2 人→警上发言  
4. `sheriff_speak`（60s/人）上警玩家警上发言  
5. `sheriff_vote`（45s）全员投票选警长  
6. `speak` 警下发言 → `vote` 放逐投票  

规则要点：

- 仅 **第 1 天** 进行一次警长竞选（`sheriffElectionDone`）  
- 无人上警或平票则无警长  
- 仅 1 人上警则直接当选（跳过退水窗口）  
- **退水**：上警≥2 人时，报名结束后 10 秒退水窗口；退水后不可再上警；公屏「X 退水」  
- 警长获得 🎖 标识；**放逐投票时警长票计 2 票**  
- **警长移交警徽**（`phase = sheriff_transfer`，15 秒）  
  - 警长因夜间出局、放逐、白狼王带走、协定者开枪等出局时触发（先于协定者开枪环节或天亮播报继续主流程）  
  - 出局警长本机弹窗：点选存活玩家 → 确认移交；可点「不移交」或超时 → 警徽流失  
  - 移交成功：公屏「警长将警徽移交给了 X」；新警长 🎖，放逐票仍计 2 票  
  - 未移交：公屏「警长未能移交警徽，警徽流失」；`sheriffOpenId` 清空  

手动模式：同上移交弹窗（`transferSheriff` / `skipTransfer`）；退水用 `withdraw`，主持可 `hostEndSheriffWithdraw` 提前结束退水。主持在「天亮了」后点 **进警长环节**，依次 **结束报名·开退水** →（退水结束）**下一位警上/开警投** → **公布警长** → 警下发言/放逐流程。

## 与手动主持

- `aiModeOn === false`：仍使用原 `werewolfService` + 组长按钮。
- `aiModeOn === true`：隐藏组长推进区，显示 AI 倒计时与身份操作面板。

## 索引建议

- `werewolf_rooms`：`roomCode` + `status`
- `werewolf_state`：文档 `_id` 与 `roomId` 一致，无需额外索引
