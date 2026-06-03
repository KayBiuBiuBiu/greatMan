/**
 * AI 主持云函数 werewolfAIService（仅狼人杀分包使用，勿放主包 utils）
 */
let configEnv
try {
  const cfg = require('../../cloud-env.js')
  configEnv = (cfg && cfg.envId) || ''
} catch (e) {
  configEnv = ''
}

function ensureCloudInit() {
  if (!wx.cloud) return false
  const app = getApp && getApp()
  if (app && app.globalData && app.globalData.cloudInited) return true
  const opts = { traceUser: true }
  if (configEnv) opts.env = configEnv
  else if (wx.cloud.DYNAMIC_CURRENT_ENV != null) opts.env = wx.cloud.DYNAMIC_CURRENT_ENV
  wx.cloud.init(opts)
  if (app && app.globalData) app.globalData.cloudInited = true
  return true
}

function callWerewolfAIService(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud || !ensureCloudInit()) {
    onError && onError(new Error('云未就绪'))
    return
  }
  wx.cloud.callFunction({
    name: 'werewolfAIService',
    data,
    success: (res) => {
      const ok = (res && res.result) || {}
      if (ok.errMsg) {
        if (!silent) wx.showToast({ title: String(ok.errMsg), icon: 'none' })
        onError && onError(new Error(String(ok.errMsg)))
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: '请部署云函数 werewolfAIService', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = {
  callWerewolfAIService,
  ensureWerewolfAICloud: ensureCloudInit
}
