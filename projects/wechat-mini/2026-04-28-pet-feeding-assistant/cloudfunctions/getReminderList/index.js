const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

exports.main = async () => {
  const openid = cloud.getWXContext().OPENID
  if (!openid) {
    return { errMsg: '无登录态', list: [] }
  }
  let r
  try {
    r = await db
      .collection('reminder')
      .where({ _openid: openid })
      .orderBy('nextAt', 'asc')
      .get()
  } catch (e) {
    r = await db.collection('reminder').where({ _openid: openid }).get()
  }
  const list = (r && r.data) || []
  list.sort((a, b) => (a.nextAt || 0) - (b.nextAt || 0))
  return { list }
}
