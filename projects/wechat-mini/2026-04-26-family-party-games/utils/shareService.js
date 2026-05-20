/**
 * 分享服务 — 调用 shareService 云函数（勿用旧名 shareUnlockService）
 */
const { ensureCloudInit, getCallFunctionConfig, getCloudEnvId, debugCloudLog } = require('./cloudInit')

/** 客户端 callFunction 超时（毫秒）；过短会触发 -404012 polling timeout */
const CALL_TIMEOUT_MS = 15000

function ensureCloud() {
  return ensureCloudInit()
}

function normalizeCallData(data) {
  const d = data && typeof data === 'object' ? Object.assign({}, data) : {}
  if (!d.action || typeof d.action !== 'string') {
    /* eslint-disable no-console */
    console.warn('[shareService] 缺少 action，调用可能失败', d)
    /* eslint-enable no-console */
  }
  return d
}

function callShareService(data) {
  if (!ensureCloud()) {
    return Promise.reject(new Error('云开发未初始化'))
  }
  const payload = normalizeCallData(data)
  const cfg = getCallFunctionConfig()
  const envId = getCloudEnvId() || (cfg && cfg.env) || ''

  const req = {
    name: 'shareService',
    data: payload,
    timeout: CALL_TIMEOUT_MS
  }
  if (cfg && cfg.env) {
    req.config = cfg
  }

  if (debugCloudLog) {
    /* eslint-disable no-console */
    console.log('[shareService] 调用 shareService:', {
      action: payload.action,
      sessionId: payload.sessionId,
      env: envId,
      timeout: CALL_TIMEOUT_MS,
      data: payload
    })
    /* eslint-enable no-console */
  }

  const t0 = Date.now()
  return new Promise((resolve, reject) => {
    req.success = (res) => {
      const ms = Date.now() - t0
      const r = (res && res.result) || {}
      if (r.code === 'COLLECTION_MISSING') {
        if (debugCloudLog) {
          /* eslint-disable no-console */
          console.warn('[shareService] fail', payload.action, ms + 'ms', r)
          /* eslint-enable no-console */
        }
        reject(new Error(r.errMsg || '数据库集合未创建'))
        return
      }
      if (r.success === false) {
        if (debugCloudLog) {
          /* eslint-disable no-console */
          console.warn('[shareService] biz fail', payload.action, ms + 'ms', r)
          /* eslint-enable no-console */
        }
        reject(new Error(String(r.errMsg || '请求失败')))
        return
      }
      if (debugCloudLog) {
        /* eslint-disable no-console */
        console.log('[shareService] ok', payload.action, ms + 'ms', r)
        /* eslint-enable no-console */
      }
      resolve(r)
    }
    req.fail = (err) => {
      const ms = Date.now() - t0
      /* eslint-disable no-console */
      console.warn('[shareService] fail', {
        action: payload.action,
        ms,
        env: envId,
        errCode: err && err.errCode,
        errMsg: err && err.errMsg,
        err
      })
      /* eslint-enable no-console */
      reject(err)
    }
    wx.cloud.callFunction(req)
  })
}

function createShareToken(sessionId, extra) {
  const e = extra || {}
  return callShareService({
    action: 'createToken',
    sessionId,
    roomId: e.roomId || '',
    kind: e.kind || 'index'
  })
}

function redeemToken(token) {
  return callShareService({
    action: 'redeemToken',
    token: String(token || '').trim()
  })
}

function checkToken(token) {
  return callShareService({
    action: 'checkToken',
    token: String(token || '').trim()
  })
}

function getUnlockProgress(sessionId) {
  return callShareService({
    action: 'getProgress',
    sessionId
  })
}

function updateUnlockProgress(sessionId, unlockLevel) {
  return callShareService({
    action: 'updateProgress',
    sessionId,
    unlockLevel: unlockLevel | 0
  })
}

function checkUnlock(sessionId, requiredLevel) {
  return callShareService({
    action: 'checkUnlock',
    sessionId,
    requiredLevel: requiredLevel == null ? 1 : requiredLevel | 0
  })
}

function callShareServiceCb(data, opts) {
  const { onOk, onError, silent } = opts || {}
  callShareService(data)
    .then((r) => onOk && onOk({ result: r }))
    .catch((err) => {
      if (!silent) {
        /* eslint-disable no-console */
        console.warn('[shareService]', err)
        /* eslint-enable no-console */
      }
      onError && onError(err)
    })
}

module.exports = {
  CALL_TIMEOUT_MS,
  getCloudEnvId,
  ensureShareServiceCloud: ensureCloud,
  callShareService,
  callShareServiceCb,
  createShareToken,
  redeemToken,
  checkToken,
  getUnlockProgress,
  updateUnlockProgress,
  checkUnlock
}
