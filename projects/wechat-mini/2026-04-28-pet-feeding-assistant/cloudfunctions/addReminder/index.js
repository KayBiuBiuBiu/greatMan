const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

function nextAtFrom (repeat, base) {
  const t = new Date(base)
  if (repeat === 'once') {
    return base
  }
  if (repeat === 'daily') {
    t.setDate(t.getDate() + 1)
  } else if (repeat === 'weekly') {
    t.setDate(t.getDate() + 7)
  } else if (repeat === 'monthly') {
    t.setMonth(t.getMonth() + 1)
  }
  return t.getTime()
}

exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态' }
  }
  if (event._deleteId) {
    try {
      await db.collection('reminder').doc(String(event._deleteId)).remove()
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
    if (patch.remindTime) {
      patch.nextAt = nextAtFrom(
        patch.repeat || 'once',
        Number(patch.remindTime)
      )
    }
    await db
      .collection('reminder')
      .doc(String(event._id))
      .update({ data: Object.assign(patch, { updatedAt: now }) })
    return { ok: true }
  }
  const rem = event.repeat || 'once'
  const rt = event.remindTime != null ? Number(event.remindTime) : now
  const d = {
    _openid: openid,
    petId: String(event.petId || ''),
    kind: String(event.kind || 'feed'),
    title: String(event.title || '').slice(0, 100),
    repeat: rem,
    remindTime: rt,
    nextAt: nextAtFrom(rem, rt),
    enabled: event.enabled !== false,
    createdAt: now,
    updatedAt: now
  }
  const res = await db.collection('reminder').add({ data: d })
  return { id: res._id }
}
