const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态' }
  }
  if (event._deleteId) {
    try {
      await db.collection('record').doc(String(event._deleteId)).remove()
    } catch (e) {
      return { errMsg: (e && e.message) || '删除失败' }
    }
    return { ok: true }
  }
  const now = Date.now()
  if (event._id) {
    const patch = Object.assign({}, event)
    delete patch._id
    delete patch._deleteId
    await db
      .collection('record')
      .doc(String(event._id))
      .update({ data: Object.assign(patch, { updatedAt: now }) })
    return { ok: true }
  }
  const d = {
    _openid: openid,
    petId: String(event.petId || ''),
    kind: event.kind || 'feed',
    title: String(event.title || '').slice(0, 200),
    detail: String(event.detail || '').slice(0, 500),
    amount: event.amount,
    recordTime: event.recordTime != null ? Number(event.recordTime) : now,
    createdAt: now
  }
  const res = await db.collection('record').add({ data: d })
  return { id: res._id }
}
