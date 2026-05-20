/**
 * 同场聚会组：成员展示、状态文案、进度
 */
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

module.exports = {
  enrichPlayers,
  computeStatusHint,
  computeProgressPct,
  patchMemberDisplay
}
