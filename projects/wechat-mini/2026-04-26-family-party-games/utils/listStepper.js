/** 列表步进：+/- 在固定选项间切换，边界可震动 */
function stepIndex(curIndex, delta, length) {
  const len = length | 0
  if (len <= 0) {
    return { index: 0, atBoundary: true }
  }
  const cur = curIndex | 0
  const next = cur + (delta > 0 ? 1 : delta < 0 ? -1 : 0)
  if (next < 0 || next >= len) {
    return { index: cur, atBoundary: true }
  }
  return { index: next, atBoundary: false }
}

function vibrateBoundary() {
  if (wx.vibrateShort) {
    wx.vibrateShort({ type: 'light' })
  }
}

module.exports = {
  stepIndex,
  vibrateBoundary
}
