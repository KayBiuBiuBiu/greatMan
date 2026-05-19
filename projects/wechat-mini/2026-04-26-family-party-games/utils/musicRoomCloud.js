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

function callMusic (data, opts) {
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
    name: 'musicRoomService',
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
        wx.showToast({ title: '请部署云函数 musicRoomService', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callMusic, ensure }
