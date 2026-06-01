/**
 * 同场聚会组：成员展示、状态文案、进度
 */
const { memberCountLine } = require('./roomUi')
const { readLocalUserInfo, getFallbackNickName } = require('../../utils/userHelper')
const {
  patchLobbySelfReady,
  lobbyGuestReadyStats,
  overlayLobbyProfileReady,
  resolveLobbyMyOpenId
} = require('./roomLobbyReady')

/** 本人资料已保存但进房记录无头像时，用本地 userInfo 补齐 */
function mergeLocalProfileIntoPlayers(players, myOpenId) {
  const oid = String(myOpenId || '').trim()
  if (!oid) {
    return players || []
  }
  const local = readLocalUserInfo() || {}
  const localAv = String(local.avatarUrl || '').trim()
  const localNick = String(local.nickName || '').trim()
  if (!localAv && !localNick) {
    return players || []
  }
  return (players || []).map((p) => {
    if (!p || p.openId !== oid) {
      return p
    }
    const next = Object.assign({}, p)
    if (localAv && !String(next.avatarUrl || '').trim()) {
      next.avatarUrl = localAv
    }
    if (localNick && !String(next.nickName || next.nick || '').trim()) {
      next.nickName = localNick
    }
    return next
  })
}
function computeProgressPct(cur, max) {
  const m = max | 0
  if (m <= 0) {
    return 0
  }
  return Math.min(100, Math.round(((cur | 0) / m) * 100))
}

function enrichPlayers(pl, phase, hostOpenId) {
  const ph = phase || 'waiting'
  const inWord = ph === 'word'
  const inLobby = ph === 'waiting' || ph === 'lobby' || !ph
  return (pl || []).map((p) => {
    const isHost = !!p.isHost || !!(hostOpenId && p.openId && p.openId === hostOpenId)
    let ready = inWord ? !!p.wordAck : p.isAlive !== false
    let readyLabel = '已到'
    if (inWord) {
      readyLabel = p.wordAck ? '已看词' : '未看词'
    } else if (inLobby) {
      ready = isHost || !!p.profileReady
      readyLabel = isHost ? '组长' : p.profileReady ? '已准备' : '未准备'
    } else if (ph !== 'waiting' && ph !== 'lobby' && ph) {
      if (p.isSheriff && p.isAlive !== false) {
        readyLabel = '警长'
      } else {
        readyLabel = p.isAlive === false ? '暂离' : '在场'
      }
    }
    const rawNick = (p.nickName || p.nick || '').toString().trim()
    const nick = rawNick || getFallbackNickName()
    const avatarUrl = (p.avatarUrl || '').toString().trim()
    return {
      openId: p.openId,
      nickName: nick,
      isHost,
      isAlive: p.isAlive !== false,
      wordAck: !!p.wordAck,
      ready,
      readyLabel,
      avatarUrl,
      avatarText: nick.slice(0, 1) || '匿',
      score: p.score != null ? p.score | 0 : null
    }
  })
}

function computeStatusHint(isHost, phase, opts) {
  const o = opts || {}
  const ph = phase || 'waiting'
  const waiting = ph === 'waiting' || ph === 'lobby' || !ph
  if (waiting) {
    if (isHost) {
      return o.hostWaiting || '⏳ 点击「开始互动」发牌'
    }
    return o.guestWaiting || '👥 等待组长开始互动'
  }
  if (ph === 'ended' || ph === 'end') {
    return ''
  }
  return '🎮 游戏进行中'
}

function patchMemberDisplay(patch, opts) {
  const o = opts || {}
  const page = o.page
  const myOpenId = resolveLobbyMyOpenId(page, o.myOpenId)
  let players = o.players || []
  if (myOpenId) {
    players = mergeLocalProfileIntoPlayers(players, myOpenId)
  }
  const phase = o.phase || 'waiting'
  const inLobby = phase === 'waiting' || phase === 'lobby' || !phase
  if (inLobby && page) {
    players = overlayLobbyProfileReady(players, myOpenId, page)
  }
  const maxPlayers = o.maxPlayers | 0
  const isHost = !!o.isHost
  const hostOpenId = o.hostOpenId || ''
  const cur = players.length
  const need = maxPlayers > 0 ? maxPlayers : (o.fallbackNeed | 0)
  patch.displayPlayers = enrichPlayers(players, phase, hostOpenId)
  patch.playerProgressPct = computeProgressPct(cur, need)
  patch.statusHint = computeStatusHint(isHost, phase, {
    hostWaiting: o.hostWaiting,
    guestWaiting: o.guestWaiting
  })
  return patch
}

/** 等待大厅横幅：人数不足时带 ⚠️ */
function buildLobbyStatusHint(isHost, phaseOrStatus, playerCount, opts) {
  const o = opts || {}
  const min = (o.minPlayers | 0) || 2
  const st = phaseOrStatus || 'waiting'
  const waiting = st === 'waiting' || st === 'lobby' || !st
  if (!waiting) {
    if (st === 'playing') {
      return o.playingHint || '🎮 游戏进行中'
    }
    if (st === 'finished' || st === 'ended' || st === 'end') {
      return ''
    }
    return o.playingHint || '🎮 游戏进行中'
  }
  const n = playerCount | 0
  const max = (o.maxPlayers | 0) > 0 ? (o.maxPlayers | 0) : 0
  if (max > 0 && n < max) {
    return '⚠️ 本局 ' + max + ' 人，当前 ' + n + ' 人，还差 ' + (max - n) + ' 人'
  }
  if (n < min) {
    return '⚠️ 至少需要 ' + min + ' 人，当前 ' + n + ' 人'
  }
  if (isHost) {
    return o.hostWaiting || '⏳ 点击「开始互动」发牌'
  }
  return o.guestWaiting || '👥 请点「准备」，等待组长开始'
}

function appendGuestReadyHint(baseHint, isHost, waiting, guestStats) {
  const st = guestStats || {}
  if (!waiting || !isHost || st.guestCount <= 0 || st.allReady) {
    return baseHint
  }
  const not = Math.max(0, st.guestCount - st.readyCount)
  const extra =
    not > 0
      ? '⚠️ 还有 ' + not + ' 人未点「准备」'
      : '⚠️ 还有参与者未准备'
  if (!baseHint) {
    return extra
  }
  if (/未准备/.test(baseHint)) {
    return baseHint
  }
  return baseHint + ' · ' + extra.replace(/^⚠️\s*/, '')
}

/**
 * 等待大厅统一 UI 状态（成员、进度、横幅、可开始）
 * opts: { state, view, players, phase, maxPlayers, minPlayers, hostOpenId, hostWaiting, guestWaiting }
 */
function patchLobbyUi(patch, opts, page) {
  const o = opts || {}
  const pageRef = page || o.page
  const st = o.state || {}
  const v = o.view || {}
  const myOpenId = resolveLobbyMyOpenId(pageRef, (v && v.myOpenId) || o.myOpenId || '')
  const phase =
    o.phase != null
      ? o.phase
      : st.status || st.currentPhase || (v && v.roomStatus) || 'waiting'
  const waiting = phase === 'waiting' || phase === 'lobby' || !phase
  const playersRaw = o.players || st.publicPlayers || []
  const players = waiting
    ? overlayLobbyProfileReady(playersRaw, myOpenId, pageRef)
    : playersRaw
  const n = players.length
  const isHost = !!(o.isHost != null ? o.isHost : v.isHost)
  const minPlayers = (o.minPlayers | 0) || 2
  const maxPlayers = (o.maxPlayers | 0) > 0 ? (o.maxPlayers | 0) : waiting && o.targetPlayers ? (o.targetPlayers | 0) : 0
  const need = maxPlayers > 0 ? maxPlayers : minPlayers

  patch.inWaiting = waiting
  if (o.memberCountLine != null) {
    patch.memberCountLine = o.memberCountLine
  } else if (maxPlayers > 0) {
    patch.memberCountLine = memberCountLine(n, maxPlayers)
  } else if (waiting) {
    patch.memberCountLine = memberCountLine(n, 0, '至少 ' + minPlayers + ' 人可开始')
  } else {
    patch.memberCountLine = memberCountLine(n, 0, '至少 ' + minPlayers + ' 人可开始')
  }

  const hostOpenId = st.hostOpenId || (v && v.hostOpenId) || o.hostOpenId || ''
  const guestStats = waiting
    ? lobbyGuestReadyStats(players, hostOpenId, pageRef, myOpenId)
    : null

  patchMemberDisplay(patch, {
    players,
    phase: waiting ? 'waiting' : 'playing',
    maxPlayers: waiting && maxPlayers > 0 ? maxPlayers : waiting ? minPlayers : 0,
    isHost,
    myOpenId,
    hostOpenId,
    fallbackNeed: minPlayers,
    hostWaiting: o.hostWaiting,
    guestWaiting: o.guestWaiting,
    page: pageRef
  })

  let canStart = isHost && n >= minPlayers
  if (maxPlayers > 0) {
    canStart = isHost && n >= maxPlayers && n >= minPlayers
  }
  if (waiting && guestStats && guestStats.guestCount > 0) {
    canStart = canStart && guestStats.allReady
  }
  patch.canStart = o.canStart != null ? o.canStart : canStart
  let statusHint = buildLobbyStatusHint(isHost, phase, n, {
    minPlayers,
    maxPlayers: maxPlayers > 0 ? maxPlayers : 0,
    hostWaiting: o.hostWaiting,
    guestWaiting: o.guestWaiting,
    playingHint: o.playingHint
  })
  patch.statusHint = appendGuestReadyHint(statusHint, isHost, waiting, guestStats)
  patch.statusBannerWarn =
    waiting &&
    (n < minPlayers ||
      (maxPlayers > 0 && n < maxPlayers) ||
      (isHost && guestStats && guestStats.guestCount > 0 && !guestStats.allReady))
  patchLobbySelfReady(patch, players, myOpenId, waiting, pageRef)
  return patch
}

module.exports = {
  mergeLocalProfileIntoPlayers,
  enrichPlayers,
  computeStatusHint,
  computeProgressPct,
  patchMemberDisplay,
  buildLobbyStatusHint,
  patchLobbyUi
}
