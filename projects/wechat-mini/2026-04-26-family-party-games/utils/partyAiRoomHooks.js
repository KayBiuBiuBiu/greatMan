/**
 * 进房 / 离房时绑定聚会场次与分享卡片预热
 */
const { startPartyAiSession, endPartyAiSession, hadActiveRoomSession } = require('./partyAiSession')
const {
  refreshAiUnlockPage,
  syncUnlockFromCloud,
  onPageHideUnlock,
  resetAiUnlockLocal,
  prepareShareToken
} = require('./aiUnlock')
const { warmShareCard } = require('./shareInviteCard')
const { PRESETS } = require('./shareHelper')

function onRoomEntered(page, roomId, kind) {
  if (roomId) {
    startPartyAiSession(roomId)
  }
  refreshAiUnlockPage(page)
  syncUnlockFromCloud({ page, silent: true })
  if (page && kind) {
    const preset = PRESETS[kind] || PRESETS.index
    const ctx =
      page._shareCtx && typeof page._shareCtx === 'function'
        ? page._shareCtx()
        : {}
    const code = String(ctx.roomCode || page.data.roomCode || '')
      .replace(/\D/g, '')
      .slice(0, 8)
    const title =
      code && preset.roomTitle
        ? preset.roomTitle(code)
        : preset.defaultTitle
    warmShareCard(page, { title, code })
    prepareShareToken(page, { roomId: String(roomId), kind: kind || 'index' })
  }
}

function onRoomLeft(page) {
  onPageHideUnlock(page)
  if (hadActiveRoomSession()) {
    endPartyAiSession()
    resetAiUnlockLocal()
  }
  refreshAiUnlockPage(page)
}

module.exports = { onRoomEntered, onRoomLeft }
