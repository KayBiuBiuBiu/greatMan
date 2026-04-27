# 秘密身份推理（聚会版）：云开发数据与 `watch`

## 集合

| 集合 | 作用 |
|------|------|
| `werewolf_rooms` | 全量环节态：成员、 `playerRoles`、`game`（仅云函数/主持视角写）。勿在前端 `open` 给非管理员写死所有人身份。 |
| `werewolf_state` | **可订阅摘要**：`doc` 的 `_id` 与 `werewolf_rooms` 的文档 `_id` 相同。云函数在每次写库后 `set` 到本集合，供全端 `watch` 做阶段/存活/公屏广播同步。 |

## 权限（建议）

- 小程序端对 `werewolf_state`：**读** 允许（同房间玩家需同步阶段）；`write` 建议仅云函数/控制台（微信控制台「数据库权限」中关闭客户端随意写，或只开放云函数走服务端权限）。
- `werewolf_rooms`：建议仅云函数可写，客户端不直连改身份；身份与夜间操作经云函数 `werewolfService` 校验（本机只通过 `getView` 看自己的身份/验人结果等）。

## 云函数

- 名：`werewolfService`（`cloudfunctions/werewolfService/`，需上传并部署依赖）。
- 与 `setPub`：每次对 `werewolf_rooms` 更新后，同步同 `_id` 的 `werewolf_state` 一条文档，便于 `watch` 不轮询。

## 前端 `watch` 用法

在房间页建立：

```js
const db = wx.cloud.database()
db.collection('werewolf_state')
  .doc(String(roomId))
  .watch({
    onChange: (s) => {
      const d = s && (s.data != null ? s.data : s.doc)
      if (d) { /* 刷新 UI 公共区 */ }
    },
    onError: (e) => { /* 重连/提示 */ }
  })
```

私密信息（本机身份、线索/同组暗位等）仍通过 `getView` 云函数拉取，不要写进可全员读的 `werewolf_state` 文档中。

## 6 位房号

- 与旧版 4 位 `roomService` 口令**分离**；身份推理使用 6 位 `roomCode` 与上表集合，避免和 `rooms` 表逻辑混用。
