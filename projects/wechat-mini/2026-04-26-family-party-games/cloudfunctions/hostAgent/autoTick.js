/**
 * 定时触发器：扫描进行中的房间并自动 tick
 */
const cloud = require('wx-server-sdk')
const db = cloud.database()
const _ = db.command

const { runTick } = require('./tick')
const { notifyPlayers } = require('./notify')

async function listActiveRooms(limit) {
  const max = limit | 0 || 10
  const list = []

  try {
    const drink = await db
      .collection('drink_rooms')
      .where({ status: _.in(['open', 'playing']) })
      .limit(Math.min(max, 5))
      .get()
    ;(drink.data || []).forEach((r) => {
      list.push({ gameKind: 'drink', roomId: r._id, _id: r._id })
    })
  } catch (e) {
    console.warn('[autoTick] drink_rooms', e.message || e)
  }

  try {
    const uc = await db
      .collection('uc_rooms')
      .where({
        currentPhase: _.nin(['waiting', 'ended', ''])
      })
      .limit(Math.min(max, 5))
      .get()
    ;(uc.data || []).forEach((r) => {
      list.push({ gameKind: 'undercover', roomId: r._id, _id: r._id })
    })
  } catch (e) {
    console.warn('[autoTick] uc_rooms', e.message || e)
  }

  try {
    const ww = await db
      .collection('werewolf_state')
      .where({
        currentPhase: _.exists(true)
      })
      .limit(Math.min(max, 3))
      .get()
    ;(ww.data || []).forEach((r) => {
      const ph = r.currentPhase || ''
      if (ph && ph !== 'ended' && ph !== 'waiting') {
        list.push({ gameKind: 'werewolf', roomId: r._id, _id: r._id })
      }
    })
  } catch (e) {
    console.warn('[autoTick] werewolf_state', e.message || e)
  }

  return list.slice(0, max)
}

async function handleAutoTick(event) {
  const limit = (event && event.limit) | 0 || 10
  const activeRooms = await listActiveRooms(limit)
  const results = []

  for (let i = 0; i < activeRooms.length; i++) {
    const room = activeRooms[i]
    try {
      const tick = await runTick(room.gameKind, room.roomId)
      if (tick.speakText) {
        await notifyPlayers(room.roomId, room.gameKind, tick.speakText)
      }
      results.push({
        roomId: room.roomId,
        gameKind: room.gameKind,
        ok: true,
        speakText: tick.speakText || ''
      })
    } catch (e) {
      results.push({
        roomId: room.roomId,
        gameKind: room.gameKind,
        ok: false,
        error: (e && e.message) || String(e)
      })
    }
  }

  return {
    autoTick: true,
    processed: results.length,
    results
  }
}

module.exports = { handleAutoTick, listActiveRooms }
