let configEnv
try {
  const cfg = require('../cloud-env.js')
  configEnv = (cfg && cfg.envId) || ''
} catch (e) {
  configEnv = ''
}

function ensure () {
  if (!wx.cloud) {
    return false
  }
  const app = getApp && getApp()
  if (app && app.globalData && app.globalData.cloudInited) {
    return true
  }
  const o = { traceUser: true }
  if (configEnv) {
    o.env = configEnv
  } else if (wx.cloud.DYNAMIC_CURRENT_ENV != null) {
    o.env = wx.cloud.DYNAMIC_CURRENT_ENV
  }
  wx.cloud.init(o)
  if (app && app.globalData) {
    app.globalData.cloudInited = true
  }
  return true
}

function callDraw (data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    onError && onError()
    return
  }
  if (!ensure()) {
    onError && onError()
    return
  }
  wx.cloud.callFunction({
    name: 'drawRoomService',
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r && r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg), icon: 'none' })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: '同场同步服务暂不可用，请稍后再试', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callDraw, ensure }
