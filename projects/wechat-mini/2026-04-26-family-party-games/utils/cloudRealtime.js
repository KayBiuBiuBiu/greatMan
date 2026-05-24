/**
 * 云开发实时能力（db.watch）在开发者工具里易触发无前缀的 Error: timeout。
 * 真机可正常使用 watch；devtools 默认走轮询 / 跳过非必要云调用。
 */

function isDevtools() {
  if (typeof wx === 'undefined' || !wx.getSystemInfoSync) {
    return false
  }
  try {
    return wx.getSystemInfoSync().platform === 'devtools'
  } catch (e) {
    return false
  }
}

/** 是否允许客户端 db.collection().watch */
function shouldUseDbWatch() {
  if (!isDevtools()) {
    return true
  }
  try {
    const cfg = require('../cloud-env.js')
    if (cfg && cfg.allowDbWatchInDevtools === true) {
      return true
    }
  } catch (e) {
    /* ignore */
  }
  return false
}

/** 开发者工具里是否跳过 shareService / agent_room_feed（首页 onShow 易触发 timeout） */
function shouldSkipShareCloudInDevtools() {
  if (!isDevtools()) {
    return false
  }
  try {
    const cfg = require('../cloud-env.js')
    if (cfg && cfg.allowShareCloudInDevtools === true) {
      return false
    }
  } catch (e) {
    /* ignore */
  }
  return true
}

/** 开发者工具里是否跳过 gameStatsService（避免 callFunction 超时刷红） */
function shouldSkipGameStatsInDevtools() {
  if (!isDevtools()) {
    return false
  }
  try {
    const cfg = require('../cloud-env.js')
    if (cfg && cfg.allowGameStatsInDevtools === true) {
      return false
    }
  } catch (e) {
    /* ignore */
  }
  return true
}

/** 真机 db.watch 已建立时标记，供 syncState 轮询降频 */
function markRoomDbWatch(page, active) {
  if (page) {
    page._roomDbWatchActive = !!active
  }
}

function startDevtoolsPoll(page, timerKey, fn, intervalMs) {
  stopDevtoolsPoll(page, timerKey)
  if (!page || typeof fn !== 'function') {
    return
  }
  markRoomDbWatch(page, false)
  page[timerKey] = setInterval(fn, intervalMs || 2500)
}

function stopDevtoolsPoll(page, timerKey) {
  if (page && page[timerKey]) {
    clearInterval(page[timerKey])
    page[timerKey] = null
  }
}

/**
 * 文档 watch；devtools 下改为轮询，避免 WAServiceMainContext Error: timeout
 */
function watchDocument(page, opts) {
  const {
    db,
    collection,
    docId,
    onChange,
    onError,
    pollTimerKey,
    pollFn,
    intervalMs,
    /** 为 false 时不标记 _roomDbWatchActive（如画布子文档 watch） */
    markActive
  } = opts || {}
  if (!db || !collection || docId == null) {
    return null
  }
  if (!shouldUseDbWatch()) {
    /* eslint-disable no-console */
    console.log('[cloud watch] devtools 轮询替代', collection, docId)
    /* eslint-enable no-console */
    if (pollTimerKey && pollFn) {
      startDevtoolsPoll(page, pollTimerKey, pollFn, intervalMs || 2500)
    }
    return null
  }
  if (pollTimerKey) {
    stopDevtoolsPoll(page, pollTimerKey)
  }
  if (markActive !== false) {
    markRoomDbWatch(page, true)
  }
  return db
    .collection(collection)
    .doc(String(docId))
    .watch({
      onChange,
      onError: (err) => {
        markRoomDbWatch(page, false)
        if (pollTimerKey && pollFn) {
          startDevtoolsPoll(page, pollTimerKey, pollFn, intervalMs || 2500)
        }
        if (onError) {
          onError(err)
        }
      }
    })
}

module.exports = {
  isDevtools,
  shouldUseDbWatch,
  shouldSkipShareCloudInDevtools,
  shouldSkipGameStatsInDevtools,
  markRoomDbWatch,
  startDevtoolsPoll,
  stopDevtoolsPoll,
  watchDocument
}
