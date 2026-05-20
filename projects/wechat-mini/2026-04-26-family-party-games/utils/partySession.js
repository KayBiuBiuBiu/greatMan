/**
 * 本机聚会进度：是否已完成过至少一局同场互动（用于首页 AI 聚会建议等）
 */
const STORAGE_KEY = 'party_finished_once_v1'

function markPartyFinishedOnce() {
  try {
    wx.setStorageSync(STORAGE_KEY, true)
  } catch (e) {
    /* ignore */
  }
}

function hasPartyFinishedOnce() {
  try {
    return !!wx.getStorageSync(STORAGE_KEY)
  } catch (e) {
    return false
  }
}

module.exports = {
  markPartyFinishedOnce,
  hasPartyFinishedOnce
}
