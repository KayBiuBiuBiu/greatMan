const { ensureCloudInit, getCallFunctionConfig } = require('./cloudInit')
const { toCloudError } = require('./cloudCallFail')

const CALL_TIMEOUT_MS = 30000

function ensure() {
  return ensureCloudInit()
}

/**
 * 趣味抽签同场云
 */
function callDrink(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud || !ensure()) {
    const err = new Error('请先开通云开发')
    if (!silent) {
      wx.showToast({ title: err.message, icon: 'none' })
    }
    onError && onError(err)
    return
  }
  wx.cloud.callFunction({
    name: 'drinkRoomService',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r && r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg), icon: 'none', duration: 3200 })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      const friendly = toCloudError(err)
      if (!silent) {
        wx.showToast({ title: friendly.message, icon: 'none', duration: 4000 })
      }
      onError && onError(friendly)
    }
  })
}
module.exports = { callDrink, ensure }
