/**
 * 副主持播报写入房间 feed，供小程序 watch / 轮询（无订阅消息时兜底）
 */
const cloud = require('wx-server-sdk')
const db = cloud.database()

const FEED = 'agent_room_feed'

async function notifyPlayers(roomId, gameKind, speakText) {
  const rid = String(roomId || '')
  const text = String(speakText || '').trim()
  if (!rid || !text) {
    return { ok: false, reason: 'empty' }
  }
  try {
    await db.collection(FEED).add({
      data: {
        roomId: rid,
        gameKind: String(gameKind || ''),
        speakText: text,
        createdAt: Date.now()
      }
    })
    return { ok: true }
  } catch (e) {
    console.warn('[hostAgent notify]', e.message || e)
    return { ok: false, error: (e && e.message) || String(e) }
  }
}

module.exports = { notifyPlayers, FEED }
