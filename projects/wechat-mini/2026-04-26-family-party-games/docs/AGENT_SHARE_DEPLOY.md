# hostAgentEnhanced / shareCardGenerator 部署说明

## 云函数目录

- `cloudfunctions/hostAgentEnhanced` — AI 分析 / 提示 / 战报
- `cloudfunctions/shareCardGenerator` — 邀请 / 战绩 / 解锁分享卡片

## 部署方式（推荐微信开发者工具）

1. 打开本项目，确认 `project.config.json` 中 `cloudfunctionRoot` 为 `cloudfunctions/`。
2. 在终端为两个目录安装依赖：

```bash
cd cloudfunctions/hostAgentEnhanced && npm install
cd ../shareCardGenerator && npm install
```

3. 在开发者工具左侧 **云开发** 面板中，分别右键上述两个文件夹 → **上传并部署：云端安装依赖**。
4. `shareCardGenerator` 需在云开发控制台为云函数开通 **wxacode.getUnlimited**（`config.json` 已声明）；未开通时仍返回 SVG 与分享路径，二维码可能为空。

## 数据库（可选）

控制台新建集合 **`share_cards`**（用于记录生成历史）。未创建也不影响卡片生成，仅无法写入记录。

## 小程序端

| 文件 | 说明 |
|------|------|
| `utils/aiHost.js` | 调用 `hostAgentEnhanced`，失败回退 `hostAgent` |
| `utils/shareCard.js` | 调用 `shareCardGenerator`，邀请卡失败回退本地画布 |
| `pages/share/card/card` | 分享卡片预览页 |
| `cloud-env.js` | `useHostAgentEnhanced` / `useShareCardGenerator` 开关 |

## 验证

```javascript
// 开发者工具 Console
wx.cloud.callFunction({ name: 'hostAgentEnhanced', data: { action: 'ping' } })
wx.cloud.callFunction({ name: 'shareCardGenerator', data: { action: 'ping' } })
```

`ping` 应返回 `buildId`: `hostAgentEnhanced-v1` / `shareCardGenerator-v1`。

## 已集成页面

- **谁是卧底** 结束阶段：`AI 主持助手`、`分享战绩卡片`
- 其他同房游戏可复制 `onShowAIAssist` / `shareAchievement` 写法
