# 谁是卧底同场 v2：集合与 `watch`

与旧版 4 位 `rooms` 房间不共用数据；6 位房、独立云函数 `undercoverRoomService`。

| 与需求对应 | 本实现集合 | 说明 |
|------------|------------|------|
| `rooms` | `uc_rooms` | 房间主文档：6 位 `roomCode`、阶段、局内发言顺序、公屏日志、胜负等 |
| `players` | `uc_players` | 每人一条：`openId`、`word`、`role`、`isAlive`、本局 `currentVote` 等 |
| `gameState`（公屏+监听） | `uc_state` | `_id` 与 `uc_rooms` 的 `_id` 相同，云函数在每次更新后 `set` 到此处供 `watch` |

## 权限建议

- `uc_rooms` / `uc_players`：**写** 仅云函数，客户端不直连改词与身份；**读** 可限制为仅本人生效字段走 `getView` 云函数，公开阶段信息走 `uc_state`。
- `uc_state`：全场可读用于同步，写仍仅云函数。

## 云函数

- 名称：`undercoverRoomService`（目录 `cloudfunctions/undercoverRoomService/`），部署前需 `npm i` 依赖 `wx-server-sdk`。
- 本机词与身份只通过 `action: 'getView'` 返回，勿把 `word` 写进可全员读的 `uc_state` 文档中。

## 客户端 `watch`

```js
wx.cloud.database()
  .collection('uc_state')
  .doc(String(roomId))
  .watch({ onChange (s) { const d = s.data != null ? s.data : s.doc /* ... */ } })
```

## 6 位与身份推理

首页「输入口令」对 6 位数字 **先试** 卧底 v2 进组，**失败且提示无组** 再试身份推理，避免同码冲突。
