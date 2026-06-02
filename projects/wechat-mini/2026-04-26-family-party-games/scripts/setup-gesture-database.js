#!/usr/bin/env node

/**
 * 为「你比划我猜」创建数据库集合
 * 用法: node setup-gesture-database.js
 */

const fs = require('fs')
const path = require('path')

// 读取环境 ID
const configPath = path.join(__dirname, '..', 'cloudbaserc.json')
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
const envId = config.envId

console.log(`📦 环境 ID: ${envId}\n`)

// 动态加载 CloudBase SDK
const tcb = require('@cloudbase/node-sdk')

// 初始化应用
const app = tcb.initializeApp({
  env: envId,
  autoAuth: false
})

// 获取数据库引用
const db = app.database()

// 集合定义
const collections = [
  {
    name: 'gesture_rooms',
    indexes: [
      {
        key: { roomCode: 1 },
        unique: true,
        name: 'roomCode_unique'
      }
    ],
    description: '你比划我猜 - 房间主表'
  },
  {
    name: 'gesture_players',
    indexes: [
      {
        key: { roomId: 1, openId: 1 },
        unique: true,
        name: 'roomId_openId_unique'
      }
    ],
    description: '你比划我猜 - 玩家表'
  },
  {
    name: 'gesture_gameState',
    indexes: [],
    description: '你比划我猜 - 游戏状态表'
  }
]

// 创建集合
async function setupCollections() {
  try {
    console.log('📋 开始创建集合...\n')

    for (const collection of collections) {
      try {
        console.log(`✓ 创建 ${collection.name}`)

        // 创建集合
        await db.createCollection(collection.name)
        console.log(`  ✅ 集合创建成功: ${collection.name}`)

        // 创建索引
        if (collection.indexes && collection.indexes.length > 0) {
          for (const index of collection.indexes) {
            await db.collection(collection.name).createIndex({
              unique: index.unique || false,
              sparse: true,
              key: index.key,
              name: index.name
            })
            console.log(`  ✅ 索引创建成功: ${index.name}`)
          }
        }

        console.log('')
      } catch (err) {
        // 集合可能已存在，继续
        if (err.code === 'RESOURCE_EXISTS_ERR' || /already exists/i.test(err.message)) {
          console.log(`  ℹ️  集合已存在: ${collection.name}`)
        } else {
          console.error(`  ❌ 错误: ${err.message}`)
        }
      }
    }

    console.log('\n✅ 数据库集合设置完成！')
    console.log('   - gesture_rooms (房间表)')
    console.log('   - gesture_players (玩家表)')
    console.log('   - gesture_gameState (游戏状态表)')
    process.exit(0)
  } catch (err) {
    console.error('❌ 设置失败:', err)
    process.exit(1)
  }
}

setupCollections()
