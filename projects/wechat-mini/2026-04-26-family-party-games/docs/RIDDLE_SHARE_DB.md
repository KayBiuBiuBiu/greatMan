# 海龟汤分享 · 云数据库 `share_riddles`

## 集合

| 集合名 | 说明 |
|--------|------|
| `share_riddles` | 海龟汤分享记录，短 token 映射到汤面数据 |

## 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `token` | string | 短标识，分享路径 `rt=` 参数，建议 8～16 位字母数字 |
| `riddleId` | number | 内置题库索引（`game-data` 中 prompts 下标），自定义题为 -1 |
| `riddleData` | object | `{ title, detail, answer, hint }` |
| `createdAt` | number | 创建时间 ms |
| `expireAt` | number | 过期时间 ms（默认 7 天） |

## 索引（请在云开发控制台创建）

1. **token 唯一索引**（必建）  
   - 字段：`token`  
   - 类型：升序  
   - 唯一：是  

2. **expireAt 普通索引**（可选，便于定时清理过期记录）  
   - 字段：`expireAt`  
   - 类型：升序  

## 权限建议

- 小程序端：**不**直连读写该集合  
- 仅云函数 `riddleShare` 读写（云函数侧有管理员权限）

## 云函数

- 名称：`riddleShare`
- `action: create` — 创建分享，入参 `riddleId`, `riddleData`
- `action: get` — 按 `token` 拉取汤面

部署：微信开发者工具 → 右键 `cloudfunctions/riddleShare` → 上传并部署。
