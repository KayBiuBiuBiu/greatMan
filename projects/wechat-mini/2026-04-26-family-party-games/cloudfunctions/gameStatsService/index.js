/**
 * 首页各互动「开始互动」点击全站统计（同场热门排序）。
 * 需在云数据库中新建集合 `game_clicks`（可空），或首次 add 时由控制台开集合。
 * 仅云函数写入；客户端经本函数 listRanks / bumpStart 调用。
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command
const COL = 'game_clicks'

exports.main = async (event) => {
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}

async function run (e) {
  const a = e.action
  if (a === 'listRanks') {
    const r = await db
      .collection(COL)
      .limit(500)
      .get()
    const ranks = {}
    ;(r.data || []).forEach((d) => {
      if (d && d.title) {
        ranks[d.title] = d.clicks | 0
      }
    })
    return { ranks }
  }
  if (a === 'bumpStart') {
    const title = String(e.title || '')
      .trim()
      .slice(0, 64)
    if (!title) {
      throw new Error('缺 title')
    }
    const now = Date.now()
    const q = await db
      .collection(COL)
      .where({ title })
      .limit(1)
      .get()
    if (q.data[0] && q.data[0]._id) {
      await db
        .collection(COL)
        .doc(String(q.data[0]._id))
        .update({ data: { clicks: _.inc(1), updatedAt: now } })
    } else {
      try {
        await db.collection(COL).add({
          data: { title, clicks: 1, createdAt: now, updatedAt: now }
        })
      } catch (err) {
        const q2 = await db
          .collection(COL)
          .where({ title })
          .limit(1)
          .get()
        if (q2.data[0] && q2.data[0]._id) {
          await db
            .collection(COL)
            .doc(String(q2.data[0]._id))
            .update({ data: { clicks: _.inc(1), updatedAt: now } })
        } else {
          throw err
        }
      }
    }
    return { ok: 1, title }
  }
  throw new Error('未知 action')
}
