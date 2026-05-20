/**
 * 首页互动「热门」统计：gameStatsService
 */
let configEnv
let debugLog = true
try {
  const cfg = require('../cloud-env.js')
  configEnv = (cfg && cfg.envId) || ''
  if (cfg && typeof cfg.debugCloudLog === 'boolean') {
    debugLog = cfg.debugCloudLog
  }
} catch (e) {
  configEnv = ''
}

function ensureCloud () {
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
 * @param {object} data
 * @param {{ onOk?: (res) => void, onError?: (e) => void, silent?: boolean }} [opts]
 */
function callGameStats (data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    onError && onError()
    return
  }
  if (!ensureCloud()) {
    onError && onError()
    return
  }
  const action = (data && data.action) || ''
  const t0 = Date.now()
  if (debugLog) {
    /* eslint-disable no-console */
    console.log('[gameStatsService] call', data)
    /* eslint-enable no-console */
  }
  const req = {
    name: 'gameStatsService',
    data,
    timeout: 15000
  }
  if (configEnv) {
    req.config = { env: configEnv }
  }
  req.success = (res) => {
    const ms = Date.now() - t0
    const r = (res && res.result) || {}
    if (r && r.errMsg) {
      if (debugLog) {
        /* eslint-disable no-console */
        console.warn('[gameStatsService] biz fail', action, ms + 'ms', r)
        /* eslint-enable no-console */
      } else if (!silent) {
        /* eslint-disable no-console */
        console.warn('[gameStatsService] err in result', r)
        /* eslint-enable no-console */
      }
      onError && onError(new Error(String(r.errMsg)))
      return
    }
    if (debugLog) {
      /* eslint-disable no-console */
      console.log('[gameStatsService] ok', action, ms + 'ms')
      /* eslint-enable no-console */
    }
    onOk && onOk(res)
  }
  req.fail = (err) => {
    const ms = Date.now() - t0
    if (debugLog) {
      /* eslint-disable no-console */
      console.warn('[gameStatsService] fail', action, ms + 'ms', err)
      /* eslint-enable no-console */
    } else if (!silent) {
      /* eslint-disable no-console */
      console.warn('[gameStatsService] callFunction fail', err)
      /* eslint-enable no-console */
    }
    onError && onError(err)
  }
  wx.cloud.callFunction(req)
}

module.exports = { callGameStats, ensureGameStatsCloud: ensureCloud }
