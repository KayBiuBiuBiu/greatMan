const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态', feedCount: 0, waterCount: 0, weightSeries: [] }
  }
  const now = Date.now()
  const days = event && (event.range === 30 || event.range === '30') ? 30 : 7
  const t0 = now - days * 24 * 60 * 60 * 1000
  const r = await db
    .collection('record')
    .where(
      event.petId
        ? { _openid: openid, petId: String(event.petId) }
        : { _openid: openid }
    )
    .get()
    .catch(() => ({ data: [] }))
  const list = ((r && r.data) || []).filter((x) => (x.recordTime || 0) >= t0)
  const feedCount = list.filter((x) => x.kind === 'feed').length
  const waterCount = list.filter((x) => x.kind === 'water').length
  return { feedCount, waterCount, byDay: [], weightSeries: [] }
}
