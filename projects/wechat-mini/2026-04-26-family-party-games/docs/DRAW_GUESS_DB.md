# 你画我猜 · 云开发数据

## 集合

| 集合 | 作用 |
|------|------|
| `draw_rooms` | 房间：口令、状态、每轮题 `currentWordId`、已用词 `usedWordIds`、词类、总轮数等（仅云函数/管理员应写，客户端不依赖读此集合判题） |
| `draw_players` | 玩家：openId、昵称、分数 |
| `draw_gameState` | 公屏：轮次、阶段、绘画者、倒计时起点、公屏分、已揭晓词、roundHits 等，供全端 `watch` |
| `draw_canvas` | 文档 `_id` = `roomId`；`strokes` 笔画数组（主同步）；`canvasSeq` 与 `draw_gameState.canvasSeq` 对齐；`image` 为可选整图兜底 |

## `draw_rooms` 主要字段

- `roomCode`：6 位
- `hostOpenId`：房主
- `status`：`waiting` / `playing` / `finished`
- `totalRounds`：总轮次（5/6/8/9/10/12 等，云函数内校验）
- `roundDuration`：默认 60 秒
- `wordCategory`：`all` 或 `动物`/`食物`/`日常`/`职业`/`其他`（与 `words.js` 中 `c` 一致）
- `usedWordIds`：本局已用题目 id
- `currentWordId`：当轮题 id（不要在前端公屏上暴露「词面」；判题在云端）
- `currentWordText`：当轮词面汉字（AI/自定义题必填；系统词库可冗余存储，供 `submitGuess` 判题）

## `draw_gameState` 主要字段

- `phase`：`waiting` / `drawing` / `revealed` / `finished`
- `currentRound`、`roundStartTime`、`roundHits`、`revealedWord`（揭晓后公屏显示）、`publicPlayers`（排行）、`canvasSeq`（清画布版本）、`publicLog` 等
- `canvasData`：笔画 JSON 字符串（`[{c,w,pts}]`）；观看端 `JSON.parse` 后全量重绘；`appendStroke` 增量合并；`canvasDataVer` 变更版本号

## `getView` 私有信息

- 词语**仅**在 `getView` 返回 `painterWord`（非画家不返回该字段）；`draw_gameState` 公屏**不含**词面。
- 客户端以 `state.currentDrawerOpenId === myOpenId` 判定画家，与 `getView.isDrawer` 双校验。

## 云函数

`drawRoomService`：create, join, setConfig, startGame, reveal, nextRound, skipWord, submitGuess, appendStroke, updateCanvas, endGame, getView

## 权限建议

- `draw_rooms`、`draw_players`、`draw_canvas`：仅云函数可写；`draw_gameState`、`draw_canvas` 可配置为登录用户只读、云写。
- `canvasData` 公屏存 JSON 字符串；客户端用 `parseCanvasData` 解析。笔画格式 `{ c, w, pts: [[x,y],...] }`。注意单文档体积与条数上限（约 200 条/800 点）。
