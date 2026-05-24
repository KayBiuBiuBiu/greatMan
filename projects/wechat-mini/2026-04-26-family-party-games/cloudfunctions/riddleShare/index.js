/**
 * 海龟汤汤面分享：短 token 存 share_riddles，好友按 token 拉取同一题
 */
const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const COL = 'share_riddles'
const TTL_MS = 7 * 24 * 60 * 60 * 1000

function makeToken() {
  const a = Math.random().toString(36).slice(2, 8)
  const b = Date.now().toString(36).slice(-6)
  return (a + b).slice(0, 16)
}

function packRiddleData(raw) {
  const d = raw && typeof raw === 'object' ? raw : {}
  return {
    title: String(d.title || '').trim().slice(0, 80) || '海龟汤',
    detail: String(d.detail || '').trim().slice(0, 500),
    answer: String(d.answer || '').trim().slice(0, 500),
    hint: String(d.hint || '').trim().slice(0, 200)
  }
}

async function createShare(event) {
  const riddleId = event.riddleId != null ? (event.riddleId | 0) : -1
  const riddleData = packRiddleData(event.riddleData)
  if (!riddleData.detail) {
    throw new Error('汤面内容为空')
  }
  const token = makeToken()
  const now = Date.now()
  await db.collection(COL).add({
    data: {
      token: token,
      riddleId: riddleId,
      riddleData: riddleData,
      createdAt: now,
      expireAt: now + TTL_MS
    }
  })
  return { ok: true, token: token, riddleId: riddleId }
}

async function getShare(event) {
  const token = String(event.token || '')
    .trim()
    .replace(/[^a-zA-Z0-9]/g, '')
    .slice(0, 24)
  if (!token) {
    throw new Error('分享链接无效')
  }
  const now = Date.now()
  const res = await db
    .collection(COL)
    .where({ token: token })
    .limit(1)
    .get()
  const row = res.data && res.data[0]
  if (!row) {
    throw new Error('分享已过期或不存在')
  }
  if (row.expireAt && row.expireAt < now) {
    throw new Error('分享已过期，请让朋友重新分享')
  }
  return {
    ok: true,
    token: token,
    riddleId: row.riddleId != null ? row.riddleId : -1,
    riddleData: row.riddleData || null
  }
}

exports.main = async function (event) {
  const action = event.action
  if (action === 'create') {
    return createShare(event)
  }
  if (action === 'get') {
    return getShare(event)
  }
  throw new Error('未知操作')
}
