const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async () => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态', list: [] }
  }
  const r = await db
    .collection('pet')
    .where({ _openid: openid })
    .orderBy('createdAt', 'desc')
    .get()
  const data = (r.data || []).filter((p) => !p.archived)
  return { list: data }
}
