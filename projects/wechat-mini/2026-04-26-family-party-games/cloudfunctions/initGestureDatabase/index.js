/**
 * 初始化你比划我猜数据库集合
 * 这是一个临时云函数，用来创建必要的数据库集合
 * 部署后在微信开发者工具中执行一次，然后可以删除
 */

const cloud = require('wx-server-sdk')

cloud.init({
  env: cloud.DYNAMIC_CURRENT_ENV
})

const db = cloud.database()

exports.main = async (event, context) => {
  try {
    console.log('开始初始化数据库集合...')

    // 集合列表
    const collections = [
      'gesture_rooms',
      'gesture_players',
      'gesture_gameState'
    ]

    const results = []

    for (const collName of collections) {
      try {
        // 尝试在集合中插入一条测试文档（会自动创建集合）
        const insertResult = await db.collection(collName).add({
          _init: true,
          _timestamp: Date.now()
        })

        console.log(`✅ 集合创建成功: ${collName}`)
        results.push({
          collection: collName,
          status: 'success',
          message: '集合已创建'
        })

        // 立即删除初始化文档
        await db.collection(collName).doc(insertResult._id).remove()
        console.log(`✅ 临时文档已删除: ${collName}`)
      } catch (err) {
        console.error(`❌ 集合创建失败: ${collName}`, err.message)
        results.push({
          collection: collName,
          status: 'error',
          message: err.message
        })
      }
    }

    return {
      code: 0,
      message: '初始化完成',
      results
    }
  } catch (err) {
    console.error('❌ 初始化失败:', err)
    return {
      code: -1,
      message: '初始化失败',
      error: err.message
    }
  }
}
