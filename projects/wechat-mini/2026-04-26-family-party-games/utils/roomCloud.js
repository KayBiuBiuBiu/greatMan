/**
 * 与 roomService 云函数通信，统一错误提示，便于排查 timeout / 未选环境 / 未部署 等问题。
 *
 * 代码审阅（无额外前端超时）：
 * - 未对 callFunction 使用 setTimeout / Promise.race
 * - 未用 wx.request 调云函数 HTTP
 * - wx.cloud.init 未传 timeout 等参数
 * - 口令聚会组（roomService）等调用统一经本文件封装，便于日志与错误提示
 *
 * 排障：若已出现「roomService#N callFunction 成功 / complete」、errMsg 为 cloud.callFunction:ok，
 * 之后控制台仍报 Error: timeout，且堆栈在 WAServiceMainContext 或 WAWorker、伴 reportRealtimeAction 等，
 * 多为基础库/模拟器内部任务，与本次云函数无关，可忽略。真正云失败不会先有 ok 日志。
 */
const {
  ensureCloudInit: ensureCloudInitShared,
  getCallFunctionConfig,
  debugCloudLog
} = require('./cloudInit')

let callSeq = 0

/** 与 shareService 对齐，避免客户端 -404012 polling timeout */
const CALL_TIMEOUT_MS = 15000

function ensureCloudInit() {
  if (!wx.cloud) {
    return false
  }
  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log('[roomService] ensureCloudInit')
    /* eslint-enable no-console */
  }
  return ensureCloudInitShared()
}

function buildFailHint(err) {
  const msg = (err && (err.errMsg || err.message)) ? String(err.errMsg || err.message) : ''
  if (/房间|口令|4位|不存在|已过期|请输入/i.test(msg)) {
    return { text: '口令不对或房间已结束' }
  }
  if (/timeout|超时|time\s*out|TIMED_?OUT|deadline|504/i.test(msg)) {
    return {
      text: '云请求超时：请开云开发、选环境、部署 roomService；可填根目录 cloud-env.js 的 envId',
      isTimeout: true
    }
  }
  if (/not\s*found|不存在|未上传|未部署|FUNCTION_NOT_FOUND|[-]50100|没有权限|未开通|cloud\.init/i.test(msg)) {
    return { text: '请部署云函数 roomService，并确认本小程序已开通云开发' }
  }
  return { text: '服务暂不可用，可先用「本机开玩」' }
}

/**
 * @param {object} data
 * @param {object} [opts]
 * @param {() => void} [opts.onBegin]
 * @param {(res) => void} [opts.onOk]
 * @param {(err) => void} [opts.onError]
 * @param {boolean} [opts.silent] 为 true 时 fail 不弹 Toast（如轮询「尚未发词」）
 */
function callRoomService(data, opts) {
  const { onBegin, onOk, onError, silent } = opts || {}
  if (!wx.cloud) {
    wx.showToast({ title: '当前基础库不支持云能力', icon: 'none' })
    onError && onError(new Error('no cloud'))
    return
  }

  if (!ensureCloudInit()) {
    wx.showToast({ title: '云能力未就绪', icon: 'none' })
    onError && onError(new Error('no cloud init'))
    return
  }

  onBegin && onBegin()

  const id = ++callSeq
  const t0 = Date.now()
  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log(`[roomService#${id}] callFunction 开始`, data)
    /* eslint-enable no-console */
  }

  wx.cloud.callFunction({
    name: 'roomService',
    config: getCallFunctionConfig(),
    timeout: CALL_TIMEOUT_MS,
    data,
    success: (res) => {
      const ms = Date.now() - t0
      if (debugCloudLog) {
        /* eslint-disable no-console */
        console.log(
          `[roomService#${id}] callFunction 成功, 耗时 ${ms}ms, errMsg=`,
          res && res.errMsg,
          '完整 res=',
          res
        )
        /* eslint-enable no-console */
      }
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
      const ms = Date.now() - t0
      const hint = buildFailHint(err)
      /* eslint-disable no-console */
      try {
        console.error(`[roomService#${id}] callFunction 失败, 耗时 ${ms}ms, hint=`, hint, 'err=', err)
        console.error(`[roomService#${id}] err JSON=`, err && (typeof err === 'string' ? err : JSON.stringify(err)))
      } catch (logE) {
        console.error(`[roomService#${id}] 打印 err 失败`, logE)
      }
      /* eslint-enable no-console */
      if (!silent) {
        wx.showToast({ title: hint.text, icon: 'none', duration: hint.isTimeout ? 4000 : 3000 })
      }
      onError && onError(err, hint)
    },
    complete: () => {
      if (debugCloudLog) {
        /* eslint-disable no-console */
        console.log(`[roomService#${id}] callFunction complete, 自开始共 ${Date.now() - t0}ms（成功/失败均已回调后触发）`)
        /* eslint-enable no-console */
      }
    }
  })
}

module.exports = {
  callRoomService,
  buildFailHint
}
