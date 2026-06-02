/**
 * 配置你比划我猜数据库集合的权限和索引
 * 这个云函数用来设置已创建的集合的权限规则和索引
 */

const cloud = require('wx-server-sdk')

cloud.init({
  env: cloud.DYNAMIC_CURRENT_ENV
})

const db = cloud.database()

exports.main = async (event, context) => {
  try {
    console.log('开始配置数据库集合权限和索引...\n')

    const results = []

    // ========== 集合 1: gesture_rooms ==========
    try {
      console.log('✓ 配置 gesture_rooms...')

      // 设置权限：仅管理员可写
      await db.collection('gesture_rooms').setPermission({
        read: 'in(db.getOpenId())',
        write: 'admin',
        admin: 'admin'
      })
      console.log('  ✅ 权限设置: ADMIN only')

      // 创建索引：roomCode (唯一)
      await db.collection('gesture_rooms').createIndex({
        key: { roomCode: 1 },
        unique: true,
        sparse: true
      })
      console.log('  ✅ 索引创建: roomCode (唯一)')

      results.push({
        collection: 'gesture_rooms',
        status: 'success',
        permissions: 'ADMIN only',
        indexes: ['roomCode (unique)']
      })
    } catch (err) {
      console.error(`  ❌ 配置失败:`, err.message)
      results.push({
        collection: 'gesture_rooms',
        status: 'error',
        message: err.message
      })
    }

    // ========== 集合 2: gesture_players ==========
    try {
      console.log('\n✓ 配置 gesture_players...')

      // 设置权限：仅管理员可写
      await db.collection('gesture_players').setPermission({
        read: 'in(db.getOpenId())',
        write: 'admin',
        admin: 'admin'
      })
      console.log('  ✅ 权限设置: ADMIN only')

      // 创建索引：roomId + openId (复合唯一)
      await db.collection('gesture_players').createIndex({
        key: { roomId: 1, openId: 1 },
        unique: true,
        sparse: true
      })
      console.log('  ✅ 索引创建: roomId + openId (复合唯一)')

      results.push({
        collection: 'gesture_players',
        status: 'success',
        permissions: 'ADMIN only',
        indexes: ['roomId + openId (composite unique)']
      })
    } catch (err) {
      console.error(`  ❌ 配置失败:`, err.message)
      results.push({
        collection: 'gesture_players',
        status: 'error',
        message: err.message
      })
    }

    // ========== 集合 3: gesture_gameState ==========
    try {
      console.log('\n✓ 配置 gesture_gameState...')

      // 设置权限：登录用户可读，仅云函数可写
      // 权限表达式：
      // - read: in(db.getOpenId()) = 登录用户可读
      // - write: db.getOpenId() === 'system' = 仅云函数可写
      // - admin: 'admin' = 管理员可改权限
      await db.collection('gesture_gameState').setPermission({
        read: 'in(db.getOpenId())',
        write: 'db.getOpenId() === "system"',
        admin: 'admin'
      })
      console.log('  ✅ 权限设置: 登录读 / 云函数写')

      console.log('  ✅ 索引: (无需创建)')

      results.push({
        collection: 'gesture_gameState',
        status: 'success',
        permissions: 'login read / cloud function write',
        indexes: '(none)'
      })
    } catch (err) {
      console.error(`  ❌ 配置失败:`, err.message)
      results.push({
        collection: 'gesture_gameState',
        status: 'error',
        message: err.message
      })
    }

    console.log('\n✅ 配置完成！\n')

    return {
      code: 0,
      message: '数据库集合配置完成',
      results
    }
  } catch (err) {
    console.error('❌ 配置失败:', err)
    return {
      code: -1,
      message: '配置失败',
      error: err.message
    }
  }
}
