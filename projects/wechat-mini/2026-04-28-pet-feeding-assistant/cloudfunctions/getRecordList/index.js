const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态', list: [] }
  }
  const cond = { _openid: openid }
  if (event.petId) {
    cond.petId = String(event.petId)
  }
  if (event.type && event.type !== 'all') {
    cond.kind = event.type
  }
  const r = await db.collection('record').where(cond).orderBy('recordTime', 'desc').get()
  let list = (r.data || []).slice()
  if (event.range && event.range !== 'all') {
    const now = Date.now()
    const days = event.range === 30 || event.range === '30' ? 30 : 7
    const t0 = now - days * 24 * 60 * 60 * 1000
    list = list.filter((x) => (x.recordTime || 0) >= t0)
  }
  return { list }
}
