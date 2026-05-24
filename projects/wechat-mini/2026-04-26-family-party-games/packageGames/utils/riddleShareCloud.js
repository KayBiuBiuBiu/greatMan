/**
 * 海龟汤分享云函数 riddleShare
 */
const { ensureCloudInit, getCallFunctionConfig } = require('../../utils/cloudInit')

const CALL_TIMEOUT_MS = 15000

function callRiddleShare(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    onError && onError(new Error('no cloud'))
    return
  }
  if (!ensureCloudInit()) {
    onError && onError(new Error('no cloud init'))
    return
  }
  wx.cloud.callFunction({
    name: 'riddleShare',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data: data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg), icon: 'none', duration: 3200 })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: '分享服务暂不可用', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callRiddleShare }
