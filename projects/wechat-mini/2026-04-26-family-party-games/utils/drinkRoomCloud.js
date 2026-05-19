let configEnv
try {
  const cfg = require('../cloud-env.js')
  configEnv = (cfg && cfg.envId) || ''
} catch (e) {
  configEnv = ''
}

function ensure() {
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
function formatFail(err) {
  const raw =
    (err && (err.errMsg != null && String(err.errMsg))) ||
    (err && err.message != null && String(err.message)) ||
    ''
  if (!raw) {
    return '未部署或网络异常，请检查云环境并上传 drinkRoomService'
  }
  if (
    /-501000|FUNCTION_NOT_FOUND|function\s*is\s*not\s*found/i.test(raw) ||
    /(not\s*found|未部署|不存在)/i.test(raw)
  ) {
    return '请上传并部署云函数「drinkRoomService」并选对云环境'
  }
  if (/time\s*out|超时|504|502|network|网络/i.test(raw)) {
    return '云请求超时，请重试'
  }
  return raw.length > 20 ? raw.slice(0, 20) + '…' : raw
}

/**
 * 趣味抽签同场云
 */
function callDrink(data, opts) {
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
    name: 'drinkRoomService',
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
      if (!silent) {
        wx.showToast({ title: formatFail(err), icon: 'none', duration: 4000 })
      }
      onError && onError(err)
    }
  })
}
module.exports = { callDrink, ensure }
