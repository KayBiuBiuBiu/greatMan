/**
 * 聚会组「房号」文案：强调是数字口令，不是最少人数。
 */
const LABEL = '6 位数字口令'
const PLACEHOLDER = '6 位数字'
const TOAST_6 = '请输入 6 位数字口令'
const TOAST_4_OR_6 = '请输入 4 位或 6 位数字口令'
const HINT_NEARBY = '把口令发给亲友进组，无陌生匹配'

/** 点击口令数字复制到剪贴板，并 Toast 提示 */
function copyRoomCodeToClipboard(code) {
  const c = String(code || '')
    .replace(/\D/g, '')
    .slice(0, 8)
  if (!c) {
    wx.showToast({ title: '暂无口令', icon: 'none' })
    return
  }
  wx.setClipboardData({
    data: c,
    success: () => {
      wx.showToast({ title: '口令已复制', icon: 'none' })
    },
    fail: () => {
      wx.showToast({ title: '复制失败，请重试', icon: 'none' })
    }
  })
}

module.exports = {
  ROOM_CODE_LABEL: LABEL,
  ROOM_CODE_PLACEHOLDER: PLACEHOLDER,
  TOAST_ROOM_CODE_6: TOAST_6,
  TOAST_ROOM_CODE_4_OR_6: TOAST_4_OR_6,
  HINT_NEARBY: HINT_NEARBY,
  copyRoomCodeToClipboard
}
