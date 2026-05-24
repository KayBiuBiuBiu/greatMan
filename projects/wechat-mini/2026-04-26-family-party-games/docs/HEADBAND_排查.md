# 贴头猜词 · 排查协作指南

卡住时按下面做，把 **诊断弹窗全文** 或 **控制台 `[hb cloud]` 日志** 复制给 Cursor，最快定位。

---

## 第一步：重新部署（最常见原因）

1. 微信开发者工具 → **云开发** → 环境选 `cloud1-d9g01no7m292bc511-d5e875d`（与 `cloud-env.js` 一致）
2. 展开 `cloudfunctions/headbandRoomService` → 右键 **上传并部署：云端安装依赖**（不要选「仅上传代码」）
3. 若报错 `Cannot find module 'wx-server-sdk'`：说明依赖未装上，务必用 **云端安装依赖** 重传；本地可在该目录执行 `npm install --registry https://registry.npmjs.org/` 生成 `package-lock.json` 后再传
4. 确认 **`generateCharacters`** 在同一环境也已部署
4. 小程序 **编译** 后重试

---

## 第二步：页面内一键诊断

1. 打开 **贴头猜词** 页（未进房界面即可）
2. 点击 **「进不去 / 建房失败？点我运行连通性诊断」**
3. 看弹窗四项是否全 ✅：

| 项 | 全 ✅ 表示 |
|----|------------|
| cloud-env.js envId | 环境 ID 已配置 |
| headbandRoomService | 云函数已部署且能读 `headband_rooms` / `headband_players` |
| generateCharacters | 词库云函数可用 |

有 ❌ 时，把弹窗内容原样发给 Cursor。

---

## 第三步：控制台日志（开发者工具）

1. **调试器 → Console**
2. 再操作一次（创建聚会组 / 加入 / 开始游戏）
3. 筛选关键字：`[hb cloud]`、`[headband 诊断]`
4. 复制相关几行（含 `errMsg`）

示例：

```text
[hb cloud] create { errMsg: '...' }
[hb cloud] ping { ok: true, roomsOk: true, playersOk: true }
```

---

## 第四步：告诉 Cursor「卡在哪一步」

请用下面模板回复（勾选 + 贴日志）：

```text
【环境】真机 / 模拟器
【操作】创建聚会组 / 加入口令 / 开始游戏 / 猜词 / 其他：___
【现象】Toast 原文：___  或  一直 loading / 进了卧底页面 等
【诊断弹窗】（粘贴）
【Console [hb cloud]】（粘贴）
【是否已部署】headbandRoomService 是/否  generateCharacters 是/否
```

---

## 常见问题对照

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 请部署云函数 headbandRoomService | 未上传或未选对云环境 | 上传并部署 + 核对 envId |
| Cannot find module 'wx-server-sdk' | 上传时未安装依赖 | **上传并部署：云端安装依赖**（见上） |
| Cannot find module '@cloudbase/node-sdk/ai' | `generateCharacters` 或 SDK 版本问题 | 已内置词库兜底；请用 `wx-server-sdk@2.6.3` 重部署 `headbandRoomService` |
| 聚会组不存在 | 口令是别的游戏房间的 | 在贴头猜词页建房，用该页口令 |
| 首页输入 6 位进了卧底 | 该口令不是贴头房间 | 在贴头猜词内建房再分享 |
| 词库生成失败 | generateCharacters 未部署或返回 code≠0 | 部署词库云函数；看诊断第三项 |
| 生成口令失败 | roomCode 冲突或集合权限 | 查 headband_rooms 是否 ADMINONLY；重试建房 |
| 同步无成员 | 未 join 成功 | 分享链接进房；看 `[hb cloud] syncState` |

---

## 云函数手动测 ping（可选）

云开发 → 云函数 → `headbandRoomService` → **云端测试**：

```json
{ "action": "ping" }
```

期望返回：

```json
{ "ok": true, "roomsOk": true, "playersOk": true, "hasOpenId": true }
```
