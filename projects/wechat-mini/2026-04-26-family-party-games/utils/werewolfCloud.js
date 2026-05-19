/**
 * 身份推理云函数 werewolfService 统一调用（与 roomCloud 相同 init/日志风格）。
 */
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

let callSeq = 0

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
  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log('[werewolfService] wx.cloud.init 首次', {
      hasConfigEnv: !!configEnv
    })
    /* eslint-enable no-console */
  }
  wx.cloud.init(opts)
  if (app && app.globalData) {
    app.globalData.cloudInited = true
  }
  return true
}

function buildFailHint(err) {
  const msg = (err && (err.errMsg || err.message) ? String(err.errMsg || err.message) : '')
  if (/timeout|超时|time\s*out|504/i.test(msg)) {
    return { text: '云请求超时：请部署 werewolfService 并选云环境', isTimeout: true }
  }
  if (/not\s*found|未部署|FUNCTION_NOT_FOUND|50100|未开通|cloud\.init/i.test(msg)) {
    return { text: '请部署云函数 werewolfService' }
  }
  return { text: '身份推理服务暂不可用' }
}

/**
 * @param {object} data
 * @param {object} [opts]
 * @param {() => void} [opts.onBegin]
 * @param {(res) => void} [opts.onOk]  收到 { result, errMsg } 里 result
 * @param {(err) => void} [opts.onError]
 * @param {boolean} [opts.silent]
 */
function callWerewolfService(data, opts) {
  const { onBegin, onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    wx.showToast({ title: '当前环境不支持云', icon: 'none' })
    onError && onError(new Error('no cloud'))
    return
  }
  if (!ensureCloudInit()) {
    wx.showToast({ title: '云未就绪', icon: 'none' })
    onError && onError(new Error('init'))
    return
  }
  onBegin && onBegin()
  const id = ++callSeq
  const t0 = Date.now()
  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log(`[werewolfService#${id}] 开始`, data)
    /* eslint-disable no-console */
  }
  wx.cloud.callFunction({
    name: 'werewolfService',
    data,
    success: (res) => {
      const ok = (res && res.result) || {}
      if (ok && ok.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(ok.errMsg), icon: 'none' })
        }
        onError && onError(new Error(String(ok.errMsg)), { result: ok })
        return
      }
      if (debugCloudLog) {
        /* eslint-disable no-console */
        console.log(`[werewolfService#${id}] 成功 ${Date.now() - t0}ms`, res)
        /* eslint-disable no-console */
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      const hint = buildFailHint(err)
      /* eslint-disable no-console */
      console.error(`[werewolfService#${id}] fail`, err)
      /* eslint-disable no-console */
      if (!silent) {
        wx.showToast({ title: hint.text, icon: 'none', duration: hint.isTimeout ? 4000 : 3000 })
      }
      onError && onError(err, hint)
    }
  })
}

module.exports = {
  callWerewolfService,
  buildFailHint,
  ensureWerewolfCloud: ensureCloudInit
}
