/**
 * 用户档案：集合 users，文档 ID = openId
 * 字段：openId, nickName, avatarUrl(云存储 fileID), updatedAt
 *
 * 数据库权限建议见 docs/USERS_DB.md
 */
const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const USERS = 'users'
const MAX_NICK = 32
let usersCollectionReady = false

function isCollectionAlreadyExistsErr(e) {
  const msg = ((e && e.message) || String(e) || '').toLowerCase()
  return (
    msg.indexOf('already exist') >= 0 ||
    msg.indexOf('resourceexist') >= 0 ||
    msg.indexOf('已存在') >= 0 ||
    msg.indexOf('重复') >= 0
  )
}

/** 集合未建时自动创建（无需手动画控制台） */
async function ensureUsersCollection() {
  if (usersCollectionReady) {
    return
  }
  try {
    await db.createCollection(USERS)
    usersCollectionReady = true
  } catch (e) {
    if (isCollectionAlreadyExistsErr(e)) {
      usersCollectionReady = true
      return
    }
    if (isCollectionMissingErr(e)) {
      throw new Error('请先在云开发控制台创建集合 users（见 docs/USERS_DB.md）')
    }
    console.warn('[userService] ensureUsersCollection', e)
    usersCollectionReady = true
  }
}

function now() {
  return Date.now()
}

function errCode(e) {
  if (e == null) {
    return null
  }
  if (e.errCode != null) {
    return e.errCode
  }
  if (e.errcode != null) {
    return e.errcode
  }
  return null
}

/** 文档不存在（新用户尚未写入）≠ 集合不存在 */
function isDocumentNotFoundErr(e) {
  const msg = ((e && e.message) || String(e) || '').toLowerCase()
  const code = errCode(e)
  if (code === -1) {
    return true
  }
  if (msg.indexOf('document') >= 0 && msg.indexOf('not exist') >= 0) {
    return true
  }
  if (msg.indexOf('document') >= 0 && msg.indexOf('not found') >= 0) {
    return true
  }
  if (msg.indexOf('does not exist') >= 0 && msg.indexOf('document') >= 0) {
    return true
  }
  if (msg.indexOf('文档') >= 0 && (msg.indexOf('不存在') >= 0 || msg.indexOf('未找到') >= 0)) {
    return true
  }
  return false
}

/** 仅当 users 集合本身未创建时返回 true */
function isCollectionMissingErr(e) {
  if (isDocumentNotFoundErr(e)) {
    return false
  }
  const msg = ((e && e.message) || String(e) || '').toLowerCase()
  const code = errCode(e)
  return (
    code === -502005 ||
    msg.indexOf('collection not exist') >= 0 ||
    msg.indexOf('table not exist') >= 0 ||
    msg.indexOf('db or table not exist') >= 0 ||
    (msg.indexOf('collection') >= 0 &&
      msg.indexOf('not exist') >= 0 &&
      msg.indexOf('document') < 0) ||
    msg.indexOf('集合') >= 0 && msg.indexOf('不存在') >= 0 && msg.indexOf('文档') < 0
  )
}

function emptyProfile(openId) {
  return {
    openId,
    nickName: '',
    avatarUrl: '',
    updatedAt: 0
  }
}

function sanitizeNick(raw) {
  return String(raw || '')
    .trim()
    .slice(0, MAX_NICK)
}

function sanitizeAvatar(raw) {
  const s = String(raw || '').trim()
  if (!s) {
    return ''
  }
  if (s.indexOf('cloud://') === 0 || s.indexOf('http') === 0) {
    return s.slice(0, 512)
  }
  return ''
}

async function getProfile(openId, retried) {
  await ensureUsersCollection()
  try {
    const d = await db.collection(USERS).doc(openId).get()
    const row = d.data || {}
    return {
      openId,
      nickName: sanitizeNick(row.nickName),
      avatarUrl: sanitizeAvatar(row.avatarUrl),
      updatedAt: row.updatedAt | 0
    }
  } catch (e) {
    if (isCollectionMissingErr(e) && !retried) {
      usersCollectionReady = false
      await ensureUsersCollection()
      return getProfile(openId, true)
    }
    if (isCollectionMissingErr(e)) {
      throw new Error('users 集合不可用，请重新部署 userService 或联系管理员')
    }
    if (isDocumentNotFoundErr(e)) {
      return emptyProfile(openId)
    }
    console.warn('[userService] getProfile', e)
    return emptyProfile(openId)
  }
}

async function upsertProfile(openId, patch) {
  let nick = patch.nickName
  let avatar = patch.avatarUrl
  if (nick === undefined || avatar === undefined) {
    const prev = await getProfile(openId)
    if (nick === undefined) {
      nick = prev.nickName
    }
    if (avatar === undefined) {
      avatar = prev.avatarUrl
    }
  }
  const data = {
    openId,
    nickName: sanitizeNick(nick),
    avatarUrl: sanitizeAvatar(avatar),
    updatedAt: now()
  }
  try {
    await db.collection(USERS).doc(openId).set({ data })
  } catch (e) {
    if (isCollectionMissingErr(e)) {
      usersCollectionReady = false
      await ensureUsersCollection()
      try {
        await db.collection(USERS).doc(openId).set({ data })
        return data
      } catch (e2) {
        if (isCollectionMissingErr(e2)) {
          throw new Error('users 集合不可用，请重新部署 userService 或联系管理员')
        }
        throw e2
      }
    }
    throw e
  }
  return data
}

exports.main = async (event) => {
  try {
    await ensureUsersCollection()
    const wxContext = cloud.getWXContext()
    const openId = wxContext.OPENID
    if (!openId) {
      return { errMsg: '未获取到用户身份，请稍后重试' }
    }
    const action = (event && event.action) || 'get'
    if (
      action === 'get' ||
      action === 'getUserInfo'
    ) {
      const profile = await getProfile(openId)
      const isComplete = !!(
        profile.nickName && profile.avatarUrl
      )
      return {
        ok: true,
        profile,
        userInfo: profile,
        isComplete
      }
    }
    if (
      action === 'update' ||
      action === 'updateUserInfo'
    ) {
      const patch = {}
      if (event.nickName !== undefined) {
        patch.nickName = event.nickName
      }
      if (event.avatarUrl !== undefined) {
        patch.avatarUrl = event.avatarUrl
      }
      if (!Object.keys(patch).length) {
        return { errMsg: '无更新字段' }
      }
      const profile = await upsertProfile(openId, patch)
      const isComplete = !!(
        profile.nickName && profile.avatarUrl
      )
      return {
        ok: true,
        profile,
        userInfo: profile,
        isComplete
      }
    }
    if (action === 'batchGet') {
      const ids = Array.isArray(event.openIds) ? event.openIds : []
      const uniq = []
      const seen = {}
      for (let i = 0; i < ids.length; i += 1) {
        const id = String(ids[i] || '').trim()
        if (!id || seen[id]) {
          continue
        }
        seen[id] = true
        uniq.push(id)
        if (uniq.length >= 24) {
          break
        }
      }
      const map = {}
      for (let j = 0; j < uniq.length; j += 1) {
        const id = uniq[j]
        map[id] = await getProfile(id)
      }
      return { ok: true, profiles: map }
    }
    return { errMsg: '未知 action: ' + action }
  } catch (e) {
    console.error('[userService]', e)
    return { errMsg: (e && e.message) || String(e) }
  }
}
