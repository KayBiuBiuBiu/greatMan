# 开发者工具里「Error: timeout」说明

## 常见原因（本项目）

| 来源 | 说明 |
|------|------|
| 首页 `onShow` | 同时调 `gameStatsService`、`shareService`、可能 `db.watch` |
| 云函数冷启动 | 标准版刚部署后首次调用较慢 |
| 工具限制 | 模拟器里 `db.watch` / 长轮询易报无前缀 `timeout`（与业务代码无关） |

## 代码里已做的优化

- `app.js`：`wx.cloud.init({ env: cloud-env.envId })`
- `gameStatsCloud` / `shareService`：客户端 `timeout: 15000`（15 秒）
- `cloudbaserc.json`：云函数服务端超时 30～60 秒
- 首页：云调用 **延后 400ms**，离开页面会取消
- 开发者工具默认 **跳过** `gameStatsService`、`shareService`（`cloud-env.js` 中 `allowGameStatsInDevtools` / `allowShareCloudInDevtools` 为 `false`）

真机预览/体验版仍会正常拉热门排序与分享解锁。

## 若真机仍超时

1. 云开发控制台 → 云函数 → 对应函数 → **超时时间** 设为 **≥10 秒**（建议 30 秒，与 `cloudbaserc.json` 一致）
2. 确认环境 ID = `cloud1-d9g01no7m292bc511-d5e875d`
3. 控制台对 `gameStatsService` / `shareService` 各执行一次测试调用（预热冷启动）

## 不建议的做法

- 不要用 `Promise.race` + 假超时包一层 `callFunction`（微信已支持 `timeout` 参数）
- 不要在 `onLoad` 里 `wx.showLoading` 挡整页（首页已改为静默失败 + 本地排序）

若要**在开发者工具里也测分享解锁云逻辑**，可在 `cloud-env.js` 临时设：

```javascript
allowGameStatsInDevtools: true,
allowShareCloudInDevtools: true,
```

测完改回 `false`。
