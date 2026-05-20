# shareService 上线部署清单

环境须为 `cloud1-d9g01no7m292bc511`（与 `cloud-env.js` 一致）。

## 一、云开发控制台

### 1. 新建集合

| 集合名 | 说明 |
|--------|------|
| `share_tokens` | 每次分享一条令牌 |
| `share_unlock_users` | 按 `openId + sessionId` 累计本场解锁 |
| `agent_room_feed` | 解锁进度实时推送（与 hostAgent 共用，**客户端需读**） |
| `analytics_share_unlock` | 可选，分享转化埋点 |

**权限（推荐）**

- `share_tokens` / `share_unlock_users`：仅云函数读写。
- `agent_room_feed`：`read: true`, `write: false`（见 `docs/Agent聚会助手.md`）。

### 2. 索引

**share_tokens**：`token` 唯一升序  

**share_unlock_users**：`openId` + `sessionId` 联合升序  

**agent_room_feed**：`roomId` + `type` 联合升序  

### 3. 部署云函数

```bash
cd cloudfunctions/shareService
npm install --registry=https://registry.npmjs.org
```

微信开发者工具 → 右键 **shareService** → **上传并部署：所有文件**。  
**关闭** shareService「本地调试」。

前端封装：`utils/shareService.js`。

---

## 二、业务规则

| 规则 | 说明 |
|------|------|
| 场次重置 | 每次进房新 `sessionId`，离房本地进度清零 |
| 首页 | 未进房用 `day_YYYY-MM-DD` |
| 好友确认 | 仅好友点开带 `st` 的链接计次 |
| 实时通知 | `agent_room_feed` watch，失败时 60s 轮询 |
| token 上限 | 每场最多 10 个未使用码，满额自动作废最旧码 |

可选：为 `shareService` 配置定时预热 `{"action":"warm"}`。

---

## 三、上线前自检

1. `cloud-env.js` 中 `debugCloudLog: false`（已默认关闭详细云日志）  
2. 真机：进房 → 点 🔒 AI → 分享 → 好友点开链接 → 分享者解锁  
3. 云函数日志可见 `redeemToken` / `token_redeemed`  

---

## 四、常见报错

| 现象 | 处理 |
|------|------|
| `collection not exists` | 未建 `share_tokens` / `share_unlock_users` |
| `redeemToken` 无反应 | 云函数未部署；须另一微信号真机点开 |
| A 不涨进度 | A 勿离房；查云函数日志；等 60s 轮询 |
| `-404012` timeout | 关本地调试；确认 envId；`timeout: 15000` |
| 开发者工具 `Error: timeout` | 多为工具内部/WebSocket，真机一般无；与分享解锁无关时可忽略 |

云函数日志：云开发 → shareService → 日志。
