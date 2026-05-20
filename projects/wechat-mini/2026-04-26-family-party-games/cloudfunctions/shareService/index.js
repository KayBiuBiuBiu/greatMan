/**
 * 分享解锁：share_tokens + share_unlock_users + agent_room_feed 推送
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const TOKENS = 'share_tokens'
const USERS = 'share_unlock_users'
const FEED = 'agent_room_feed'
const ANALYTICS = 'analytics_share_unlock'
const TOKEN_TTL_MS = 48 * 60 * 60 * 1000
const SESSION_TTL_MS = 24 * 60 * 60 * 1000
const MAX_LEVEL = 3
const MAX_ACTIVE_TOKENS = 10
const CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
const DB_MISSING_HINT =
  '请先在云开发控制台创建集合 share_tokens、share_unlock_users（见 docs/shareUnlock-部署与测试.md）'

function now() {
  return Date.now()
}

function feedRoomId(sessionId) {
  return 'unlock_' + normSessionId(sessionId)
}

function isDbMissingErr(e) {
  const msg = ((e && e.message) || String(e) || '').toLowerCase()
  const code = e && (e.errCode | e.errcode)
  return (
    code === -502005 ||
    msg.indexOf('not exist') >= 0 ||
    msg.indexOf('not_exists') >= 0 ||
    (msg.indexOf('collection') >= 0 && msg.indexOf('exist') >= 0)
  )
}

function dbMissingResult() {
  return {
    success: false,
    errMsg: DB_MISSING_HINT,
    code: 'COLLECTION_MISSING'
  }
}

async function dbTry(fn) {
  try {
    return await fn()
  } catch (e) {
    if (isDbMissingErr(e)) {
      return { __missing: true }
    }
    throw e
  }
}

function normSessionId(raw) {
  const s = String(raw || '')
    .trim()
    .slice(0, 64)
  return s || 'day_default'
}

function genShortToken() {
  let s = ''
  for (let i = 0; i < 10; i++) {
    s += CHARS[Math.floor(Math.random() * CHARS.length)]
  }
  return s
}

function progressPayload(shareCount) {
  const n = Math.min(MAX_LEVEL, shareCount | 0)
  let nextHint = ''
  if (n === 0) {
    nextHint = '邀请好友点开分享链接解锁 AI 出题'
  } else if (n === 1) {
    nextHint = '再获得 1 次好友确认解锁策略建议'
  } else if (n === 2) {
    nextHint = '再获得 1 次好友确认解锁战报与聚会建议'
  }
  return {
    success: true,
    shareCount: n,
    unlockLevel: n,
    level: n,
    canGen: n >= 1,
    canAssist: n >= 2,
    canRecap: n >= 3,
    nextHint
  }
}

async function trackAnalytics(event, data) {
  try {
    await db.collection(ANALYTICS).add({
      data: Object.assign(
        {
          event: String(event || '').slice(0, 32),
          createdAt: now()
        },
        data || {}
      )
    })
  } catch (e) {
    /* 集合可选，失败忽略 */
  }
}

async function pushUnlockFeed(toOpenId, sessionId, snap) {
  const r = await dbTry(() =>
    db.collection(FEED).add({
      data: {
        roomId: feedRoomId(sessionId),
        type: 'unlock_progress',
        toOpenId: String(toOpenId || ''),
        payload: {
          shareCount: snap.shareCount | 0,
          unlockLevel: snap.unlockLevel | 0,
          level: snap.level | 0
        },
        createdAt: now()
      }
    })
  )
  return !(r && r.__missing)
}

/** 分享码达上限时，作废最旧的一批未使用码以便继续创建 */
async function trimActiveTokens(openId, sessionId, keepMax) {
  const sid = normSessionId(sessionId)
  const maxKeep = Math.max(1, (keepMax | 0) - 1)
  const list = await dbTry(() =>
    db
      .collection(TOKENS)
      .where({
        sharerOpenId: openId,
        sessionId: sid,
        redeemed: false
      })
      .limit(50)
      .get()
  )
  if (list && list.__missing) {
    return -1
  }
  const rows = (list && list.data) || []
  if (rows.length < keepMax) {
    return rows.length
  }
  rows.sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0))
  const toDrop = rows.slice(0, rows.length - maxKeep)
  const t = now()
  for (const row of toDrop) {
    await dbTry(() =>
      db
        .collection(TOKENS)
        .doc(String(row._id))
        .update({
          data: {
            redeemed: true,
            redeemerOpenId: '_trim_active',
            redeemedAt: t
          }
        })
    )
  }
  return maxKeep
}

async function countActiveTokens(openId, sessionId) {
  const sid = normSessionId(sessionId)
  const r = await dbTry(() =>
    db
      .collection(TOKENS)
      .where({
        sharerOpenId: openId,
        sessionId: sid,
        redeemed: false
      })
      .count()
  )
  if (r && r.__missing) {
    return -1
  }
  return (r && r.total) | 0
}

async function getUserDoc(openId, sessionId) {
  const sid = normSessionId(sessionId)
  const r = await dbTry(() =>
    db
      .collection(USERS)
      .where({ openId, sessionId: sid })
      .limit(1)
      .get()
  )
  if (r && r.__missing) {
    return null
  }
  return (r.data && r.data[0]) || null
}

async function ensureUser(openId, sessionId) {
  const t = now()
  const sid = normSessionId(sessionId)
  let doc = await getUserDoc(openId, sid)
  if (doc === null && openId) {
    const probe = await dbTry(() => db.collection(USERS).limit(1).get())
    if (probe && probe.__missing) {
      return null
    }
    doc = await getUserDoc(openId, sid)
  }
  if (!doc) {
    const data = {
      openId,
      sessionId: sid,
      shareCount: 0,
      unlockLevel: 0,
      createdAt: t,
      updatedAt: t,
      expiresAt: t + SESSION_TTL_MS
    }
    const addR = await dbTry(() => db.collection(USERS).add({ data }))
    if (addR && addR.__missing) {
      return null
    }
    if (addR && addR._id) {
      doc = Object.assign({ _id: addR._id }, data)
    } else {
      doc = await getUserDoc(openId, sid)
    }
  }
  if (doc && doc.expiresAt && t > doc.expiresAt) {
    const up = await dbTry(() =>
      db
        .collection(USERS)
        .doc(String(doc._id))
        .update({
          data: {
            shareCount: 0,
            unlockLevel: 0,
            updatedAt: t,
            expiresAt: t + SESSION_TTL_MS
          }
        })
    )
    if (up && up.__missing) {
      return null
    }
    doc.shareCount = 0
    doc.unlockLevel = 0
  }
  return doc
}

async function bumpConfirmed(openId, sessionId) {
  const sid = normSessionId(sessionId)
  for (let attempt = 0; attempt < 2; attempt++) {
    const doc = await ensureUser(openId, sid)
    if (!doc) {
      return dbMissingResult()
    }
    const cur = Math.min(
      MAX_LEVEL,
      ((doc.shareCount | 0) | (doc.unlockLevel | 0))
    )
    if (cur >= MAX_LEVEL) {
      return progressPayload(cur)
    }
    const t = now()
    const up = await dbTry(() =>
      db
        .collection(USERS)
        .doc(String(doc._id))
        .update({
          data: {
            shareCount: _.inc(1),
            unlockLevel: _.inc(1),
            updatedAt: t,
            expiresAt: t + SESSION_TTL_MS
          }
        })
    )
    if (up && up.__missing) {
      return dbMissingResult()
    }
    const next = await getUserDoc(openId, sid)
    if (next && next._id) {
      const count = Math.min(
        MAX_LEVEL,
        ((next.shareCount | 0) | (next.unlockLevel | 0))
      )
      const snap = progressPayload(count)
      await pushUnlockFeed(openId, sid, snap)
      await trackAnalytics('token_redeemed', {
        openId,
        sessionId: sid,
        unlockLevel: count
      })
      return snap
    }
  }
  return dbMissingResult()
}

exports.main = async (event) => {
  const e = event || {}
  if (e.action === 'warm' || e.TriggerName === 'warmer') {
    return { success: true, status: 'warm' }
  }
  try {
    return await run(e)
  } catch (e) {
    console.error('[shareService]', e)
    if (isDbMissingErr(e)) {
      return dbMissingResult()
    }
    return { success: false, errMsg: (e && e.message) || String(e) }
  }
}

async function run(e) {
  const wxContext = cloud.getWXContext()
  const openId = wxContext.OPENID || ''
  const a = e.action

  if (!a) {
    return { success: false, errMsg: '缺少 action' }
  }

  if (a === 'createToken') {
    if (!openId) {
      throw new Error('需要登录')
    }
    const sessionId = normSessionId(e.sessionId)
    const active = await countActiveTokens(openId, sessionId)
    if (active < 0) {
      return dbMissingResult()
    }
    if (active >= MAX_ACTIVE_TOKENS) {
      const trimmed = await trimActiveTokens(openId, sessionId, MAX_ACTIVE_TOKENS)
      if (trimmed < 0) {
        return dbMissingResult()
      }
      const active2 = await countActiveTokens(openId, sessionId)
      if (active2 < 0) {
        return dbMissingResult()
      }
      if (active2 >= MAX_ACTIVE_TOKENS) {
        return {
          success: false,
          errMsg: '分享码过多，请先让好友使用已发出的链接'
        }
      }
    }
    const token = genShortToken()
    const t = now()
    const addR = await dbTry(() =>
      db.collection(TOKENS).add({
        data: {
          token,
          sharerOpenId: openId,
          sessionId,
          roomId: String(e.roomId || '').slice(0, 64),
          kind: String(e.kind || 'index').slice(0, 24),
          redeemed: false,
          redeemerOpenId: '',
          createdAt: t,
          expiresAt: t + TOKEN_TTL_MS
        }
      })
    )
    if (addR && addR.__missing) {
      return dbMissingResult()
    }
    await trackAnalytics('token_created', {
      openId,
      sessionId,
      token,
      kind: String(e.kind || 'index').slice(0, 24)
    })
    return { success: true, token, sessionId }
  }

  if (a === 'checkToken') {
    const token = String(e.token || '')
      .trim()
      .slice(0, 32)
    const q = await dbTry(() =>
      db
        .collection(TOKENS)
        .where({ token })
        .limit(1)
        .get()
    )
    if (q && q.__missing) {
      return dbMissingResult()
    }
    const row = q.data[0]
    if (!row) {
      return { success: true, valid: false, used: false, expired: false, reason: 'invalid' }
    }
    const expired = row.expiresAt && now() > row.expiresAt
    return {
      success: true,
      valid: !row.redeemed && !expired,
      used: !!row.redeemed,
      expired: !!expired,
      reason: row.redeemed ? 'used' : expired ? 'expired' : 'ok'
    }
  }

  if (a === 'redeemToken') {
    if (!openId) {
      throw new Error('需要登录')
    }
    const token = String(e.token || '')
      .trim()
      .slice(0, 32)
    if (!token) {
      return { success: false, errMsg: '缺少 token' }
    }
    const q = await dbTry(() =>
      db
        .collection(TOKENS)
        .where({ token })
        .limit(1)
        .get()
    )
    if (q && q.__missing) {
      return dbMissingResult()
    }
    const row = q.data[0]
    if (!row) {
      return { success: false, errMsg: '无效分享码', reason: 'invalid' }
    }
    if (row.expiresAt && now() > row.expiresAt) {
      return { success: false, errMsg: '分享码已过期', reason: 'expired' }
    }
    if (row.redeemed) {
      return { success: false, errMsg: '分享码已使用', reason: 'used' }
    }
    if (row.sharerOpenId === openId) {
      return { success: false, errMsg: '不能兑换自己的分享', reason: 'self' }
    }
    const up = await dbTry(() =>
      db
        .collection(TOKENS)
        .doc(String(row._id))
        .update({
          data: {
            redeemed: true,
            redeemerOpenId: openId,
            redeemedAt: now()
          }
        })
    )
    if (up && up.__missing) {
      return dbMissingResult()
    }
    const snap = await bumpConfirmed(row.sharerOpenId, row.sessionId)
    if (snap && snap.code === 'COLLECTION_MISSING') {
      return snap
    }
    return {
      success: true,
      data: snap,
      visitorMsg: '已助力好友解锁 AI 功能'
    }
  }

  if (a === 'getProgress') {
    if (!openId) {
      return progressPayload(0)
    }
    const sessionId = normSessionId(e.sessionId)
    const doc = await ensureUser(openId, sessionId)
    if (!doc) {
      return dbMissingResult()
    }
    const count = Math.min(
      MAX_LEVEL,
      ((doc.shareCount | 0) | (doc.unlockLevel | 0))
    )
    const snap = progressPayload(count)
    await trackAnalytics('progress_checked', {
      openId,
      sessionId,
      unlockLevel: count
    })
    return snap
  }

  if (a === 'updateProgress') {
    if (!openId) {
      throw new Error('需要登录')
    }
    const sessionId = normSessionId(e.sessionId)
    const doc = await ensureUser(openId, sessionId)
    if (!doc) {
      return dbMissingResult()
    }
    const lv = Math.min(MAX_LEVEL, Math.max(0, e.unlockLevel | 0))
    const up = await dbTry(() =>
      db
        .collection(USERS)
        .doc(String(doc._id))
        .update({
          data: {
            shareCount: lv,
            unlockLevel: lv,
            updatedAt: now(),
            expiresAt: now() + SESSION_TTL_MS
          }
        })
    )
    if (up && up.__missing) {
      return dbMissingResult()
    }
    const snap = progressPayload(lv)
    await pushUnlockFeed(openId, sessionId, snap)
    return snap
  }

  if (a === 'checkUnlock') {
    if (!openId) {
      return { success: true, unlocked: false, unlockLevel: 0 }
    }
    const sessionId = normSessionId(e.sessionId)
    const doc = await ensureUser(openId, sessionId)
    if (!doc) {
      return Object.assign({ unlocked: false, unlockLevel: 0 }, dbMissingResult())
    }
    const lv = Math.min(
      MAX_LEVEL,
      ((doc.shareCount | 0) | (doc.unlockLevel | 0))
    )
    const need = Math.max(1, e.requiredLevel | 0)
    return {
      success: true,
      unlocked: lv >= need,
      unlockLevel: lv,
      shareCount: lv
    }
  }

  return { success: false, errMsg: '未知 action ' + a }
}
