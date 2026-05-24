/**
 * 同房云状态同步：syncState 轮询兜底（参与者直读 gameState 常失败）
 */
const { withJoinProfile } = require('../../utils/userProfile')
const { shouldUseDbWatch } = require('../../utils/cloudRealtime')

/** 无 db.watch 时的 syncState 间隔（毫秒） */
const IN_ROOM_POLL_MS = 3000
/** 真机已 watch 房间文档时的慢速兜底（仍偶尔 syncState 校正 inRoom/成员） */
const IN_ROOM_POLL_WITH_WATCH_MS = 8000

function readPollMsFromConfig() {
  try {
    const cfg = require('../../cloud-env.js')
    const n = cfg && cfg.inRoomPollIntervalMs
    if (n != null && n > 0) {
      return n | 0
    }
  } catch (e) {
    /* ignore */
  }
  return 0
}

function resolveInRoomPollMs(page, explicitMs) {
  if (explicitMs != null && explicitMs > 0) {
    return explicitMs | 0
  }
  const fromCfg = readPollMsFromConfig()
  if (fromCfg > 0) {
    return fromCfg
  }
  if (page && page._roomDbWatchActive && shouldUseDbWatch()) {
    return IN_ROOM_POLL_WITH_WATCH_MS
  }
  return IN_ROOM_POLL_MS
}

function storeMyOpenId(storageKey, openId) {
  const o = String(openId || '').trim()
  if (!o) {
    return
  }
  try {
    wx.setStorageSync(storageKey, o)
  } catch (e) {}
}

function loadStoredOpenId(storageKey) {
  try {
    return String(wx.getStorageSync(storageKey) || '').trim()
  } catch (e) {
    return ''
  }
}

function pageInRoom(page) {
  if (!page || !page.data) {
    return false
  }
  return !!(page.data.roomId || page.data.roomCode)
}

function ensureInRoomPoll(page, refreshFn, intervalMs) {
  if (!page || !pageInRoom(page) || page._roomPollTimer) {
    return
  }
  const ms = resolveInRoomPollMs(page, intervalMs)
  if (typeof refreshFn === 'function') {
    refreshFn.call(page)
  }
  page._roomPollTimer = setInterval(function () {
    if (pageInRoom(page) && typeof refreshFn === 'function') {
      refreshFn.call(page)
    }
  }, ms)
}

function stopInRoomPoll(page) {
  if (page && page._roomPollTimer) {
    clearInterval(page._roomPollTimer)
    page._roomPollTimer = null
  }
}

/** onHide 停轮询后，onShow 需重新启动（间隔会按是否 watch 重算） */
function resumeInRoomPollOnShow(page, refreshFn, intervalMs) {
  if (!page || !pageInRoom(page)) {
    return
  }
  stopInRoomPoll(page)
  ensureInRoomPoll(page, refreshFn, intervalMs)
}

/**
 * 分享/深链进房但未写入玩家表时，静默 join 后再同步
 */
function ensureCloudJoin(page, opts) {
  const o = opts || {}
  const callService = o.callService
  const busyKey = o.busyKey || '_cloudJoining'
  const onDone = o.onDone
  if (!page || !callService) {
    if (typeof onDone === 'function') {
      onDone(null)
    }
    return
  }
  if (page[busyKey]) {
    if (typeof onDone === 'function') {
      onDone(null)
    }
    return
  }
  const code = String(
    o.roomCode || (page.data && (page.data.roomCode || page.data.joinCode)) || ''
  )
    .replace(/\D/g, '')
    .slice(0, 6)
  const rid = String(o.roomId || (page.data && page.data.roomId) || '').trim()
  const payload = { action: 'join' }
  if (code.length === 6) {
    payload.roomCode = code
  } else if (rid) {
    payload.roomId = rid
  } else {
    if (typeof onDone === 'function') {
      onDone(null)
    }
    return
  }
  page[busyKey] = true
  callService(withJoinProfile(payload), {
    silent: true,
    onOk: (res) => {
      page[busyKey] = false
      if (typeof onDone === 'function') {
        onDone((res && res.result) || {})
      }
    },
    onError: () => {
      page[busyKey] = false
      if (typeof onDone === 'function') {
        onDone(null)
      }
    }
  })
}

/** syncState 返回 inRoom:false 时自动 join 并再拉一次 */
function retrySyncIfNotInRoom(page, syncResult, refreshFn, joinOpts) {
  const r = syncResult || {}
  if (r.inRoom !== false) {
    return true
  }
  ensureCloudJoin(page, Object.assign({}, joinOpts || {}, {
    onDone: function () {
      if (typeof refreshFn === 'function') {
        refreshFn.call(page)
      }
    }
  }))
  return false
}

module.exports = {
  IN_ROOM_POLL_MS,
  IN_ROOM_POLL_WITH_WATCH_MS,
  storeMyOpenId,
  loadStoredOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  ensureCloudJoin,
  retrySyncIfNotInRoom
}
