/** 身份推理板子人数：6 / 8 / 10 / 12 */
const SIZES = [6, 8, 10, 12]
const STORAGE_KEY = 'werewolf_board_size'
const HINT = '可选 6 / 8 / 10 / 12 人局（不含主持）'

function indexOfSize(n) {
  const i = SIZES.indexOf(parseInt(n, 10) || 0)
  return i >= 0 ? i : 0
}

function sizeAtIndex(i) {
  return SIZES[Math.max(0, Math.min(SIZES.length - 1, i | 0))] || 6
}

const { stepIndex, vibrateBoundary } = require('./listStepper')

function stepSizeIndex(curIndex, delta) {
  const r = stepIndex(curIndex, delta, SIZES.length)
  return {
    index: r.index,
    atBoundary: r.atBoundary,
    size: sizeAtIndex(r.index)
  }
}

function loadStoredSize() {
  const n = parseInt(wx.getStorageSync(STORAGE_KEY), 10)
  return SIZES.indexOf(n) >= 0 ? n : 6
}

function saveStoredSize(n) {
  if (SIZES.indexOf(n | 0) >= 0) {
    wx.setStorageSync(STORAGE_KEY, n)
  }
}

function isValidSize(n) {
  return SIZES.indexOf(parseInt(n, 10) || 0) >= 0
}

module.exports = {
  SIZES,
  STORAGE_KEY,
  HINT,
  indexOfSize,
  sizeAtIndex,
  stepSizeIndex,
  vibrateBoundary,
  loadStoredSize,
  saveStoredSize,
  isValidSize
}
