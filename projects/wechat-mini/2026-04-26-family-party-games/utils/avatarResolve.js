/**
 * 云存储 fileID → 小程序 <image> 可显示的 HTTPS 临时链接
 */
const { ensureCloudInit } = require('./cloudInit')

const _cache = {}

function resolveAvatarDisplayUrl(url) {
  const raw = String(url || '').trim()
  if (!raw) {
    return Promise.resolve('')
  }
  if (/^https?:\/\//i.test(raw)) {
    return Promise.resolve(raw)
  }
  if (raw.indexOf('cloud://') !== 0) {
    return Promise.resolve(raw)
  }
  if (_cache[raw]) {
    return Promise.resolve(_cache[raw])
  }
  if (!ensureCloudInit() || !wx.cloud) {
    return Promise.resolve(raw)
  }
  return new Promise((resolve) => {
    wx.cloud.getTempFileURL({
      fileList: [raw],
      success(res) {
        const item = (res && res.fileList && res.fileList[0]) || {}
        if (item.tempFileURL) {
          _cache[raw] = item.tempFileURL
          resolve(item.tempFileURL)
          return
        }
        resolve(raw)
      },
      fail() {
        resolve(raw)
      }
    })
  })
}

module.exports = {
  resolveAvatarDisplayUrl
}
