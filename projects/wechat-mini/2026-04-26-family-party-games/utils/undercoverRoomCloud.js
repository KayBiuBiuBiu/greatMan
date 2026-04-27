let configEnv
let debugCloudLog = true
try {
  const cfg = require('../cloud-env.js')
  configEnv = (cfg && cfg.envId) || ''
  if (cfg && typeof cfg.debugCloudLog === 'boolean') {
    debugCloudLog = cfg.debugCloudLog
  }
} catch (e) {
  configEnv = ''
}

let seq = 0

function ensureCloud() {
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

/**
 * 解析 callFunction 的 fail；勿对 errMsg 作过短截断，否则常出现 "cloud.callFunction:fail" + 换行 + "e"。
 */
function formatCallFunctionFail (err) {
  const raw =
    (err && (err.errMsg != null && String(err.errMsg))) ||
    (err && err.message != null && String(err.message)) ||
    ''
  if (!raw) {
    return '未部署或网络异常，请检查云环境并上传云函数'
  }
  if (
    /-501000|FunctionName\s*parameter|FUNCTION_NOT_FOUND|function\s*is\s*not\s*found/i.test(
      raw
    ) ||
    /(not\s*found|未部署|不存在|50400[13]|-5040)/i.test(raw) ||
    /\bfunction\s*not\s*found\b/i.test(raw)
  ) {
    return '云端无此云函数：请上传并部署「undercoverRoomService」（与 cloudfunctions 下目录名一致）并选对云环境'
  }
  if (/502005|not\s*exist|collection|DATABASE|集合|Db\s*or/i.test(raw)) {
    return '请先在云数据库中创建集合 uc_rooms 等，见项目文档'
  }
  if (/time\s*out|超时|504|502|network|网络|ECONN|fail.*connect/i.test(raw)) {
    return '云请求超时，请重试或检查云环境'
  }
  if (/未开通|无权限|init|云开发|environment/i.test(raw) && /cloud|env|开通/i.test(raw)) {
    return '请检查是否开通云开发并选环境'
  }
  let t = raw.replace(/^\s*cloud\.callFunction:fail(\s*-\d+)?\s*/i, '')
  t = t.replace(/^\s*Error:\s*/i, '')
  t = t.trim() || raw
  if (t.length < 2 || (t.length <= 3 && /^[a-z]$/i.test(t))) {
    return '云异常：未部署/环境/网络。请打开云开发-云函数检查 undercoverRoomService'
  }
  if (t.length > 22) {
    return t.slice(0, 22) + '…'
  }
  return t
}

function callUndercoverService(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    wx.showToast({ title: '无云能力', icon: 'none' })
    onError && onError()
    return
  }
  if (!ensureCloud()) {
    onError && onError()
    return
  }
  const id = ++seq
  wx.cloud.callFunction({
    name: 'undercoverRoomService',
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r && r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg), icon: 'none', duration: 3500 })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        const title = formatCallFunctionFail(err)
        console.error('[undercoverRoomService callFunction fail]', err)
        wx.showToast({ title, icon: 'none', duration: 4500 })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callUndercoverService, ensureUndercoverCloud: ensureCloud }
