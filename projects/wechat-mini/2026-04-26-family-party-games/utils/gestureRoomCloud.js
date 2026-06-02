const { ensureCloudInit } = require('./cloudInit')
const { toCloudError } = require('./cloudCallFail')

function callGesture(data, opts) {
  const { onOk, onError, silent } = opts || {}

  if (!ensureCloudInit()) {
    const err = new Error('请先开通云开发')
    if (!silent) wx.showToast({ title: err.message, icon: 'none' })
    onError && onError(err)
    return
  }

  wx.cloud.callFunction({
    name: 'gestureRoomService',
    config: { env: wx.cloud.database().config.env },
    timeout: 30000,
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r && r.errMsg) {
        if (!silent) wx.showToast({ title: String(r.errMsg), icon: 'none' })
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      const friendly = toCloudError(err)
      if (!silent) wx.showToast({ title: friendly.message, icon: 'none', duration: 4000 })
      onError && onError(friendly)
    }
  })
}

module.exports = { callGesture }
