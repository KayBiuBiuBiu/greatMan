const { ensureCloudInit, getCallFunctionConfig } = require('./cloudInit')

/** startGame 会在云端调 aiPartyService 出题，需较长超时 */
const CALL_TIMEOUT_MS = 90000

function formatFail(err) {
  const raw =
    (err && (err.errMsg != null && String(err.errMsg))) ||
    (err && err.message != null && String(err.message)) ||
    ''
  if (/time\s*out|超时|504|502/i.test(raw)) {
    return '云请求超时，请重试'
  }
  if (/node-sdk\/ai|wx-server-sdk|Cannot find module/i.test(raw)) {
    return '请重新部署 headbandRoomService（云端安装依赖）'
  }
  if (/not\s*found|未部署|FUNCTION_NOT_FOUND/i.test(raw)) {
    return '请部署云函数 headbandRoomService'
  }
  return raw.length > 22 ? raw.slice(0, 22) + '…' : raw || '网络异常'
}

function callHeadband(data, opts) {
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
    name: 'headbandRoomService',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data: data,
    success: (res) => {
      const r = (res && res.result) || {}
      /* eslint-disable no-console */
      console.log('[hb cloud]', data.action || '?', r.errMsg ? { errMsg: r.errMsg } : r)
      /* eslint-enable no-console */
      if (r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg), icon: 'none', duration: 3500 })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      /* eslint-disable no-console */
      console.warn('[hb cloud] fail', data.action || '?', err)
      /* eslint-enable no-console */
      if (!silent) {
        wx.showToast({ title: formatFail(err), icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callHeadband }
