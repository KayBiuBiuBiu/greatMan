#!/usr/bin/env node
/**
 * 读取 cloudfunctions/aiPartyService/secrets.local.json，写入 config.json 的 envVariables 并部署
 * 用法：node scripts/deploy-ai-party-service.js
 */
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const ROOT = path.join(__dirname, '..')
const FN_DIR = path.join(ROOT, 'cloudfunctions/aiPartyService')
const SECRETS = path.join(FN_DIR, 'secrets.local.json')
const CONFIG = path.join(FN_DIR, 'config.json')
const ENV_ID = 'cloud1-d9g01no7m292bc511-d5e875d'
const CLI =
  process.platform === 'darwin'
    ? '/Applications/wechatwebdevtools.app/Contents/MacOS/cli'
    : 'cli'

function readSecrets() {
  if (!fs.existsSync(SECRETS)) {
    console.error('缺少 ' + SECRETS)
    console.error('请复制 secrets.local.json.example 为 secrets.local.json 并填入 HUNYUAN_API_KEY')
    process.exit(1)
  }
  const s = JSON.parse(fs.readFileSync(SECRETS, 'utf8'))
  const key = String(s.HUNYUAN_API_KEY || '').trim()
  if (!key || key.includes('你的')) {
    console.error('请在 secrets.local.json 中填写有效的 HUNYUAN_API_KEY')
    process.exit(1)
  }
  return s
}

function patchConfig(secrets) {
  const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'))
  cfg.envVariables = {
    HUNYUAN_API_KEY: String(secrets.HUNYUAN_API_KEY).trim(),
    HUNYUAN_API_BASE: String(
      secrets.HUNYUAN_API_BASE || 'https://api.hunyuan.cloud.tencent.com/v1/'
    ).trim()
  }
  fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2) + '\n')
  console.log('[deploy] 已写入 config.json envVariables（勿提交含 Key 的 config.json）')
}

function restoreConfig() {
  const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'))
  delete cfg.envVariables
  fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2) + '\n')
  console.log('[deploy] 已从 config.json 移除 envVariables')
}

function main() {
  const secrets = readSecrets()
  patchConfig(secrets)
  let code = 1
  try {
    if (!fs.existsSync(CLI)) {
      console.error('未找到微信开发者工具 CLI:', CLI)
      console.error('请手动：右键 aiPartyService → 上传并部署：所有文件')
      return
    }

    const args = [
      'cloud',
      'functions',
      'deploy',
      '--env',
      ENV_ID,
      '--names',
      'aiPartyService',
      '--project',
      ROOT,
      '--remote-npm-install'
    ]
    console.log('[deploy] 执行:', CLI, args.join(' '))
    console.log('[deploy] 请先打开微信开发者工具，并在 设置→安全设置 中开启「服务端口」')
    const r = spawnSync(CLI, args, { stdio: 'inherit', encoding: 'utf8' })
    code = r.status === 0 ? 0 : r.status || 1
  } finally {
    restoreConfig()
  }
  process.exit(code)
}

main()
