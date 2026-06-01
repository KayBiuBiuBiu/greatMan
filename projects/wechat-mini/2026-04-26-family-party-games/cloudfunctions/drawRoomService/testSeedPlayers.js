/**
 * Minium 测试：向房间注入虚拟玩家（需 event._test === true）
 */
function assertTestAction(e) {
  if (!e || !e._test) {
    throw new Error('test action denied')
  }
}

/**
 * 向独立 players 表注入成员
 * opts: { db, playersCol, roomId, room, incoming, cap, jp, baseFields, refreshState }
 */
async function seedPlayersCollection(opts) {
  const o = opts || {}
  assertTestAction(o.event)
  const db = o.db
  const P = o.playersCol
  const jp = o.jp
  const rid = String(o.roomId || '')
  let pl0 = await o.listPlayers(rid)
  const incoming = (o.event && o.event.players) || []
  const cap = (o.cap | 0) > 0 ? (o.cap | 0) : 12
  for (let i = 0; i < incoming.length; i += 1) {
    const p = incoming[i] || {}
    const oid = String(p.openId || '').trim()
    if (!oid || pl0.some((x) => x.openId === oid)) {
      continue
    }
    if (pl0.length >= cap) {
      break
    }
    await db.collection(P).add({
      data: Object.assign({}, o.baseFields(p, pl0.length), jp.mergeJoinFields(p, {}))
    })
    pl0 = await o.listPlayers(rid)
  }
  if (typeof o.refreshState === 'function') {
    await o.refreshState(rid)
  }
  return {
    ok: true,
    playerCount: pl0.length,
    roomId: rid,
    roomCode: o.roomCode || ''
  }
}

module.exports = {
  assertTestAction,
  seedPlayersCollection
}
