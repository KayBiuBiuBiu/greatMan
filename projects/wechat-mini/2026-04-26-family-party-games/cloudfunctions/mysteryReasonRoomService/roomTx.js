/**
 * 房间写操作事务封装（微信云数据库 runTransaction）
 */
function createRoomTx(db, collectionName, getTime) {
  async function runRoomTx(roomId, mutator) {
    const rid = String(roomId)
    let out = null
    await db.runTransaction(async (transaction) => {
      const snap = await transaction.collection(collectionName).doc(rid).get()
      const room = snap.data
      if (!room) throw new Error('聚会组无效')
      const patch = await mutator(room, transaction)
      if (patch && typeof patch === 'object' && Object.keys(patch).length > 0) {
        patch.updateTime = getTime()
        await transaction.collection(collectionName).doc(rid).update({ data: patch })
        out = Object.assign({}, room, patch)
      } else {
        out = room
      }
    })
    return out
  }

  return { runRoomTx }
}

module.exports = { createRoomTx }
