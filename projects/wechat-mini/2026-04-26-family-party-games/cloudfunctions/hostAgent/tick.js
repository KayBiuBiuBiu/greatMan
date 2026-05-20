/**
 * 副主持自动推进：根据阶段与截止时间调用对应云函数 action
 */
const cloud = require('wx-server-sdk')

const AGENT_AUTH = process.env.AGENT_HOST_TOKEN || 'family-party-agent-v1'

async function callGame(gameKind, data) {
  const name =
    gameKind === 'drink'
      ? 'drinkRoomService'
      : gameKind === 'undercover'
        ? 'undercoverRoomService'
        : gameKind === 'werewolf'
          ? 'werewolfService'
          : ''
  if (!name) {
    return { errMsg: '未知游戏' }
  }
  const res = await cloud.callFunction({
    name,
    data: Object.assign({}, data, { _agentAuth: AGENT_AUTH })
  })
  return (res && res.result) || {}
}

function planDrink(state, now, roomId) {
  const actions = []
  let speak = ''
  const rid = String(roomId || (state && (state._id || state.roomId)) || '')
  if (!state || !rid) {
    return { actions, speak }
  }
  const ph = state.phase
  if (ph === 'countdown' && now >= (state.countdownEndsAt | 0) - 100) {
    actions.push({ service: 'drink', action: 'revealRinger', roomId: rid })
    speak = '倒计时结束，自动揭晓响铃者'
  } else if (ph === 'voting') {
    const need = (state.voteProgress && state.voteProgress.need) || 0
    const cast = (state.voteProgress && state.voteProgress.cast) || 0
    const deadline = state.votingDeadline | 0
    if ((need > 0 && cast >= need) || now >= deadline - 300) {
      actions.push({
        service: 'drink',
        action: 'finalizeVoting',
        roomId: rid,
        force: false
      })
      speak = '投票时间到，自动结算'
    }
  }
  return { actions, speak }
}

function planUndercover(state, now) {
  const actions = []
  let speak = ''
  if (!state) {
    return { actions, speak }
  }
  const ph = state.currentPhase || state.phase
  const rid = state._id || state.roomId
  // 讨论阶段超时自动开投票（若配置了 discussDeadline）
  if (ph === 'discuss' && state.discussEndsAt && now >= state.discussEndsAt) {
    actions.push({ service: 'undercover', action: 'startVote', roomId: rid })
    speak = '讨论时间到，自动开始投票'
  }
  return { actions, speak }
}

function planWerewolf(state) {
  return { actions: [], speak: '' }
}

async function runTick(gameKind, roomId) {
  const { loadState } = require('./state')
  const bundle = await loadState(gameKind, roomId)
  const state = bundle && bundle.state
  const now = Date.now()
  let plan = { actions: [], speak: '' }
  if (bundle && bundle.kind === 'drink') {
    plan = planDrink(state, now, roomId)
  } else if (bundle && bundle.kind === 'undercover') {
    plan = planUndercover(state, now)
  } else if (bundle && bundle.kind === 'werewolf') {
    plan = planWerewolf(state)
  }

  const executed = []
  for (let i = 0; i < plan.actions.length; i++) {
    const a = plan.actions[i]
    const r = await callGame(a.service, {
      action: a.action,
      roomId: a.roomId,
      force: a.force
    })
    executed.push({ action: a.action, result: r })
  }
  return {
    speakText: plan.speak,
    planned: plan.actions,
    executed
  }
}

module.exports = { runTick, AGENT_AUTH }
