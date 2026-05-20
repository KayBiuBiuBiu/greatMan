# AI 聚会助手

云环境：`cloud1-d9g01no7m292bc511`（见 `cloud-env.js`）

混元 OpenAPI 基址（官方）：`https://api.hunyuan.cloud.tencent.com/v1/`（已写入 `cloud-env.js` 的 `hunyuanApiBase`）

官方调用示例（Python，Key 勿提交仓库）：

```python
from openai import OpenAI
client = OpenAI(
    api_key="您的API Key",  # 勿提交仓库
    base_url="https://api.hunyuan.cloud.tencent.com/v1",
)
response = client.chat.completions.create(
    model="hunyuan-lite",
    messages=[{"role": "user", "content": "你好"}],
)
print(response.choices[0].message.content)
```

云函数 `aiPartyService/hunyuanOpenApi.js` 请求同一接口 `POST /v1/chat/completions`（与上例等价），`apiKey` 来自环境变量 `HUNYUAN_API_KEY`。

> **说明**：小程序端仍用 `createModel('hunyuan')` + `generateText`（不写 Key）。若 `extend.AI` 不通，可在云函数 **aiPartyService** 配置环境变量直连 OpenAPI（Key **仅**放云端，勿写入 `cloud-env.js` 或提交 Git）：
>
> | 变量名 | 示例 | 说明 |
> |--------|------|------|
> | `HUNYUAN_API_KEY` | `sk-***` | 混元 API Key（控制台创建） |
> | `HUNYUAN_API_BASE` | `https://api.hunyuan.cloud.tencent.com/v1/` | 可选，默认与 `cloud-env.js` 一致 |
>
> **方式 A（推荐）云开发控制台**  
> 云开发 → 云函数 → **aiPartyService** → 配置 → 环境变量 → 保存 → 重新部署。
>
> **方式 B 项目脚本（部署时写入，不提交 Key）**
>
> ```bash
> # 1. 填写 cloudfunctions/aiPartyService/secrets.local.json（已 gitignore）
> npm run prepare:ai-party
> # 2. 微信开发者工具：右键 aiPartyService → 上传并部署：所有文件
> npm run restore:ai-party
> ```
>
> **方式 C 腾讯云 CLI（需已安装 tccli 且 configure）**
>
> ```bash
> pip install tccli && tccli configure
> chmod +x scripts/set-scf-env-from-secrets.sh
> ./scripts/set-scf-env-from-secrets.sh
> ```
>
> 或手动（将 `sk-***` 换成你的 Key；`Namespace` 为云环境 ID）：
>
> ```bash
> tccli scf UpdateFunctionConfiguration \
>   --region ap-shanghai \
>   --FunctionName aiPartyService \
>   --Namespace cloud1-d9g01no7m292bc511 \
>   --Environment '{"Variables":[{"Key":"HUNYUAN_API_KEY","Value":"sk-***"},{"Key":"HUNYUAN_API_BASE","Value":"https://api.hunyuan.cloud.tencent.com/v1/"}]}' \
>   --Timeout 60
> ```
>
> **安全**：Key 勿写入 `cloud-env.js`、文档或 Git；若已泄露请作废并重新生成。

## 部署

1. 微信开发者工具 → **云开发** → 顶部环境必须选 **`cloud1-d9g01no7m292bc511`**（与 `cloud-env.js` 的 `envId` 一致）。
2. 云开发控制台 → **AI** → 确认已开通 **hunyuan-lite**（主）及 **hy3-preview**（备）与混元生图。
3. 部署 `aiPartyService`、`imageService`（依赖 **wx-server-sdk ~3.0.4**，勿写不存在的 3.9.x 版本号）：
   - 在终端进入对应目录执行 `npm install`（生成 `node_modules`）；
   - 开发者工具右键该函数 → **上传并部署：所有文件**（若「云端安装依赖」报「更新云函数失败」，改用此项）。
   - **超时**：两函数 `config.json` 均为 `"timeout": 60`（生图较慢）；小程序端 `runAiPoster` 等待 **65s**。
   - **tccli 改云端超时**（可选）：`npm run set-scf-timeout`（含 `aiPartyService` / `imageService` / `hostAgent` / `aiPlayer`）或单独指定函数名。
4. 小程序 **基础库 ≥ 3.15.1**（`project.private.config.json` 已设 `3.15.2`）。
5. `app.js` 启动时会 `wx.cloud.init({ env: envId })`，所有 `callFunction` 带 `config.env` 指向同一环境。

## 各玩法 AI 入口

| 玩法 | 功能 |
|------|------|
| 趣味抽签 | 结果页：AI 解说、趣味任务建议 |
| 谁是卧底 | 等待：AI 出题并发牌；结束：战报文案 |
| 你画我猜 | 等待：AI 出题 → 点开始使用 |
| 真心话大冒险 | 出新题、题目加码、同场投票点评 |
| 故事接龙 | AI 接一句 |
| 身份推理 | 结束战报 |
| 疯狂猜歌 | 主持开场词 / 提示 |

## 调用链

`pages/*` → `utils/aiHelper.js` → `createModel('hunyuan').generateText({ data: { model: 'hunyuan-lite', messages } })`（失败降级云函数 `aiPartyService`）  
失败时 → 云函数 `aiPartyService`（`action: 'chat'`，同样 `generateText`）。

生图：`runAiPoster` → `imageService` → 返回 `{ success, imageUrl, revised_prompt }`（图片 URL 约 24h 有效）。

## 验证 AI 是否计入 CloudBase 用量

CloudBase 控制台 → **AI 用量**：生文 Token / 生图张数从 **0 变为 >0** 即表示闭环跑通（可能延迟 **数分钟**）。

### 快速自检（推荐）

1. 开发者工具编译后，在**首页长按标题「家庭聚会助手」** → 弹出「AI 连通测试」。
2. 成功会显示：环境 ID、通道（`client` 或 `cloudFunction`）、模型名、回复「好」。
3. 刷新 CloudBase **AI 用量** 页，观察 Token 是否增加。

### 若用量仍为 0

| 检查项 | 说明 |
|--------|------|
| 云环境 | 工具栏云开发环境 = `cloud1-d9g01no7m292bc511`；`cloud-env.js` 的 `envId` 一致 |
| 云函数 | `aiPartyService`、`imageService` 已部署且状态正常；依赖为 wx-server-sdk **3.x** |
| 基础库 | ≥ 3.15.1；真机预览/体验版再测一次（模拟器偶发不走 extend.AI） |
| 缓存 | `runAi` 有 **5 分钟内存缓存**，重复点同一解说**不会再次扣费**；自检会 `clearAiCache`，玩法内请点「换一个」或换 `cacheTag` |
| 控制台日志 | 开启 `debugCloudLog: true` 时，Console 有 `[ai] { via, modelUsed, usage }` |
| 模型 | 主：`hunyuan` / `hunyuan-lite`；备：`cloudbase` / `hy3-preview`（见 `cloud-env.js`） |

### 真机冒烟

趣味抽签 → 进组 → 出结果 → 点 **AI 解说** → 等回复 → 回控制台刷新用量。

## 分享确认解锁 AI（shareService）

好友通过带 `st` 的分享链接进入后，为**分享者本场聚会**累计解锁（进房新 session，离房清零；首页按自然日）。

**流程说明**：见 [`docs/分享解锁AI功能流程.md`](分享解锁AI功能流程.md)  
**部署与双机测试**：见 [`docs/shareUnlock-部署与测试.md`](shareUnlock-部署与测试.md)

梯度：1 次好友确认 → AI 出题；2 次 → 策略；3 次 → 战报 / 聚会建议。未解锁时点 🔒 弹出分享弹窗（A/B 文案 + 绿色分享按钮）。

## 相关文档

- 玩法与 AI 细节：`docs/游戏玩法与逻辑说明.md` §7、§14
- 本地单测：`npm run test:ai-cache`
