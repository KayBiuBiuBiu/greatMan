# 宠伴日常 — 宠物喂养助手

普通微信小程序（`compileType: "miniprogram"`）+ 微信云开发。类目建议：**工具 → 实用工具 → 生活便民**（以平台最新类目为准）。

## 快速开始

1. 用 **微信开发者工具** 导入本目录 `2026-04-28-pet-feeding-assistant`。
2. 在 `project.config.json` 中填写你的 **AppID**（`touristappid` 仅为占位）。
3. 在小程序后台**开通云开发**，将云环境 ID 填到 `cloud-env.js` 的 `CLOUD_ENV_ID`。
4. 右键 `cloudfunctions` 下各函数目录 → **上传并部署：云端安装依赖**（共 7 个：addPet、getPetList、addRecord、getRecordList、addReminder、getReminderList、statisticData）。
5. 在**云开发控制台**创建集合（建议）：`pet`、`record`、`reminder`；权限请按你方安全要求配置（仅云函数写 / 仅创建者可读写等）。

未开通云开发时，客户端会**回退到本机 `wx.setStorage` 模拟**（`utils/cloud.js`），便于界面联调，**正式与云端同步依赖云环境**。

## 提审用文案

见 `docs/audit-copy.md`，可直接复制简介与审核备注到微信公众平台。

## 项目结构

- `pages/index` 首页，今日待办、宠物入口、快捷操作
- `pages/pet` 宠物档案（列表/新建编辑/详情）
- `pages/record` 养护记录（筛选项、列表/时间线、新增弹层）
- `pages/reminder` 养护提醒（增删、开关、订阅说明）
- `pages/mine` 我的，合规说明与知识库入口
- `pages/knowledge` 养宠知识（预置 14 篇图文摘要 + 正文体）
- `components/pet-card` 宠物卡
- `data/knowledge.js`、`data/breeds.js` 静态数据
- `utils/cloud.js`、`utils/format.js`

## 能力说明

- 相册/拍照选图使用 `wx.chooseMedia`，在「宠物档案」中调用。
- 订阅消息需在**公众平台**申请模板，并在业务代码中配置 `tmplIds` 后，用户可接收提醒（当前为说明位，不强制调起请求）。

## 协议与责任

养宠知识库为**健康科普与日常管理参考，非医疗诊断**；请在使用说明与知识详情页强调线下就医场景。
