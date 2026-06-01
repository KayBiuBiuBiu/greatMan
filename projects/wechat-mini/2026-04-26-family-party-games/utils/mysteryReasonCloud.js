const { ensureCloudInit, getCallFunctionConfig } = require('./cloudInit')

const CALL_TIMEOUT_MS = 120000

function formatFail(err) {
  const raw =
    (err && err.errMsg) ||
    (err && err.message) ||
    ''
  if (/time\s*out|超时|504/i.test(String(raw))) {
    return '云请求超时，请重试'
  }
  if (/not\s*found|未部署|FUNCTION_NOT_FOUND/i.test(String(raw))) {
    return '请部署云函数 mysteryReasonRoomService'
  }
  return String(raw).slice(0, 28) || '网络异常'
}

function callMysteryReason(data, opts) {
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
    name: 'mysteryReasonRoomService',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r.errMsg) {
        if (!silent) wx.showToast({ title: String(r.errMsg), icon: 'none', duration: 3500 })
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) wx.showToast({ title: formatFail(err), icon: 'none' })
      onError && onError(err)
    }
  })
}

module.exports = { callMysteryReason }
