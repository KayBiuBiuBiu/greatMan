/**
 * 分享解锁进度 — 订阅 agent_room_feed（与 shareService callFunction 独立）
 */
const { getCurrentSessionId } = require('./partyAiSession')
const { shouldUseDbWatch } = require('./cloudRealtime')

let _debugWatch = false
try {
  const cfg = require('../cloud-env.js')
  _debugWatch = !!(cfg && cfg.debugCloudLog)
} catch (e) {
  _debugWatch = false
}

function feedRoomId(sessionId) {
  return 'unlock_' + String(sessionId || 'day_default').slice(0, 64)
}

function formatWatchErr(err) {
  if (!err) {
    return 'unknown'
  }
  const parts = [err.errCode, err.errMsg, err.message].filter(Boolean)
  return parts.length ? parts.join(' ') : String(err)
}

function stopUnlockFeedWatch(page) {
  if (!page || !page._unlockFeedWatcher) {
    return
  }
  try {
    page._unlockFeedWatcher.close()
  } catch (e) {
    /* ignore */
  }
  page._unlockFeedWatcher = null
  page._unlockFeedWatchActive = false
}

/**
 * @param {object} page
 * @param {{ onProgress?: (payload, opts) => void, onError?: (err) => void }} callbacks
 * @returns {boolean} 是否成功启动 watch
 */
function shouldUseFeedWatch(sessionId) {
  if (!shouldUseDbWatch()) {
    return false
  }
  return !!String(sessionId || '')
}

function startUnlockFeedWatch(page, callbacks) {
  stopUnlockFeedWatch(page)
  if (!page || !wx.cloud) {
    return false
  }
  const sessionId = getCurrentSessionId()
  if (!shouldUseFeedWatch(sessionId)) {
    if (_debugWatch) {
      /* eslint-disable no-console */
      console.log(
        '[unlockFeed watch] 跳过',
        shouldUseDbWatch() ? '（首页 day 场次用轮询）' : '（devtools 禁用 watch）',
        sessionId
      )
      /* eslint-enable no-console */
    }
    return false
  }
  const roomId = feedRoomId(sessionId)
  const db = wx.cloud.database()
  const since = Date.now() - 3000
  page._unlockFeedSince = since
  page._unlockFeedErrored = false

  const applyDoc = (doc) => {
    if (!doc) {
      return
    }
    const ts = doc.createdAt || 0
    if (ts && ts < since) {
      return
    }
    const p = doc.payload || {}
    if (_debugWatch) {
      /* eslint-disable no-console */
      console.log('[unlockFeed watch] onChange', roomId, p)
      /* eslint-enable no-console */
    }
    if (callbacks && callbacks.onProgress) {
      callbacks.onProgress(p, { silent: false, fromFeed: true })
    }
  }

  const onWatchError = (err) => {
    if (page._unlockFeedErrored) {
      return
    }
    page._unlockFeedErrored = true
    const msg = formatWatchErr(err)
    /* eslint-disable no-console */
    if (msg.indexOf('timeout') >= 0 || msg.indexOf('timed out') >= 0) {
      console.warn(
        '[unlockFeed watch] 连接超时（已关闭，使用 60s 轮询）；与 shareService 无关:',
        msg
      )
    } else {
      console.warn(
        '[unlockFeed watch] 错误（与 shareService callFunction 无关），已关闭并回退轮询:',
        msg
      )
    }
    /* eslint-enable no-console */
    stopUnlockFeedWatch(page)
    if (callbacks && callbacks.onError) {
      callbacks.onError(err)
    }
  }

  try {
    if (_debugWatch) {
      /* eslint-disable no-console */
      console.log('[unlockFeed watch] 启动', { roomId, sessionId })
      /* eslint-enable no-console */
    }
    page._unlockFeedWatcher = db
      .collection('agent_room_feed')
      .where({
        roomId,
        type: 'unlock_progress'
      })
      .watch({
        onChange(snapshot) {
          const docs = snapshot.docs || []
          if (_debugWatch && snapshot.type === 'init') {
            /* eslint-disable no-console */
            console.log('[unlockFeed watch] init', docs.length, 'docs')
            /* eslint-enable no-console */
          }
          docs.forEach(applyDoc)
        },
        onError: onWatchError
      })
    page._unlockFeedWatchActive = true
    return true
  } catch (e) {
    onWatchError(e)
    return false
  }
}

module.exports = {
  feedRoomId,
  formatWatchErr,
  shouldUseFeedWatch,
  startUnlockFeedWatch,
  stopUnlockFeedWatch
}
