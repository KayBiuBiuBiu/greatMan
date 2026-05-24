/**
 * 调用已部署云函数 generateCharacters（勿修改该云函数本身）
 */
const { ensureCloudInit, getCallFunctionConfig } = require('./cloudInit')

const CALL_TIMEOUT_MS = 60000

function callGenerateCharacters(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    onError && onError(new Error('no cloud'))
    return
  }
  if (!ensureCloudInit()) {
    onError && onError(new Error('no init'))
    return
  }
  wx.cloud.callFunction({
    name: 'generateCharacters',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data: data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r.code !== 0) {
        const msg = r.message || '词库生成失败'
        if (!silent) {
          wx.showToast({ title: msg, icon: 'none', duration: 3500 })
        }
        onError && onError(new Error(msg), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: '词库服务超时，请重试', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callGenerateCharacters }
