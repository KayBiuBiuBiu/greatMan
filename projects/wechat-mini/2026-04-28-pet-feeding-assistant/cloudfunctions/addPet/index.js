const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async (event) => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态' }
  }
  const now = Date.now()
  if (event._id) {
    const patch = Object.assign({}, event)
    delete patch._id
    await db
      .collection('pet')
      .doc(String(event._id))
      .update({ data: Object.assign(patch, { updatedAt: now }) })
    return { ok: true }
  }
  const d = {
    _openid: openid,
    name: String(event.name || '').trim().slice(0, 20) || '未命名',
    category: event.category || 'cat',
    breed: String(event.breed || '').slice(0, 32),
    birthday: event.birthday || '',
    gender: event.gender || '',
    weight: event.weight != null ? Number(event.weight) : '',
    neutered: !!event.neutered,
    note: String(event.note || '').slice(0, 500),
    photo: String(event.photo || '').slice(0, 500),
    archived: false,
    createdAt: now,
    updatedAt: now
  }
  const res = await db.collection('pet').add({ data: d })
  return { id: res._id }
}
