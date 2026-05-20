#!/usr/bin/env node
/** 仅把 secrets.local.json 同步到 config.json，便于在开发者工具里手动「上传并部署」 */
const fs = require('fs')
const path = require('path')

const FN = path.join(__dirname, '../cloudfunctions/aiPartyService')
const SECRETS = path.join(FN, 'secrets.local.json')
const CONFIG = path.join(FN, 'config.json')

if (!fs.existsSync(SECRETS)) {
  console.error('请先创建', SECRETS)
  process.exit(1)
}
const s = JSON.parse(fs.readFileSync(SECRETS, 'utf8'))
const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'))
cfg.envVariables = {
  HUNYUAN_API_KEY: String(s.HUNYUAN_API_KEY || '').trim(),
  HUNYUAN_API_BASE: String(s.HUNYUAN_API_BASE || 'https://api.hunyuan.cloud.tencent.com/v1/').trim()
}
fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2) + '\n')
console.log('已写入 config.json envVariables')
console.log('请在微信开发者工具：右键 aiPartyService → 上传并部署：所有文件')
console.log('部署完成后运行: node scripts/restore-ai-party-config.js')
