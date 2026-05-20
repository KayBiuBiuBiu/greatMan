#!/usr/bin/env node
/** 从 config.json 移除 envVariables，避免 Key 被 git 提交 */
const fs = require('fs')
const path = require('path')
const CONFIG = path.join(__dirname, '../cloudfunctions/aiPartyService/config.json')
const cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8'))
delete cfg.envVariables
fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2) + '\n')
console.log('已从 config.json 移除 envVariables')
