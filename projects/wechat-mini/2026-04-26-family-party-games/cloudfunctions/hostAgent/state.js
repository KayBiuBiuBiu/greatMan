/**
 * 读取各游戏公开状态（供 Agent 决策）
 */
const cloud = require('wx-server-sdk')
const db = cloud.database()

async function loadState(gameKind, roomId) {
  const rid = String(roomId || '')
  if (!rid) {
    return null
  }
  const k = String(gameKind || '').toLowerCase()
  if (k === 'drink' || k === 'drinkparty') {
    const doc = await db.collection('drink_gameState').doc(rid).get()
    return { kind: 'drink', state: doc.data || null }
  }
  if (k === 'undercover') {
    const doc = await db.collection('uc_state').doc(rid).get()
    return { kind: 'undercover', state: doc.data || null }
  }
  if (k === 'werewolf') {
    const doc = await db.collection('werewolf_state').doc(rid).get()
    return { kind: 'werewolf', state: doc.data || null }
  }
  return null
}

function summarizeForPrompt(bundle) {
  if (!bundle || !bundle.state) {
    return '（无状态）'
  }
  const s = bundle.state
  const lines = [`游戏: ${bundle.kind}`]
  if (bundle.kind === 'drink') {
    lines.push(`阶段: ${s.phase}`, `轮次: ${s.currentRound}`)
    if (s.targetNick) {
      lines.push(`响铃者昵称: ${s.targetNick}`)
    }
    if (s.voteProgress) {
      lines.push(`投票: ${s.voteProgress.cast}/${s.voteProgress.need}`)
    }
    if (s.countdownEndsAt) {
      lines.push(`倒计时结束: ${s.countdownEndsAt}`)
    }
    if (s.votingDeadline) {
      lines.push(`投票截止: ${s.votingDeadline}`)
    }
    if (s.publicPlayers) {
      lines.push(
        '玩家: ' +
          s.publicPlayers.map((p) => p.nickName + (p.isHost ? '(组长)' : '')).join('、')
      )
    }
  } else if (bundle.kind === 'undercover') {
    lines.push(
      `阶段: ${s.currentPhase || s.phase}`,
      `轮次: ${s.currentRound}`,
      `发言序号: ${s.speakIndex}`
    )
    if (s.publicLog && s.publicLog.length) {
      lines.push('公开记录: ' + JSON.stringify(s.publicLog.slice(-8)))
    }
  } else if (bundle.kind === 'werewolf') {
    lines.push(`阶段: ${s.currentPhase}`, `天数: ${s.day}`)
    if (s.publicLog && s.publicLog.length) {
      lines.push('公开记录: ' + JSON.stringify(s.publicLog.slice(-8)))
    }
  }
  return lines.join('\n')
}

module.exports = { loadState, summarizeForPrompt }
