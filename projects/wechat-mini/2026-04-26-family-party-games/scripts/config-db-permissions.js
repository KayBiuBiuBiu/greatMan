#!/usr/bin/env node

/**
 * 通过 CloudBase HTTP API 配置数据库集合权限和索引
 *
 * 使用方法:
 * 1. 获取 API Key: https://tcb.cloud.tencent.com → 设置 → API 管理
 * 2. 运行: node scripts/config-db-permissions.js --api-key YOUR_API_KEY
 */

const https = require('https')
const path = require('path')
const fs = require('fs')

// 读取环境 ID
const configPath = path.join(__dirname, '..', 'cloudbaserc.json')
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
const envId = config.envId

console.log(`📦 环境 ID: ${envId}\n`)

// 集合配置
const collections = [
  {
    name: 'gesture_rooms',
    permissions: {
      read: ['in(db.getOpenId())'],
      write: ['db.getOpenId() === "admin"'],
      admin: ['db.getOpenId() === "admin"']
    },
    indexes: [
      {
        key: { roomCode: 1 },
        unique: true,
        sparse: true
      }
    ]
  },
  {
    name: 'gesture_players',
    permissions: {
      read: ['in(db.getOpenId())'],
      write: ['db.getOpenId() === "admin"'],
      admin: ['db.getOpenId() === "admin"']
    },
    indexes: [
      {
        key: { roomId: 1, openId: 1 },
        unique: true,
        sparse: true
      }
    ]
  },
  {
    name: 'gesture_gameState',
    permissions: {
      read: ['in(db.getOpenId())'],
      write: ['db.getOpenId() === "system"'],
      admin: ['db.getOpenId() === "admin"']
    },
    indexes: []
  }
]

function makeHttpRequest(method, path, body = null) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'tcb.tencentcloudapi.com',
      port: 443,
      path,
      method,
      headers: {
        'Content-Type': 'application/json'
      }
    }

    const req = https.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => {
        data += chunk
      })
      res.on('end', () => {
        try {
          resolve(JSON.parse(data))
        } catch (e) {
          resolve({ raw: data, statusCode: res.statusCode })
        }
      })
    })

    req.on('error', reject)

    if (body) {
      req.write(JSON.stringify(body))
    }
    req.end()
  })
}

console.log(`⚠️  CloudBase HTTP API 权限配置需要 API Key`)
console.log(`\n获取方式:`)
console.log(`1. 打开 https://tcb.cloud.tencent.com/`)
console.log(`2. 选择环境: ${envId}`)
console.log(`3. 设置 → API 管理 → 创建 API Key`)
console.log(`4. 复制 Secret ID 和 Secret Key`)
console.log(`\n权限表达式说明:`)
console.log(`- read: 'in(db.getOpenId())' = 登录用户可读`)
console.log(`- write: 'db.getOpenId() === "admin"' = 仅管理员/云函数可写`)
console.log(`- write: 'db.getOpenId() === "system"' = 仅云函数可写`)
console.log(`\n📌 更简单的方法: 直接通过 CloudBase 控制台手动设置权限`)
console.log(`   https://tcb.cloud.tencent.com/ → 数据库 → 权限编辑`)
console.log(`\n集合权限配置需要:`)
collections.forEach(col => {
  console.log(`\n✓ ${col.name}`)
  if (col.indexes && col.indexes.length > 0) {
    console.log(`  索引:`)
    col.indexes.forEach(idx => {
      const keys = Object.keys(idx.key).map(k => `${k}:${idx.key[k]}`).join(', ')
      console.log(`    - ${keys}${idx.unique ? ' (唯一)' : ''}`)
    })
  }
})

console.log(`\n✅ 建议: 通过 CloudBase 控制台在线配置会更简单快速`)
