/**
 * 同场聚会组：成员展示、状态文案、进度
 */
const { memberCountLine } = require('./roomUi')
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
  return (pl || []).map((p) => {
    const isHost = !!p.isHost || !!(hostOpenId && p.openId && p.openId === hostOpenId)
    const ready = inWord ? !!p.wordAck : p.isAlive !== false
    let readyLabel = '已到'
    if (inWord) {
      readyLabel = p.wordAck ? '已看词' : '未看词'
    } else if (ph !== 'waiting' && ph !== 'lobby' && ph) {
      readyLabel = p.isAlive === false ? '暂离' : '在场'
    }
    const nick = (p.nickName || p.nick || '玩家').toString()
    return {
      openId: p.openId,
      nickName: nick,
      isHost,
      isAlive: p.isAlive !== false,
      wordAck: !!p.wordAck,
      ready,
      readyLabel,
      avatarText: nick.slice(0, 1) || '?',
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
  const players = o.players || []
  const phase = o.phase || 'waiting'
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
  return o.guestWaiting || '👥 等待组长开始互动'
}

/**
 * 等待大厅统一 UI 状态（成员、进度、横幅、可开始）
 * opts: { state, view, players, phase, maxPlayers, minPlayers, hostOpenId, hostWaiting, guestWaiting }
 */
function patchLobbyUi(patch, opts) {
  const o = opts || {}
  const st = o.state || {}
  const v = o.view || {}
  const players = o.players || st.publicPlayers || []
  const n = players.length
  const phase =
    o.phase != null
      ? o.phase
      : st.status || st.currentPhase || (v && v.roomStatus) || 'waiting'
  const waiting = phase === 'waiting' || phase === 'lobby' || !phase
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
    patch.memberCountLine = memberCountLine(n, minPlayers)
  } else {
    patch.memberCountLine = memberCountLine(n, 0, '至少 ' + minPlayers + ' 人可开始')
  }

  patchMemberDisplay(patch, {
    players,
    phase: waiting ? 'waiting' : 'playing',
    maxPlayers: waiting && maxPlayers > 0 ? maxPlayers : waiting ? minPlayers : 0,
    isHost,
    hostOpenId: st.hostOpenId || (v && v.hostOpenId) || o.hostOpenId || '',
    fallbackNeed: minPlayers,
    hostWaiting: o.hostWaiting,
    guestWaiting: o.guestWaiting
  })

  let canStart = isHost && n >= minPlayers
  if (maxPlayers > 0) {
    canStart = isHost && n >= maxPlayers && n >= minPlayers
  }
  patch.canStart = o.canStart != null ? o.canStart : canStart
  patch.statusHint = buildLobbyStatusHint(isHost, phase, n, {
    minPlayers,
    maxPlayers: maxPlayers > 0 ? maxPlayers : 0,
    hostWaiting: o.hostWaiting,
    guestWaiting: o.guestWaiting,
    playingHint: o.playingHint
  })
  patch.statusBannerWarn =
    waiting && (n < minPlayers || (maxPlayers > 0 && n < maxPlayers))
  return patch
}

module.exports = {
  enrichPlayers,
  computeStatusHint,
  computeProgressPct,
  patchMemberDisplay,
  buildLobbyStatusHint,
  patchLobbyUi
}
