/**
 * 聚会场次：每场进房新开 sessionId，离房后本地解锁进度清零（云端按 sessionId 分桶）
 */
const STORAGE_KEY = 'party_ai_session_v1'

function pad2(n) {
  return n < 10 ? '0' + n : String(n)
}

function todayKey() {
  const d = new Date()
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

function readSession() {
  try {
    const raw = wx.getStorageSync(STORAGE_KEY)
    if (!raw || typeof raw !== 'object') {
      return null
    }
    return raw
  } catch (e) {
    return null
  }
}

/** 当前用于云端 / 本地的 sessionId */
function getCurrentSessionId() {
  const raw = readSession()
  if (raw && raw.sessionId) {
    return String(raw.sessionId)
  }
  return 'day_' + todayKey()
}

/**
 * 进入同场房间时调用（创建/加入成功）
 * @param {string} roomId
 */
function startPartyAiSession(roomId) {
  const rid = roomId ? String(roomId).slice(0, 48) : ''
  const sessionId =
    'sess_' +
    Date.now().toString(36) +
    Math.random().toString(36).slice(2, 8)
  try {
    wx.setStorageSync(STORAGE_KEY, {
      sessionId,
      roomId: rid,
      startedAt: Date.now()
    })
  } catch (e) {
    /* ignore */
  }
  return sessionId
}

/** 离开房间页时调用 */
function endPartyAiSession() {
  try {
    wx.removeStorageSync(STORAGE_KEY)
  } catch (e) {
    /* ignore */
  }
}

function hadActiveRoomSession() {
  const raw = readSession()
  return !!(raw && raw.roomId)
}

module.exports = {
  getCurrentSessionId,
  startPartyAiSession,
  endPartyAiSession,
  hadActiveRoomSession,
  todayKey
}
