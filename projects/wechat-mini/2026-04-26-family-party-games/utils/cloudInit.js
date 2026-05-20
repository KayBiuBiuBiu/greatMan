/**
 * 云开发统一初始化（固定 cloud-env.js 的 envId，避免误用 DYNAMIC_CURRENT_ENV 指向错误环境）
 */
let configEnv = ''
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

function getCloudEnvId() {
  return configEnv
}

/** wx.cloud.callFunction 的 config，强制指定环境 */
function getCallFunctionConfig() {
  if (configEnv) {
    return { env: configEnv }
  }
  return {}
}

function ensureCloudInit() {
  if (!wx.cloud) {
    return false
  }
  const app = getApp && getApp()
  if (app && app.globalData && app.globalData.cloudInited) {
    return true
  }
  const opts = { traceUser: true }
  if (configEnv) {
    opts.env = configEnv
  } else if (wx.cloud.DYNAMIC_CURRENT_ENV != null) {
    opts.env = wx.cloud.DYNAMIC_CURRENT_ENV
  }
  try {
    if (wx.getSystemInfoSync().platform === 'devtools') {
      // 减少开发者工具里云实时通道连不上时的 Error: timeout
      opts.traceUser = false
    }
  } catch (e) {
    /* ignore */
  }
  wx.cloud.init(opts)
  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log('[cloud] wx.cloud.init', {
      env: configEnv || '(工具当前云环境)',
      hasExtendAi: !!(wx.cloud.extend && wx.cloud.extend.AI)
    })
    /* eslint-enable no-console */
  }
  if (app && app.globalData) {
    app.globalData.cloudInited = true
  }
  return true
}

module.exports = {
  ensureCloudInit,
  getCloudEnvId,
  getCallFunctionConfig,
  debugCloudLog
}
