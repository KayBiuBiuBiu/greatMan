/**
 * AI 梯度解锁：好友点开带 st 的分享链接后为分享者累计（shareService 云函数）
 */
const shareService = require('./shareService')
const { debugCloudLog } = require('./cloudInit')
const { shouldSkipShareCloudInDevtools } = require('./cloudRealtime')
const { getCurrentSessionId } = require('./partyAiSession')
const { getShareCopyVariant } = require('./shareUnlockCopy')
const {
  startUnlockFeedWatch,
  stopUnlockFeedWatch
} = require('./shareUnlockFeed')

let aiButtonsEnabled = true
try {
  aiButtonsEnabled = require('../data/feature-flags').isAiButtonsEnabled()
} catch (e) {
  aiButtonsEnabled = true
}

const STORAGE_KEY = 'ai_share_unlock_v2'
const REDEEM_PREFIX = 'ai_redeemed_'
/** watch 不可用时的兜底轮询间隔 */
const POLL_FALLBACK_MS = 60000
/** 分享弹窗打开时加快同步好友助力结果 */
const POLL_FAST_MS = 5000
const PREPARE_TOKEN_GAP_MS = 25000
let _lastPrepareAt = 0
let _prepareInflight = null

const LEVEL = {
  NONE: 0,
  GEN: 1,
  ASSIST: 2,
  RECAP: 3
}

const FEATURE_LABEL = {
  [LEVEL.GEN]: 'AI 出题',
  [LEVEL.ASSIST]: 'AI 策略建议',
  [LEVEL.RECAP]: 'AI 战报与聚会建议'
}

function readState() {
  const sessionId = getCurrentSessionId()
  try {
    const raw = wx.getStorageSync(STORAGE_KEY)
    if (!raw || typeof raw !== 'object' || raw.sessionId !== sessionId) {
      return { shareCount: 0, lastShareAt: 0, sessionId }
    }
    return {
      shareCount: raw.shareCount | 0,
      lastShareAt: raw.lastShareAt | 0,
      sessionId
    }
  } catch (e) {
    return { shareCount: 0, lastShareAt: 0, sessionId }
  }
}

function writeState(st) {
  try {
    wx.setStorageSync(STORAGE_KEY, {
      shareCount: st.shareCount | 0,
      lastShareAt: st.lastShareAt | 0,
      sessionId: st.sessionId || getCurrentSessionId()
    })
  } catch (e) {
    /* ignore */
  }
}

function resetAiUnlockLocal() {
  writeState({
    shareCount: 0,
    lastShareAt: 0,
    sessionId: getCurrentSessionId()
  })
}

function shareCountToLevel(count) {
  const n = count | 0
  if (n >= 3) {
    return LEVEL.RECAP
  }
  if (n >= 2) {
    return LEVEL.ASSIST
  }
  if (n >= 1) {
    return LEVEL.GEN
  }
  return LEVEL.NONE
}

function getUnlockSnapshot() {
  const st = readState()
  const level = shareCountToLevel(st.shareCount)
  const need = level < LEVEL.RECAP ? level + 1 - st.shareCount : 0
  let progressText = ''
  let nextHint = ''
  if (level === 0) {
    progressText = '本场未解锁'
    nextHint = '分享给好友，请好友点开链接解锁 AI 出题'
  } else if (level === LEVEL.GEN) {
    progressText = '已解锁 AI 出题'
    nextHint = '再获得 1 次好友确认解锁策略建议'
  } else if (level === LEVEL.ASSIST) {
    progressText = '已解锁出题 + 策略'
    nextHint = '再获得 1 次好友确认解锁战报与聚会建议'
  } else {
    progressText = '本场 AI 已全部解锁'
    nextHint = ''
  }
  return {
    shareCount: st.shareCount,
    level,
    canGen: level >= LEVEL.GEN,
    canAssist: level >= LEVEL.ASSIST,
    canRecap: level >= LEVEL.RECAP,
    progressText,
    nextHint,
    needMore: need
  }
}

/**
 * 预创建云端分享码（打开分享弹窗 / 进房时调用）
 * @param {object} [page]
 * @param {{ roomId?: string, kind?: string }} [extra]
 * @param {{ force?: boolean }} [opts] force 时忽略节流（打开分享弹窗）
 * @returns {Promise<object|null>}
 */
function prepareShareToken(page, extra, opts) {
  if (!wx.cloud || shouldSkipShareCloudInDevtools()) {
    return Promise.resolve(null)
  }
  if (_prepareInflight) {
    return _prepareInflight
  }
  const force = !!(opts && opts.force)
  const now = Date.now()
  if (
    !force &&
    now - _lastPrepareAt < PREPARE_TOKEN_GAP_MS &&
    page &&
    page._shareTokenCache
  ) {
    return Promise.resolve({ token: page._shareTokenCache })
  }
  if (!force && now - _lastPrepareAt < PREPARE_TOKEN_GAP_MS) {
    return Promise.resolve(null)
  }
  const e = extra || {}
  if (page) {
    page._shareExtra = e
  }
  const sessionId = getCurrentSessionId()
  _prepareInflight = shareService
    .createShareToken(sessionId, e)
    .then((r) => {
      if (r && r.token) {
        _lastPrepareAt = Date.now()
        if (page) {
          page._shareTokenCache = r.token
        }
      }
      return r
    })
    .catch((err) => {
      if (page) {
        page._shareCloudFail = (page._shareCloudFail | 0) + 1
      }
      const msg = (err && err.message) || ''
      if (msg.indexOf('集合') >= 0 || msg.indexOf('collection') >= 0) {
        /* eslint-disable no-console */
        console.warn('[shareService] 请创建 share_tokens / share_unlock_users 集合')
        /* eslint-enable no-console */
      }
      return null
    })
    .finally(() => {
      _prepareInflight = null
    })
  return _prepareInflight
}

/**
 * onShareAppMessage 同步取 token（仅使用云端已登记的码）
 */
function getShareTokenForShare(page) {
  const extra = (page && page._shareExtra) || {}
  if (page && page._shareTokenCache) {
    const t = page._shareTokenCache
    page._shareTokenCache = null
    prepareShareToken(page, extra)
    return t
  }
  prepareShareToken(page, extra, { force: true })
  return ''
}

function mergeCloudCount(cloudCount, opts) {
  const prevLevel = getUnlockSnapshot().level
  let st = readState()
  const now = Date.now()
  const cc = cloudCount | 0
  if (cc > (st.shareCount | 0)) {
    st.shareCount = cc
    st.lastShareAt = now
    writeState(st)
    const snap = getUnlockSnapshot()
    if (debugCloudLog && opts && opts.fromFeed) {
      /* eslint-disable no-console */
      console.log('[unlockFeed watch] 收到更新', {
        shareCount: snap.shareCount,
        unlockLevel: snap.level,
        canGen: snap.canGen
      })
      /* eslint-enable no-console */
    }
    if (opts && opts.silent) {
      return snap
    }
    if (snap.level > prevLevel) {
      let tip = '好友已确认，解锁进度更新'
      if (snap.level === LEVEL.GEN) {
        tip = '已解锁 AI 出题'
      } else if (snap.level === LEVEL.ASSIST) {
        tip = '已解锁 AI 策略建议'
      } else if (snap.level === LEVEL.RECAP) {
        tip = '本场 AI 已全部解锁'
      }
      wx.showToast({ title: tip, icon: 'none' })
    }
    return snap
  }
  return getUnlockSnapshot()
}

function syncUnlockFromCloud(opts) {
  const { page, silent } = opts || {}
  if (!wx.cloud || shouldSkipShareCloudInDevtools()) {
    refreshAiUnlockPage(page)
    return
  }
  shareService
    .getUnlockProgress(getCurrentSessionId())
    .then((r) => {
      if (page) {
        page._shareCloudFail = 0
      }
      const count = (r && (r.shareCount | r.unlockLevel)) | 0
      mergeCloudCount(count, { silent: !!silent })
      refreshAiUnlockPage(page)
      if (page && getUnlockSnapshot().level >= LEVEL.RECAP) {
        stopShareUnlockPoll(page)
      }
    })
    .catch(() => {
      if (page) {
        page._shareCloudFail = (page._shareCloudFail | 0) + 1
        if (page._shareCloudFail >= 2) {
          stopShareUnlockPoll(page)
        }
      }
      refreshAiUnlockPage(page)
    })
}

function tryRedeemShareFromQuery(query) {
  const st =
    (query && query.st) ||
    (query && query.shareToken) ||
    ''
  if (!st || typeof st !== 'string') {
    return
  }
  const token = String(st).trim().slice(0, 32)
  if (token.length < 4) {
    return
  }
  try {
    if (wx.getStorageSync(REDEEM_PREFIX + token)) {
      return
    }
  } catch (e) {
    /* ignore */
  }
  if (!wx.cloud) {
    return
  }
  shareService
    .redeemToken(token)
    .then((r) => {
      if (r && r.success) {
        try {
          wx.setStorageSync(REDEEM_PREFIX + token, 1)
        } catch (e) {
          /* ignore */
        }
        wx.showToast({
          title: (r && r.visitorMsg) || '已助力好友解锁 AI',
          icon: 'none'
        })
      }
    })
    .catch((err) => {
      const msg = (err && err.message) || '助力失败，请确认分享链接有效'
      wx.showToast({ title: msg.slice(0, 28), icon: 'none' })
    })
}

function scheduleFallbackPoll(page) {
  if (!page || !wx.cloud || shouldSkipShareCloudInDevtools()) {
    return
  }
  const snap = getUnlockSnapshot()
  if (snap.level >= LEVEL.RECAP) {
    stopShareUnlockPoll(page)
    return
  }
  const ms = (page && page._sharePollMs) || POLL_FALLBACK_MS
  page._shareUnlockPollTimer = setTimeout(() => {
    syncUnlockFromCloud({ page, silent: true })
    scheduleFallbackPoll(page)
  }, ms)
}

function startShareUnlockPoll(page) {
  scheduleFallbackPoll(page)
}

function startShareUnlockFastPoll(page) {
  if (!page) {
    return
  }
  page._sharePollMs = POLL_FAST_MS
  stopShareUnlockPoll(page)
  syncUnlockFromCloud({ page, silent: true })
  scheduleFallbackPoll(page)
}

function stopShareUnlockFastPoll(page) {
  if (!page) {
    return
  }
  page._sharePollMs = null
  stopShareUnlockPoll(page)
}

function stopShareUnlockPoll(page) {
  if (page && page._shareUnlockPollTimer) {
    clearTimeout(page._shareUnlockPollTimer)
    page._shareUnlockPollTimer = null
  }
}

function applyFeedPayload(page, payload, opts) {
  const count = (payload && (payload.shareCount | payload.unlockLevel | payload.level)) | 0
  mergeCloudCount(count, opts)
  refreshAiUnlockPage(page)
  if (getUnlockSnapshot().level >= LEVEL.RECAP) {
    stopShareUnlockPoll(page)
    stopUnlockFeedWatch(page)
  }
}

function onPageShowUnlock(page) {
  if (page) {
    page._shareUseFeed = false
  }
  refreshAiUnlockPage(page)
  if (shouldSkipShareCloudInDevtools()) {
    return
  }
  syncUnlockFromCloud({ page, silent: true })
  prepareShareToken(page, (page && page._shareExtra) || {})

  const watchOk = startUnlockFeedWatch(page, {
    onProgress: (payload, opts) => {
      applyFeedPayload(page, payload, opts)
    },
    onError: () => {
      if (page) {
        page._shareUseFeed = false
      }
    }
  })
  if (page) {
    page._shareUseFeed = !!watchOk
  }
  // watch 与 callFunction 独立：即使 watch 已连上，仍保留 60s 兜底轮询
  startShareUnlockPoll(page)
}

function onPageHideUnlock(page) {
  stopShareUnlockPoll(page)
  stopUnlockFeedWatch(page)
  if (page) {
    page._shareUseFeed = false
  }
}

function hasUnlock(minLevel) {
  return getUnlockSnapshot().level >= (minLevel | 0)
}

function showShareGuide() {
  wx.showModal({
    title: '分享到朋友圈',
    content:
      '朋友圈分享不计入 AI 解锁进度。\n\n请使用弹窗中的「分享给好友」，让好友点开聊天卡片里的链接完成助力。',
    showCancel: false,
    confirmText: '知道了'
  })
}

function applyShareTokenReady(page, r) {
  if (!page || !page.setData) {
    return
  }
  const open = !!(page.data && page.data.showAiShareModal)
  if (!open) {
    return
  }
  if (r && r.token) {
    page._shareTokenCache = r.token
    page.setData({ shareTokenReady: true })
    return
  }
  page.setData({ shareTokenReady: false })
  wx.showToast({ title: '分享码生成失败，请稍后重试', icon: 'none' })
}

function openAiShareModal(page) {
  if (!page || !page.setData) {
    showShareGuide()
    return
  }
  refreshAiUnlockPage(page)
  const extra = (page && page._shareExtra) || {}
  page.setData({
    showAiShareModal: true,
    shareTokenReady: false,
    shareCopy: getShareCopyVariant() || {}
  })
  startShareUnlockFastPoll(page)
  const p = prepareShareToken(page, extra, { force: true })
  if (p && typeof p.then === 'function') {
    p.then((r) => applyShareTokenReady(page, r)).catch(() => applyShareTokenReady(page, null))
  }
}

function closeAiShareModal(page) {
  stopShareUnlockFastPoll(page)
  if (page && page.setData) {
    page.setData({ showAiShareModal: false, shareTokenReady: false })
    if (!shouldSkipShareCloudInDevtools()) {
      startShareUnlockPoll(page)
    }
  }
}

function ensureAiUnlock(minLevel, featureName, page) {
  if (!aiButtonsEnabled) {
    return false
  }
  if (hasUnlock(minLevel)) {
    return true
  }
  if (page) {
    openAiShareModal(page)
  } else {
    showShareGuide()
  }
  return false
}

function refreshAiUnlockPage(page) {
  if (!page || !page.setData) {
    return getUnlockSnapshot()
  }
  const snap = aiButtonsEnabled
    ? getUnlockSnapshot()
    : {
        level: 0,
        canGen: false,
        canAssist: false,
        canRecap: false,
        nextHint: ''
      }
  page.setData({
    aiUnlock: Object.assign({}, snap, { nextHint: snap.nextHint || '' }),
    canShowPartyRecommend: aiButtonsEnabled && snap.canRecap,
    aiButtonsEnabled: aiButtonsEnabled
  })
  return snap
}

module.exports = {
  LEVEL,
  FEATURE_LABEL,
  getUnlockSnapshot,
  prepareShareToken,
  getShareTokenForShare,
  tryRedeemShareFromQuery,
  syncUnlockFromCloud,
  startShareUnlockPoll,
  stopShareUnlockPoll,
  onPageShowUnlock,
  onPageHideUnlock,
  hasUnlock,
  ensureAiUnlock,
  openAiShareModal,
  closeAiShareModal,
  showShareGuide,
  refreshAiUnlockPage,
  resetAiUnlockLocal
}
