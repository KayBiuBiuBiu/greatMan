/**
 * 分享给好友 + 分享到朋友圈（onShareTimeline 使用 query，不用 path）
 */

const PRESETS = {
  index: {
    page: '/pages/index/index',
    defaultTitle: '家庭聚会助手 - 亲友口令进组一起玩'
  },
  dontdoit: {
    page: '/packageGames/dontdoit/dontdoit',
    defaultTitle: '家庭聚会助手 - 不要做挑战',
    codeLen: 6,
    roomTitle: (code) => '一起来玩不要做挑战！口令 ' + code,
    buildQuery: (ctx) => {
      const cfg = { roomId: ctx.roomId, roomCode: ctx.code }
      return 'config=' + encodeURIComponent(JSON.stringify(cfg))
    }
  },
  mysteryReason: {
    page: '/packageGames/mystery-reason/mystery-reason',
    defaultTitle: '家庭聚会助手 - AI迷雾推理局',
    codeLen: 6,
    roomTitle: (code) => '一起来玩AI迷雾推理局！口令 ' + code,
    buildQuery: (ctx) => {
      const cfg = { roomId: ctx.roomId, roomCode: ctx.code }
      return 'config=' + encodeURIComponent(JSON.stringify(cfg))
    }
  },
  headband: {
    page: '/packageGames/headband/headband',
    defaultTitle: '家庭聚会助手 - 贴头猜词',
    codeLen: 6,
    roomTitle: (code) => '一起来玩贴头猜词！口令 ' + code,
    buildQuery: (ctx) => {
      const cfg = { roomId: ctx.roomId, roomCode: ctx.code }
      return 'config=' + encodeURIComponent(JSON.stringify(cfg))
    }
  },
  drink: {
    page: '/packageGames/drink-party/drink-party',
    defaultTitle: '家庭聚会助手 - 趣味抽签',
    codeLen: 6,
    roomTitle: (code) => '一起来玩趣味抽签！口令 ' + code,
    buildQuery: (ctx) =>
      'roomId=' +
      encodeURIComponent(String(ctx.roomId)) +
      '&roomCode=' +
      encodeURIComponent(ctx.code)
  },
  undercover: {
    page: '/packageGames/undercover/undercover',
    defaultTitle: '家庭聚会助手 - 谁是卧底',
    codeLen: 6,
    roomTitle: (code) => '快来一起玩谁是卧底！口令 ' + code,
    buildQuery: (ctx) => {
      const cfg = { mode: 'v2', roomCode: ctx.code }
      if (ctx.roomId) {
        cfg.roomId = String(ctx.roomId)
      }
      return 'config=' + encodeURIComponent(JSON.stringify(cfg))
    }
  },
  werewolf: {
    page: '/packageGames/werewolf/werewolf',
    defaultTitle: '家庭聚会助手 - 秘密身份推理',
    codeLen: 6,
    roomTitle: (code) => '一起来玩身份推理！口令 ' + code,
    buildQuery: (ctx) => {
      const cfg = { roomCode: ctx.code }
      if (ctx.roomId) {
        cfg.roomId = String(ctx.roomId)
      }
      return 'config=' + encodeURIComponent(JSON.stringify(cfg))
    }
  },
  draw: {
    page: '/packageGames/draw-guess/draw-guess',
    defaultTitle: '家庭聚会助手 - 你画我猜',
    codeLen: 6,
    needRoomId: true,
    roomTitle: (code) => '一起来玩你画我猜！口令 ' + code,
    buildQuery: (ctx) =>
      'roomId=' +
      encodeURIComponent(String(ctx.roomId)) +
      '&roomCode=' +
      encodeURIComponent(ctx.code)
  },
  music: {
    page: '/packageGames/song-guess/song-guess',
    defaultTitle: '家庭聚会助手 - 疯狂猜歌',
    codeLen: 6,
    needRoomId: true,
    roomTitle: (code) => '一起来玩疯狂猜歌！口令 ' + code,
    buildQuery: (ctx) =>
      'roomId=' +
      encodeURIComponent(String(ctx.roomId)) +
      '&roomCode=' +
      encodeURIComponent(ctx.code)
  },
  truthDare: {
    page: '/packageGames/play/play',
    defaultTitle: '家庭聚会助手 - 真心话大冒险',
    codeLen: 4,
    roomTitle: (code) => '一起来玩真心话大冒险！口令 ' + code,
    buildQuery: (ctx) =>
      'title=' +
      encodeURIComponent('真心话大冒险') +
      '&config=' +
      encodeURIComponent(JSON.stringify({ roomCode: ctx.code }))
  }
}

function appendShareToken(query, token) {
  if (!token) {
    return query || ''
  }
  const sep = query ? '&' : ''
  return query + sep + 'st=' + encodeURIComponent(String(token))
}

function enableShareMenus() {
  if (typeof wx === 'undefined' || !wx.showShareMenu) {
    return
  }
  try {
    wx.showShareMenu({
      withShareTicket: true,
      menus: ['shareAppMessage', 'shareTimeline']
    })
  } catch (e) {
    /* 低版本基础库可能不支持 shareTimeline */
  }
}

/**
 * @param {string} kind index | drink | undercover | werewolf | draw | music | truthDare
 * @param {{ roomId?: string, roomCode?: string, imageUrl?: string, shareToken?: string }} ctx
 */
function buildRoomShare(kind, ctx) {
  const preset = PRESETS[kind] || PRESETS.index
  const raw = ctx && ctx.roomCode != null ? String(ctx.roomCode) : ''
  const code = raw.replace(/\D/g, '')
  const len = preset.codeLen | 0
  let title = preset.defaultTitle
  let path = preset.page
  const token = ctx && ctx.shareToken

  if (kind === 'index') {
    path = '/pages/index/index'
    if (token) {
      path += '?st=' + encodeURIComponent(token)
    }
  } else if (len > 0 && code.length === len && (!preset.needRoomId || ctx.roomId)) {
    title = preset.roomTitle ? preset.roomTitle(code) : title
    const q = preset.buildQuery({ code: code, roomId: ctx.roomId })
    path = preset.page + '?' + appendShareToken(q, token)
  } else if (kind !== 'index') {
    path = '/pages/index/index'
    if (token) {
      path += '?st=' + encodeURIComponent(token)
    }
    title = preset.defaultTitle
  }

  return {
    title: title,
    path: path,
    imageUrl: (ctx && ctx.imageUrl) || ''
  }
}

/** 将 onShareAppMessage 返回值转为 onShareTimeline 参数 */
function toTimeline(shareMsg) {
  const m = shareMsg || {}
  const path = m.path || '/pages/index/index'
  const qi = path.indexOf('?')
  const query = qi >= 0 ? path.slice(qi + 1) : ''
  return {
    title: m.title || '家庭聚会助手',
    query: query,
    imageUrl: m.imageUrl || ''
  }
}

const {
  getShareTokenForShare,
  refreshAiUnlockPage
} = require('./aiUnlock')
const { getShareCardUrl } = require('./shareInviteCard')

/**
 * 在 onShareAppMessage 中调用：生成 st、登记云端，好友点开链接后计次
 */
function handleShareAppMessage(page, kind, ctx) {
  const base = ctx || {}
  if (page) {
    page._shareExtra = {
      roomId: base.roomId || '',
      kind: kind || 'index'
    }
  }
  const token = getShareTokenForShare(page)
  if (!token) {
    wx.showToast({
      title: '分享码准备中，请稍候再点',
      icon: 'none',
      duration: 2500
    })
  }
  if (page) {
    refreshAiUnlockPage(page)
  }
  return buildRoomShare(
    kind,
    Object.assign({}, base, {
      shareToken: token,
      imageUrl: getShareCardUrl(page, base)
    })
  )
}

/**
 * 在 onShareTimeline 中调用
 */
function handleShareTimeline(page, kind, ctx) {
  const base = ctx || {}
  if (page) {
    page._shareExtra = {
      roomId: base.roomId || '',
      kind: kind || 'index'
    }
  }
  const token = getShareTokenForShare(page)
  if (page) {
    refreshAiUnlockPage(page)
  }
  return toTimeline(
    buildRoomShare(
      kind,
      Object.assign({}, base, {
        shareToken: token,
        imageUrl: getShareCardUrl(page, base)
      })
    )
  )
}

module.exports = {
  PRESETS,
  enableShareMenus: enableShareMenus,
  buildRoomShare: buildRoomShare,
  toTimeline: toTimeline,
  handleShareAppMessage: handleShareAppMessage,
  handleShareTimeline: handleShareTimeline,
  appendShareToken: appendShareToken
}
