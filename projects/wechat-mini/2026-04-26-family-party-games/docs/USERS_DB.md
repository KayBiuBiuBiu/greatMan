# users 集合与权限

环境：`cloud1-d9g01no7m292bc511-d5e875d`（见 `cloud-env.js`）

## 集合 `users`

| 字段 | 类型 | 说明 |
|------|------|------|
| `_id` | string | 与 `openId` 相同（云函数写入） |
| `openId` | string | 微信用户 openId |
| `nickName` | string | 昵称，最长 32 字 |
| `avatarUrl` | string | 云存储 `fileID`（`cloud://...`） |
| `updatedAt` | number | 毫秒时间戳 |

## 索引

控制台 → 数据库 → `users` → 索引：

- 无需额外索引（按 `_id` 精确读写的单用户档案）

若后续按 `updatedAt` 做运营统计，可加：

- `updatedAt` 降序（非唯一）

## 安全规则（个人主体推荐）

仅允许用户读写**自己的**文档：

```json
{
  "read": "doc._openid == auth.openid || doc._id == auth.openid",
  "write": "doc._openid == auth.openid || doc._id == auth.openid"
}
```

说明：

- 业务读写统一走云函数 `userService`（服务端用管理员权限），客户端不直接 `db.collection('users')`。
- 同场成员头像/昵称在进房时写入各玩法 `*_players` 文档，列表展示不依赖读取他人 `users` 文档。

## 云函数 `userService`

| action | 说明 |
|--------|------|
| `getUserInfo` / `get` | 读取当前用户档案，返回 `isComplete`（`nickName` 与 `avatarUrl` 均非空） |
| `updateUserInfo` / `update` | 更新 `nickName` / `avatarUrl` |
| `batchGet` | 批量读档案（预留，最多 24 个 openId） |

部署：微信开发者工具 → 云开发 → 云函数 → 右键 `userService` → 上传并部署。

## 客户端

- `utils/userHelper.js`：`ensureUserInfo(page, callback)`，在首页点击游戏时检查资料
- `components/user-info-modal`：半屏弹窗，`chooseAvatar` + `type="nickname"`
- 本地缓存键：`userInfo`（`wx.setStorageSync('userInfo', { openId, avatarUrl, nickName, updatedAt })`）

## 头像存储路径

`avatars/{openId}_{timestamp}.png`

**同场成员列表要显示彼此头像**，存储权限需允许登录用户读取（否则只能看到自己上传的头像）：

```json
{
  "read": "auth != null",
  "write": "auth != null"
}
```

或控制台选择「所有用户可读，仅创建者可写」。

## 创建集合

**推荐（本机已 `tcb login`）：**

```bash
cd projects/wechat-mini/2026-04-26-family-party-games
./scripts/apply-cloudbase-console.sh   # 含 users 集合与安全规则
# 或仅部署云函数（首次调用也会尝试自动建表）：
./scripts/deploy-all-cloudfunctions.sh
```

**或控制台：** 云开发 → 数据库 → **添加集合** → 名称 **`users`**（全小写）。

未建集合时，点「准备开始」保存头像昵称会报错。执行 `bash scripts/ensure-users-collection.sh` 或部署最新 `userService` 后，云函数会在首次读写时自动 `createCollection('users')`。

## 常见问题

**已创建 `users` 仍提示「请先在云开发控制台创建集合 users」**

多数是云函数误判：新用户还没有自己的那条文档时，数据库会报 `document not exist`，旧版 `userService` 会当成「集合不存在」。请重新**上传并部署 `userService`（云端安装依赖）** 后再试。

若仍失败，请核对：

1. 云开发环境是否为 `cloud1-d9g01no7m292bc511-d5e875d`（与 `cloud-env.js` 一致）
2. 集合名是否为全小写 **`users`**（不是 `Users` / `user`）
3. 云函数日志里是否有 `-502005`（才是真·集合不存在）
