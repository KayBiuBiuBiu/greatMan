/**
 * 秘密身份推理 — AI 全自动主持云函数
 * 阶段：waiting → night → day_announce → [day1: sheriff_signup → sheriff_withdraw → sheriff_speak → sheriff_vote] → speak → vote → …
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()

const {
  MAXN,
  DECK,
  MIN_PLAYERS,
  rolesForPlayerCount,
  isWolfRole,
  isGodRole,
  membersOf,
  roomSeatCap
} = require('../common/wolfDeck')
const R = 'werewolf_rooms'
const S = 'werewolf_state'
const participantsOf = membersOf

const DUR = {
  nightRole: 30,
  witchSave: 15,
  witchPoison: 30,
  dayAnnounce: 5,
  sheriffSignup: 25,
  sheriffWithdraw: 10,
  sheriffSpeak: 60,
  sheriffVote: 45,
  speak: 60,
  vote: 60,
  hunter: 10,
  sheriffTransfer: 15
}

const now = () => Date.now()

function shuf(a) {
  const x = a.slice()
  for (let i = x.length - 1; i > 0; i -= 1) {
    const j = (Math.random() * (i + 1)) | 0
    const t = x[i]
    x[i] = x[j]
    x[j] = t
  }
  return x
}

function omitIdDeep(x) {
  if (x == null) return x
  if (Array.isArray(x)) return x.map(omitIdDeep)
  if (typeof x === 'object') {
    if (x instanceof Date) return x
    if (Object.getPrototypeOf(x) !== Object.prototype) return x
    const o = {}
    for (const k of Object.keys(x)) {
      if (k === '_id' || k === '_openid') continue
      o[k] = omitIdDeep(x[k])
    }
    return o
  }
  return x
}

async function getOpenId() {
  return cloud.getWXContext().OPENID
}

async function getRoomById(id) {
  if (!id) return null
  const r = await db.collection(R).doc(String(id)).get()
  return r.data || null
}

function nn(room, oid) {
  const m = (room.members || []).find((u) => u.openId === oid)
  return m ? m.nickName : '参与者'
}

function getRole(room, oid) {
  return (room.playerRoles || {})[oid] || ''
}

function alivePlayers(room) {
  const al = (room.game && room.game.alive) || {}
  return participantsOf(room).filter((m) => al[m.openId] !== false)
}

function aliveWolves(room) {
  return alivePlayers(room).filter((m) => isWolfRole(getRole(room, m.openId)))
}

function defaultAiState() {
  return {
    aiMode: true,
    currentPhaseStartTime: 0,
    phaseDuration: DUR.nightRole,
    nightSteps: [],
    nightStepIndex: 0,
    wolfVotes: {},
    seerTarget: '',
    seerResult: null,
    witchSave: null,
    witchPoisonTarget: '',
    witchPhaseStep: 1,
    guardTarget: '',
    lastGuardTarget: '',
    speakOrder: [],
    currentSpeakerIndex: 0,
    voteResults: {},
    nightKillTarget: '',
    nightSaveTarget: '',
    nightPoisonTarget: '',
    nightGuardTarget: '',
    lastNightDeaths: [],
    lastNightCauses: {},
    pendingHunter: null,
    hunterFromNight: false,
    hunterCause: '',
    whiteWolfBoomStep: '',
    whiteWolfBoomOpenId: '',
    winner: '',
    actedWolves: {},
    actedSeer: false,
    actedWitchSave: false,
    actedWitchPoison: false,
    actedGuard: false,
    sheriffSignup: {},
    sheriffCandidates: [],
    sheriffPhase: 'signup',
    withdrawEndTime: 0,
    sheriffWithdrawn: {},
    sheriffSpeakOrder: [],
    sheriffSpeakIndex: 0,
    sheriffVotes: {},
    sheriffTransferPending: false,
    sheriffTransferFrom: '',
    sheriffTransferContinue: ''
  }
}

function getSheriffOpenId(g) {
  const game = g || {}
  return String(game.sheriffOpenId || (game.ai && game.ai.sheriffOpenId) || '')
}

function setSheriffOpenId(g, oid) {
  g.sheriffOpenId = oid || ''
  if (g.ai) g.ai.sheriffOpenId = oid || ''
}

/**
 * 警长出局后进入移交警徽阶段（15s）；超时或未移交则警徽流失。
 * @returns {boolean} true 表示已进入移交阶段，调用方应中止后续流程
 */
function tryStartSheriffTransfer(room, deadSheriffOid, continueKind) {
  const g = room.game
  if (!deadSheriffOid || getSheriffOpenId(g) !== deadSheriffOid) return false
  const ai = ensureAi(g)
  ai.sheriffTransferFrom = deadSheriffOid
  ai.sheriffTransferPending = true
  ai.sheriffTransferContinue = continueKind || ''
  g.phase = 'sheriff_transfer'
  resetPhaseTimer(ai, DUR.sheriffTransfer)
  g.publicLog = (g.publicLog || []).concat([
    '警长 ' +
      nn(room, deadSheriffOid) +
      ' 出局，请在15秒内移交警徽（可交给存活玩家）'
  ])
  return true
}

/** 完成移交：targetOid 为空表示不移交 / 超时 → 警徽流失 */
async function completeSheriffTransfer(room, targetOid) {
  const g = room.game
  const ai = ensureAi(g)
  if (g.phase !== 'sheriff_transfer' && !ai.sheriffTransferPending) return
  const from = String(ai.sheriffTransferFrom || getSheriffOpenId(g) || '')
  ai.sheriffTransferPending = false
  ai.sheriffTransferFrom = ''
  const kind = ai.sheriffTransferContinue || ''
  ai.sheriffTransferContinue = ''

  let tid = String(targetOid || '').trim()
  if (tid && (tid === from || g.alive[tid] === false)) tid = ''
  if (tid) {
    setSheriffOpenId(g, tid)
    g.publicLog = (g.publicLog || []).concat([
      '警长将警徽移交给了 ' + nn(room, tid)
    ])
  } else {
    setSheriffOpenId(g, '')
    g.publicLog = (g.publicLog || []).concat(['警长未能移交警徽，警徽流失'])
  }
  await resumeAfterSheriffTransfer(room, kind)
}

/** 移交结束或跳过后，按 pendingContinue 恢复主流程 */
async function resumeAfterSheriffTransfer(room, kind) {
  const g = room.game
  const ai = ensureAi(g)
  if (checkGameEnd(room)) return

  if (kind === 'after_night') {
    if (ai.pendingHunter) {
      g.phase = 'hunter'
      resetPhaseTimer(ai, DUR.hunter)
      g.publicLog = (g.publicLog || []).concat(['协定者请选择是否带走一人'])
      return
    }
    g.phase = 'day_announce'
    resetPhaseTimer(ai, DUR.dayAnnounce)
    const uniq = ai.lastNightDeaths || []
    const names = uniq.length ? uniq.map((id) => nn(room, id)).join('、') : '无人'
    g.publicLog = (g.publicLog || []).concat(['天亮了。昨夜：' + names])
    return
  }
  if (kind === 'after_vote_hunter') {
    g.phase = 'hunter'
    resetPhaseTimer(ai, DUR.hunter)
    return
  }
  if (kind === 'vote_night') {
    g.day = (g.day | 0) + 1
    g.phase = 'night'
    ai.nightStepIndex = 0
    clearNightActionFlags(ai)
    ai.witchPhaseStep = 1
    startNightStep(room)
    g.publicLog = (g.publicLog || []).concat(['第' + g.day + '夜'])
    return
  }
  if (kind === 'white_wolf_night') {
    g.day = (g.day | 0) + 1
    g.phase = 'night'
    ai.nightStepIndex = 0
    clearNightActionFlags(ai)
    ai.witchPhaseStep = 1
    startNightStep(room)
    g.publicLog = (g.publicLog || []).concat(['第' + g.day + '夜'])
    return
  }
  if (kind === 'after_hunter_shot') {
    await afterHunterPhase(room)
    return
  }
  g.phase = 'day_announce'
  resetPhaseTimer(ai, DUR.dayAnnounce)
}

function ensureAi(game) {
  if (!game.ai) game.ai = defaultAiState()
  return game.ai
}

function buildNightSteps(room) {
  const pr = room.playerRoles || {}
  const roles = Object.values(pr)
  const steps = []
  if (roles.some(isWolfRole)) steps.push('wolf')
  if (roles.includes('seer')) steps.push('seer')
  if (roles.includes('witch')) steps.push('witch')
  if (roles.includes('guard')) steps.push('guard')
  return steps
}

/** 白狼王白天自爆：自己与目标出局，跳过发言/投票，直接入夜 */
async function whiteWolfSelfDestruct(room, actorOpenId, targetOpenId) {
  const g = room.game
  const ai = ensureAi(g)
  const t = String(targetOpenId || '')
  if (!t || t === actorOpenId) {
    throw new Error('请选择带走对象')
  }
  if (g.alive[t] === false) {
    throw new Error('目标已暂离')
  }
  const sheriff = getSheriffOpenId(g)
  const sheriffDead = sheriff && (sheriff === actorOpenId || sheriff === t)
  g.alive[actorOpenId] = false
  g.alive[t] = false
  ai.whiteWolfBoomStep = ''
  ai.whiteWolfBoomOpenId = ''
  ai.voteResults = {}
  g.voteOpen = 0
  g.publicLog = (g.publicLog || []).concat([
    '白狼王自爆：' + nn(room, actorOpenId) + ' 带走 ' + nn(room, t)
  ])
  if (checkGameEnd(room)) return
  if (sheriffDead && tryStartSheriffTransfer(room, sheriff, 'white_wolf_night')) return
  g.day = (g.day | 0) + 1
  g.phase = 'night'
  ai.nightStepIndex = 0
  clearNightActionFlags(ai)
  ai.witchPhaseStep = 1
  startNightStep(room)
  g.publicLog = (g.publicLog || []).concat(['第' + g.day + '夜'])
}

function remainingSeconds(ai) {
  const start = ai.currentPhaseStartTime | 0
  const dur = ai.phaseDuration | 0
  if (!start || !dur) return 0
  const left = Math.ceil((start + dur * 1000 - now()) / 1000)
  return left > 0 ? left : 0
}

function resetPhaseTimer(ai, durationSec) {
  ai.currentPhaseStartTime = now()
  ai.phaseDuration = durationSec | 0
}

/** 警长退水窗口剩余秒数（优先 withdrawEndTime） */
function withdrawRemainingSeconds(ai) {
  const end = (ai && ai.withdrawEndTime) | 0
  if (end) return Math.max(0, Math.ceil((end - now()) / 1000))
  return remainingSeconds(ai)
}

function buildPubFromRoom(room) {
  if (!room || !room._id) return null
  const g = room.game || {}
  const ai = g.ai || {}
  const al = g.alive || {}
  return {
    roomCode: room.roomCode,
    status: room.status,
    maxPlayers: room.maxPlayers,
    currentPhase: g.phase || 'lobby',
    day: g.day || 0,
    hostOpenId: room.hostOpenId || '',
    aiMode: !!ai.aiMode,
    currentPhaseStartTime: ai.currentPhaseStartTime | 0,
    phaseDuration: ai.phaseDuration | 0,
    remainingSeconds: remainingSeconds(ai),
    nightSteps: ai.nightSteps || [],
    nightStepIndex: ai.nightStepIndex | 0,
    currentNightStep: (ai.nightSteps || [])[ai.nightStepIndex | 0] || '',
    witchPhaseStep: ai.witchPhaseStep | 1,
    speakOrder: ai.speakOrder || [],
    currentSpeakerIndex: ai.currentSpeakerIndex | 0,
    currentSpeakerOpenId: (() => {
      const ph = g.phase
      if (ph === 'sheriff_speak') {
        return (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0] || ''
      }
      return (ai.speakOrder || [])[ai.currentSpeakerIndex | 0] || ''
    })(),
    currentSpeakerNick: (() => {
      const ph = g.phase
      let oid = ''
      if (ph === 'sheriff_speak') {
        oid = (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0] || ''
      } else {
        oid = (ai.speakOrder || [])[ai.currentSpeakerIndex | 0] || ''
      }
      return oid ? nn(room, oid) : ''
    })(),
    sheriffOpenId: getSheriffOpenId(g),
    sheriffElectionDone: !!g.sheriffElectionDone,
    sheriffCandidates: (ai.sheriffCandidates || []).map((oid) => ({
      openId: oid,
      nickName: nn(room, oid)
    })),
    sheriffSignupCount: Object.keys(ai.sheriffSignup || {}).length,
    sheriffCandidateCount: (ai.sheriffCandidates || []).length,
    sheriffPhase: ai.sheriffPhase || '',
    withdrawRemainingSeconds:
      g.phase === 'sheriff_withdraw' ? withdrawRemainingSeconds(ai) : 0,
    voteResults: ai.voteResults || {},
    sheriffVotes: ai.sheriffVotes || {},
    wolfVotes: ai.wolfVotes || {},
    wolfVoteCount: Object.keys(ai.wolfVotes || {}).length,
    wolfTotal: aliveWolves(room).length,
    lastNightDeaths: ai.lastNightDeaths || [],
    lastNightCauses: ai.lastNightCauses || {},
    gameEnd: g.endReason,
    winSide: g.winSide,
    winner: ai.winner || g.winSide || '',
    pendingHunter: ai.pendingHunter,
    needTransfer: g.phase === 'sheriff_transfer' && !!ai.sheriffTransferPending,
    transferRemainingSeconds:
      g.phase === 'sheriff_transfer' ? remainingSeconds(ai) : 0,
    sheriffTransferFrom: ai.sheriffTransferFrom || '',
    players: (room.members || []).map((m, i) =>
      Object.assign(jp.withProfileReadyFlag(m), {
        isHost: m.openId === room.hostOpenId,
        isAlive: al[m.openId] !== false,
        isSheriff: getSheriffOpenId(g) === m.openId,
        seat: i + 1
      })
    ),
    publicLog: g.publicLog || [],
    updatedAt: now()
  }
}

async function setPub(room) {
  const doc = buildPubFromRoom(room)
  if (!doc) return
  await db.collection(S).doc(String(room._id)).set({ data: omitIdDeep(doc) })
}

async function saveRoom(room) {
  await db.collection(R).doc(String(room._id)).update({
    data: {
      status: room.status,
      playerRoles: room.playerRoles,
      game: room.game,
      updatedAt: now()
    }
  })
  const fresh = await getRoomById(room._id)
  if (fresh) await setPub(fresh)
  return fresh || room
}

/** 屠边：狼灭 / 神灭或民灭 */
function checkGameEnd(room) {
  const g = room.game
  const pr = room.playerRoles || {}
  const al = g.alive || {}
  let wolves = 0
  let gods = 0
  let villagers = 0
  membersOf(room).forEach((m) => {
    if (al[m.openId] === false) return
    const r = pr[m.openId]
    if (isWolfRole(r)) wolves += 1
    else if (r === 'villager') villagers += 1
    else if (isGodRole(r)) gods += 1
  })
  const ai = ensureAi(g)
  if (wolves === 0) {
    g.phase = 'end'
    g.winSide = 'good'
    g.endReason = '所有暗位成员已暂离，村民侧胜利'
    ai.winner = 'good'
    room.status = 'ended'
    return true
  }
  if (gods === 0 || villagers === 0) {
    g.phase = 'end'
    g.winSide = 'wolf'
    g.endReason =
      gods === 0 ? '神职已全部暂离，暗位侧胜利' : '村民已全部暂离，暗位侧胜利'
    ai.winner = 'wolf'
    room.status = 'ended'
    return true
  }
  return false
}

function aggWolfVotes(wolfVotes) {
  const c = {}
  let best = 0
  let out = null
  const keys = Object.keys(wolfVotes || {})
  keys.forEach((k) => {
    const t = wolfVotes[k]
    if (!t) return
    c[t] = (c[t] || 0) + 1
    if (c[t] > best) {
      best = c[t]
      out = t
    } else if (c[t] === best && Math.random() > 0.5) {
      out = t
    }
  })
  return out
}

function clearNightActionFlags(ai) {
  ai.actedWolves = {}
  ai.actedSeer = false
  ai.actedWitchSave = false
  ai.actedWitchPoison = false
  ai.actedGuard = false
  ai.seerTarget = ''
  ai.witchSave = null
  ai.witchPoisonTarget = ''
  ai.guardTarget = ''
  ai.witchPhaseStep = 1
}

function startNightStep(room) {
  const g = room.game
  const ai = ensureAi(g)
  const step = (ai.nightSteps || [])[ai.nightStepIndex | 0]
  if (step === 'witch') {
    ai.witchPhaseStep = ai.nightKillTarget ? 1 : 2
    resetPhaseTimer(ai, ai.witchPhaseStep === 1 ? DUR.witchSave : DUR.witchPoison)
  } else {
    resetPhaseTimer(ai, DUR.nightRole)
  }
  g.publicLog = (g.publicLog || []).concat([
    '夜间·' +
      (step === 'wolf'
        ? '暗位'
        : step === 'seer'
          ? '线索员'
          : step === 'witch'
            ? '治愈者'
            : step === 'guard'
              ? '守卫'
              : step) +
      ' 行动中'
  ])
}

async function resolveNight(room) {
  const g = room.game
  const ai = ensureAi(g)
  const al = { ...(g.alive || {}) }
  const dead = []
  const causes = {}

  const kill = ai.nightKillTarget
  const poison = ai.nightPoisonTarget
  const guard = ai.nightGuardTarget
  const saved = ai.witchSave === true && kill

  if (kill) {
    let dies = true
    const guarded = guard && guard === kill
    if (saved && guarded) {
      dies = true
      causes[kill] = '同守同救'
    } else if (saved) {
      dies = false
      causes[kill] = causes[kill] || '被袭击但已缓解'
    } else if (guarded) {
      dies = false
      causes[kill] = '被守护'
    } else {
      causes[kill] = '夜间关注'
    }
    if (dies) {
      dead.push(kill)
      al[kill] = false
    }
  }
  if (poison && al[poison] !== false) {
    if (dead.indexOf(poison) < 0) dead.push(poison)
    al[poison] = false
    causes[poison] = '备用提醒'
  }
  const uniq = [...new Set(dead)]
  const sheriffDead = uniq.find((id) => getSheriffOpenId(g) === id)
  ai.lastNightDeaths = uniq
  ai.lastNightCauses = causes
  g.alive = al
  g.lastNightReport = uniq.map((id) => {
    const c = causes[id] || '暂离'
    return nn(room, id) + '（' + c + '）'
  })

  uniq.forEach((id) => {
    if (getRole(room, id) === 'hunter' && causes[id] !== '备用提醒') {
      ai.pendingHunter = id
      ai.hunterFromNight = true
      ai.hunterCause = causes[id] || ''
    }
  })

  ai.nightKillTarget = ''
  ai.nightPoisonTarget = ''
  ai.nightGuardTarget = ''
  ai.wolfVotes = {}
  clearNightActionFlags(ai)

  if (checkGameEnd(room)) return

  if (sheriffDead && tryStartSheriffTransfer(room, sheriffDead, 'after_night')) return

  if (ai.pendingHunter) {
    g.phase = 'hunter'
    resetPhaseTimer(ai, DUR.hunter)
    g.publicLog = (g.publicLog || []).concat(['协定者请选择是否带走一人'])
    return
  }

  g.phase = 'day_announce'
  resetPhaseTimer(ai, DUR.dayAnnounce)
  const names = uniq.length ? uniq.map((id) => nn(room, id)).join('、') : '无人'
  g.publicLog = (g.publicLog || []).concat(['天亮了。昨夜：' + names])
}

async function advanceNightStep(room) {
  const g = room.game
  const ai = ensureAi(g)
  const steps = ai.nightSteps || []
  const idx = ai.nightStepIndex | 0
  const step = steps[idx]

  if (step === 'wolf') {
    const target = aggWolfVotes(ai.wolfVotes) || ai.nightKillTarget
    ai.nightKillTarget = target || ''
    ai.wolfVotes = {}
  } else if (step === 'seer') {
    if (ai.seerTarget) {
      const isW = isWolfRole(getRole(room, ai.seerTarget))
      ai.seerResult = {
        target: ai.seerTarget,
        isW,
        label: isW ? '暗位侧' : '村民侧'
      }
    }
  } else if (step === 'witch') {
    if (ai.witchPhaseStep === 1) {
      if (ai.witchSave === true && ai.nightKillTarget) {
        ai.nightSaveTarget = ai.nightKillTarget
      }
      ai.witchPhaseStep = 2
      resetPhaseTimer(ai, DUR.witchPoison)
      return
    }
    if (ai.witchPoisonTarget) {
      ai.nightPoisonTarget = ai.witchPoisonTarget
    }
  } else if (step === 'guard') {
    if (ai.guardTarget) {
      ai.nightGuardTarget = ai.guardTarget
      ai.lastGuardTarget = ai.guardTarget
    }
  }

  ai.nightStepIndex = idx + 1
  if (ai.nightStepIndex >= steps.length) {
    await resolveNight(room)
    return
  }
  startNightStep(room)
}

/** 天亮后：第 1 天先走警长竞选，否则直接进入白天发言 */
async function afterDayAnnounce(room) {
  const g = room.game
  const ai = ensureAi(g)
  if ((g.day | 0) === 1 && !g.sheriffElectionDone) {
    g.phase = 'sheriff_signup'
    ai.sheriffSignup = {}
    ai.sheriffCandidates = []
    ai.sheriffVotes = {}
    ai.sheriffPhase = 'signup'
    ai.withdrawEndTime = 0
    ai.sheriffWithdrawn = ai.sheriffWithdrawn || {}
    resetPhaseTimer(ai, DUR.sheriffSignup)
    g.publicLog = (g.publicLog || []).concat([
      '警长竞选：请选择是否上警（警上发言后投票选警长）'
    ])
    return
  }
  await dayAnnounceToSpeak(room)
}

function finalizeSheriffSignup(room) {
  const g = room.game
  const ai = ensureAi(g)
  const alive = alivePlayers(room)
  alive.forEach((m) => {
    if (!ai.sheriffSignup[m.openId]) {
      ai.sheriffSignup[m.openId] = 'skip'
    }
  })
  g.sheriffElectionDone = true
  ai.sheriffCandidates = alive
    .filter((m) => ai.sheriffSignup[m.openId] === 'run')
    .map((m) => m.openId)
  const logs = []
  if (ai.sheriffCandidates.length === 0) {
    ai.sheriffPhase = 'done'
    logs.push('无人上警，本局无警长')
    g.publicLog = (g.publicLog || []).concat(logs)
    return { next: 'speak' }
  }
  if (ai.sheriffCandidates.length === 1) {
    ai.sheriffPhase = 'done'
    setSheriffOpenId(g, ai.sheriffCandidates[0])
    logs.push(nn(room, ai.sheriffCandidates[0]) + ' 独自上警，当选警长')
    g.publicLog = (g.publicLog || []).concat(logs)
    return { next: 'speak' }
  }
  logs.push(
    '上警 ' +
      ai.sheriffCandidates.length +
      ' 人：' +
      ai.sheriffCandidates.map((id) => nn(room, id)).join('、')
  )
  g.publicLog = (g.publicLog || []).concat(logs)
  return { next: 'withdraw' }
}

/** 报名结束且上警≥2人：开启退水窗口（警上发言前） */
async function startSheriffWithdraw(room) {
  const g = room.game
  const ai = ensureAi(g)
  ai.sheriffPhase = 'withdraw'
  ai.withdrawEndTime = now() + DUR.sheriffWithdraw * 1000
  g.phase = 'sheriff_withdraw'
  resetPhaseTimer(ai, DUR.sheriffWithdraw)
  const n = (ai.sheriffCandidates || []).length
  g.publicLog = (g.publicLog || []).concat([
    '退水窗口开启（' +
      DUR.sheriffWithdraw +
      '秒），上警 ' +
      n +
      ' 人可选择退水（退水后不可再上警）'
  ])
}

/**
 * 退水后或退水窗口结束：按剩余候选人数决定下一阶段
 * @param {boolean} endWindow true=倒计时结束；false=玩家主动退水后检查（≥2 人则继续等待）
 */
async function afterWithdraw(room, endWindow) {
  const g = room.game
  const ai = ensureAi(g)
  const cands = (ai.sheriffCandidates || []).slice()
  const n = cands.length

  if (!endWindow && n >= 2) {
    return { stayed: true, count: n }
  }

  ai.sheriffPhase = 'done'
  ai.withdrawEndTime = 0

  if (n === 0) {
    setSheriffOpenId(g, '')
    g.publicLog = (g.publicLog || []).concat(['退水结束后无人上警，本局无警长'])
    await dayAnnounceToSpeak(room)
    return { next: 'speak' }
  }
  if (n === 1) {
    setSheriffOpenId(g, cands[0])
    g.publicLog = (g.publicLog || []).concat([
      nn(room, cands[0]) + ' 成为唯一候选人，当选警长'
    ])
    await dayAnnounceToSpeak(room)
    return { next: 'speak' }
  }
  await startSheriffSpeak(room)
  ai.sheriffPhase = 'speak'
  return { next: 'sheriff_speak' }
}

async function finishSheriffWithdrawWindow(room) {
  await afterWithdraw(room, true)
}

/** 上警玩家主动退水 */
async function handleWithdraw(event, actorOpenId) {
  let room = await getRoomById(event.roomId)
  if (!room || room.status !== 'playing') throw new Error('对局未进行中')
  if (!room.game || !room.game.ai || !room.game.ai.aiMode) {
    throw new Error('非 AI 主持模式')
  }
  await tickTimeout(room)
  room = (await getRoomById(event.roomId)) || room
  const g = room.game
  const ai = ensureAi(g)
  if (g.phase !== 'sheriff_withdraw' || ai.sheriffPhase !== 'withdraw') {
    throw new Error('当前非退水窗口')
  }
  if ((ai.sheriffCandidates || []).indexOf(actorOpenId) < 0) {
    throw new Error('你未上警，无法退水')
  }
  ai.sheriffCandidates = (ai.sheriffCandidates || []).filter((id) => id !== actorOpenId)
  ai.sheriffWithdrawn = ai.sheriffWithdrawn || {}
  ai.sheriffWithdrawn[actorOpenId] = true
  ai.sheriffSignup[actorOpenId] = 'withdrawn'
  g.publicLog = (g.publicLog || []).concat([nn(room, actorOpenId) + ' 退水'])
  await afterWithdraw(room, false)
  await saveRoom(room)
  return {
    ok: true,
    needRefresh: true,
    candidateCount: (ai.sheriffCandidates || []).length
  }
}

async function startSheriffSpeak(room) {
  const g = room.game
  const ai = ensureAi(g)
  ai.sheriffPhase = 'speak'
  ai.sheriffSpeakOrder = shuf((ai.sheriffCandidates || []).slice())
  ai.sheriffSpeakIndex = 0
  g.phase = 'sheriff_speak'
  resetPhaseTimer(ai, DUR.sheriffSpeak)
  const who = ai.sheriffSpeakOrder[0] ? nn(room, ai.sheriffSpeakOrder[0]) : '—'
  g.publicLog = (g.publicLog || []).concat(['警上发言开始，当前：' + who])
}

async function advanceSheriffSpeak(room) {
  const g = room.game
  const ai = ensureAi(g)
  ai.sheriffSpeakIndex = (ai.sheriffSpeakIndex | 0) + 1
  if (ai.sheriffSpeakIndex >= (ai.sheriffSpeakOrder || []).length) {
    g.phase = 'sheriff_vote'
    ai.sheriffPhase = 'vote'
    ai.sheriffVotes = {}
    resetPhaseTimer(ai, DUR.sheriffVote)
    g.publicLog = (g.publicLog || []).concat(['警徽投票：请选择警长'])
    return
  }
  resetPhaseTimer(ai, DUR.sheriffSpeak)
  const who = ai.sheriffSpeakOrder[ai.sheriffSpeakIndex]
  g.publicLog = (g.publicLog || []).concat(['下一位警上发言：' + nn(room, who)])
}

async function advanceSheriffVote(room) {
  const g = room.game
  const ai = ensureAi(g)
  const sv = ai.sheriffVotes || {}
  const tally = {}
  Object.keys(sv).forEach((voter) => {
    const t = sv[voter]
    if (!t) return
    tally[t] = (tally[t] || 0) + 1
  })
  let high = 0
  let winner = null
  let tie = false
  Object.keys(tally).forEach((k) => {
    if (tally[k] > high) {
      high = tally[k]
      winner = k
      tie = false
    } else if (tally[k] === high && high > 0) {
      tie = true
    }
  })
  if (tie) winner = null
  ai.sheriffVotes = {}
  if (winner && g.alive[winner] !== false) {
    setSheriffOpenId(g, winner)
    g.publicLog = (g.publicLog || []).concat([
      nn(room, winner) + ' 当选警长，获得警徽（放逐投票时计 2 票）'
    ])
  } else {
    g.publicLog = (g.publicLog || []).concat(['警徽投票平票或无效，本局无警长'])
  }
  await dayAnnounceToSpeak(room)
}

async function dayAnnounceToSpeak(room) {
  const g = room.game
  const ai = ensureAi(g)
  const order = shuf(alivePlayers(room).map((m) => m.openId))
  ai.speakOrder = order
  ai.currentSpeakerIndex = 0
  g.phase = 'speak'
  resetPhaseTimer(ai, DUR.speak)
  const who = order[0] ? nn(room, order[0]) : '—'
  const sheriff = getSheriffOpenId(g)
  const extra = sheriff ? '（警长：' + nn(room, sheriff) + '）' : ''
  g.publicLog = (g.publicLog || []).concat(['警下发言开始，当前：' + who + extra])
}

async function advanceSpeak(room) {
  const g = room.game
  const ai = ensureAi(g)
  ai.currentSpeakerIndex = (ai.currentSpeakerIndex | 0) + 1
  if (ai.currentSpeakerIndex >= (ai.speakOrder || []).length) {
    g.phase = 'vote'
    ai.voteResults = {}
    resetPhaseTimer(ai, DUR.vote)
    g.publicLog = (g.publicLog || []).concat(['投票阶段开始'])
    return
  }
  resetPhaseTimer(ai, DUR.speak)
  const who = ai.speakOrder[ai.currentSpeakerIndex]
  g.publicLog = (g.publicLog || []).concat(['下一位发言：' + nn(room, who)])
}

async function advanceVote(room) {
  const g = room.game
  const ai = ensureAi(g)
  const cv = ai.voteResults || {}
  const sheriffOid = getSheriffOpenId(g)
  const tally = {}
  Object.keys(cv).forEach((voter) => {
    const t = cv[voter]
    if (!t) return
    const w = sheriffOid && voter === sheriffOid ? 2 : 1
    tally[t] = (tally[t] || 0) + w
  })
  let high = 0
  let victim = null
  let tie = false
  Object.keys(tally).forEach((k) => {
    if (tally[k] > high) {
      high = tally[k]
      victim = k
      tie = false
    } else if (tally[k] === high && high > 0) {
      tie = true
    }
  })
  if (tie) victim = null

  ai.voteResults = {}
  if (victim && g.alive[victim] !== false) {
    g.alive[victim] = false
    const exileLogs = ['投票离场：' + nn(room, victim)]
    const wasSheriff = getSheriffOpenId(g) === victim
    const isHunter = getRole(room, victim) === 'hunter'
    if (wasSheriff) {
      if (isHunter) {
        ai.pendingHunter = victim
        ai.hunterFromNight = false
        ai.hunterCause = '投票'
      }
      g.publicLog = (g.publicLog || []).concat(exileLogs)
      const cont = isHunter ? 'after_vote_hunter' : 'vote_night'
      if (tryStartSheriffTransfer(room, victim, cont)) {
        if (checkGameEnd(room)) return
        return
      }
    } else {
      g.publicLog = (g.publicLog || []).concat(exileLogs)
      if (isHunter) {
        ai.pendingHunter = victim
        ai.hunterFromNight = false
        ai.hunterCause = '投票'
        g.phase = 'hunter'
        resetPhaseTimer(ai, DUR.hunter)
        if (checkGameEnd(room)) return
        return
      }
    }
  } else if (!victim) {
    g.publicLog = (g.publicLog || []).concat(['平票或无人投票，无人离场'])
  }

  if (checkGameEnd(room)) return

  g.day = (g.day | 0) + 1
  g.phase = 'night'
  ai.nightStepIndex = 0
  clearNightActionFlags(ai)
  ai.witchPhaseStep = 1
  startNightStep(room)
  g.publicLog = (g.publicLog || []).concat(['第' + g.day + '夜'])
}

async function afterHunterPhase(room) {
  const g = room.game
  const ai = ensureAi(g)
  ai.pendingHunter = null
  if (checkGameEnd(room)) return
  if (ai.hunterFromNight) {
    ai.hunterFromNight = false
    g.phase = 'day_announce'
    resetPhaseTimer(ai, DUR.dayAnnounce)
    return
  }
  g.day = (g.day | 0) + 1
  g.phase = 'night'
  ai.nightStepIndex = 0
  clearNightActionFlags(ai)
  startNightStep(room)
  g.publicLog = (g.publicLog || []).concat(['第' + g.day + '夜'])
}

async function resolveHunterSkip(room) {
  const g = room.game
  if (g.phase !== 'hunter') return
  await afterHunterPhase(room)
}

async function onHunterShot(room, targetOpenId) {
  const g = room.game
  if (targetOpenId && g.alive[targetOpenId] !== false) {
    g.alive[targetOpenId] = false
    g.publicLog = (g.publicLog || []).concat([
      '协定者带走 ' + nn(room, targetOpenId)
    ])
    if (getSheriffOpenId(g) === targetOpenId) {
      if (tryStartSheriffTransfer(room, targetOpenId, 'after_hunter_shot')) return
    }
  }
  if (room.game.phase !== 'hunter') return
  await afterHunterPhase(room)
}

/** 超时自动推进 */
async function tickTimeout(room) {
  const g = room.game
  const ai = ensureAi(g)
  if (room.status === 'ended' || g.phase === 'end') return false
  if (remainingSeconds(ai) > 0) return false

  if (ai.whiteWolfBoomStep === 'pick') {
    const actor = ai.whiteWolfBoomOpenId
    if (actor) {
      g.alive[actor] = false
      g.publicLog = (g.publicLog || []).concat([
        nn(room, actor) + ' 自爆（未选人，仅自身暂离）'
      ])
    }
    ai.whiteWolfBoomStep = ''
    ai.whiteWolfBoomOpenId = ''
    if (checkGameEnd(room)) return true
    g.day = (g.day | 0) + 1
    g.phase = 'night'
    ai.nightStepIndex = 0
    clearNightActionFlags(ai)
    startNightStep(room)
    return true
  }

  const ph = g.phase
  if (ph === 'night') {
    const step = (ai.nightSteps || [])[ai.nightStepIndex | 0]
    if (step === 'witch' && ai.witchPhaseStep === 1) {
      if (ai.witchSave == null) ai.witchSave = false
      await advanceNightStep(room)
      return true
    }
    await advanceNightStep(room)
    return true
  }
  if (ph === 'day_announce') {
    await afterDayAnnounce(room)
    return true
  }
  if (ph === 'sheriff_signup') {
    const r = finalizeSheriffSignup(room)
    if (r.next === 'speak') await dayAnnounceToSpeak(room)
    else if (r.next === 'withdraw') await startSheriffWithdraw(room)
    else await startSheriffSpeak(room)
    return true
  }
  if (ph === 'sheriff_withdraw') {
    await finishSheriffWithdrawWindow(room)
    return true
  }
  if (ph === 'sheriff_speak') {
    await advanceSheriffSpeak(room)
    return true
  }
  if (ph === 'sheriff_vote') {
    await advanceSheriffVote(room)
    return true
  }
  if (ph === 'speak') {
    await advanceSpeak(room)
    return true
  }
  if (ph === 'vote') {
    await advanceVote(room)
    return true
  }
  if (ph === 'hunter') {
    await resolveHunterSkip(room)
    return true
  }
  if (ph === 'sheriff_transfer') {
    await completeSheriffTransfer(room, null)
    return true
  }
  return false
}

function buildPlayerView(room, o) {
  const g = room.game || {}
  const ai = g.ai || {}
  const pr = room.playerRoles || {}
  const myR = pr[o]
  const al = g.alive || {}
  const phase = g.phase
  const nightStep = (ai.nightSteps || [])[ai.nightStepIndex | 0] || ''

  let canAct = false
  let actionHint = ''
  if (phase === 'night' && al[o] !== false) {
    if (nightStep === 'wolf' && isWolfRole(myR)) {
      canAct = true
      actionHint = 'wolf_kill'
    } else if (nightStep === 'seer' && myR === 'seer') {
      canAct = !ai.actedSeer
      actionHint = 'seer_check'
    } else if (nightStep === 'witch' && myR === 'witch') {
      if (ai.witchPhaseStep === 1 && ai.nightKillTarget) {
        canAct = !ai.actedWitchSave
        actionHint = 'witch_save'
      } else if (ai.witchPhaseStep === 2) {
        canAct = !ai.actedWitchPoison
        actionHint = 'witch_poison'
      }
    } else if (nightStep === 'guard' && myR === 'guard') {
      canAct = !ai.actedGuard
      actionHint = 'guard_guard'
    }
  } else if (phase === 'sheriff_signup' && al[o] !== false) {
    const withdrawn = !!(ai.sheriffWithdrawn && ai.sheriffWithdrawn[o])
    canAct = !ai.sheriffSignup[o] && !withdrawn
    actionHint = 'sheriff_signup'
  } else if (
    phase === 'sheriff_withdraw' &&
    (ai.sheriffCandidates || []).indexOf(o) >= 0
  ) {
    canAct = true
    actionHint = 'sheriff_withdraw'
  } else if (phase === 'sheriff_speak') {
    const cur = (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0]
    if (cur === o) {
      canAct = true
      actionHint = 'finish_sheriff_speak'
    }
  } else if (phase === 'sheriff_vote' && al[o] !== false) {
    canAct = !ai.sheriffVotes[o]
    actionHint = 'sheriff_vote'
  } else if (
    (phase === 'speak' ||
      phase === 'vote' ||
      phase === 'day_announce' ||
      phase === 'sheriff_speak' ||
      phase === 'sheriff_vote') &&
    myR === 'white_wolf' &&
    al[o] !== false
  ) {
    if (ai.whiteWolfBoomStep === 'pick') {
      canAct = o === ai.whiteWolfBoomOpenId
      actionHint = 'white_wolf_boom_kill'
    } else {
      canAct = true
      actionHint = 'white_wolf_boom'
    }
  } else if (phase === 'speak') {
    const cur = (ai.speakOrder || [])[ai.currentSpeakerIndex | 0]
    if (cur === o) {
      canAct = true
      actionHint = 'finish_speak'
    }
  } else if (phase === 'vote' && al[o] !== false) {
    canAct = !ai.voteResults[o]
    actionHint = 'vote'
  } else if (phase === 'hunter' && ai.pendingHunter === o) {
    canAct = true
    actionHint = 'hunter_shoot'
  } else if (phase === 'sheriff_transfer' && o === ai.sheriffTransferFrom) {
    canAct = true
    actionHint = 'sheriff_transfer'
  }

  const wm = aliveWolves(room)
    .filter((m) => m.openId !== o)
    .map((m) => m.nickName)

  return {
    myOpenId: o,
    myRole: myR,
    iAmAlive: al[o] !== false,
    isHost: room.hostOpenId === o,
    phase,
    day: g.day,
    canAct,
    actionHint,
    nightStep,
    witchPhaseStep: ai.witchPhaseStep,
    nightKillTargetNick: ai.nightKillTarget ? nn(room, ai.nightKillTarget) : '',
    wolfVoted: !!(ai.wolfVotes && ai.wolfVotes[o]),
    myWolfVoteTarget: (ai.wolfVotes && ai.wolfVotes[o]) || '',
    seerResult:
      myR === 'seer' && ai.seerResult && ai.seerResult.target
        ? ai.seerResult
        : null,
    myVoteTarget: (ai.voteResults && ai.voteResults[o]) || '',
    isCurrentSpeaker:
      (phase === 'speak' &&
        (ai.speakOrder || [])[ai.currentSpeakerIndex | 0] === o) ||
      (phase === 'sheriff_speak' &&
        (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0] === o),
    isSheriff: getSheriffOpenId(g) === o,
    isSheriffCandidate: (ai.sheriffCandidates || []).indexOf(o) >= 0,
    sheriffSignupChoice: (ai.sheriffSignup && ai.sheriffSignup[o]) || '',
    currentSpeakerNick:
      phase === 'sheriff_speak'
        ? nn(room, (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0])
        : phase === 'speak'
          ? nn(room, (ai.speakOrder || [])[ai.currentSpeakerIndex | 0])
          : '',
    wolfMates: isWolfRole(myR) ? wm : [],
    whiteWolfBoomStep: ai.whiteWolfBoomStep || '',
    pendingHunter: ai.pendingHunter,
    aiMode: true
  }
}

async function startAIMode(event, hostOpenId) {
  const ro = await getRoomById(event.roomId)
  if (!ro || ro.hostOpenId !== hostOpenId) {
    throw new Error('仅组长可开始 AI 主持局')
  }
  const players = membersOf(ro)
  const n = players.length
  if (n < MIN_PLAYERS) {
    throw new Error('至少 ' + MIN_PLAYERS + ' 人才能开始')
  }
  const roleList = rolesForPlayerCount(n)
  if (!roleList) {
    throw new Error('人数与板子未配')
  }

  const deck = shuf(roleList)
  const pr = {}
  const al = {}
  players.forEach((mem, i) => {
    pr[mem.openId] = deck[i]
    al[mem.openId] = true
  })

  const ai = defaultAiState()
  ai.nightSteps = buildNightSteps({ playerRoles: pr, members: ro.members })

  const g = {
    day: 1,
    phase: 'night',
    alive: al,
    sheriffOpenId: '',
    sheriffElectionDone: false,
    publicLog: ['AI 主持：第1夜开始'],
    ai,
    endReason: '',
    winSide: ''
  }
  ro.status = 'playing'
  ro.playerRoles = pr
  ro.game = g
  ai.nightStepIndex = 0
  startNightStep(ro)
  await saveRoom(ro)
  return { ok: true }
}

/** 警长移交警徽（AI 局） */
async function handleTransferSheriff(event, actorOpenId) {
  let room = await getRoomById(event.roomId)
  if (!room || room.status !== 'playing') throw new Error('对局未进行中')
  if (!room.game || !room.game.ai || !room.game.ai.aiMode) {
    throw new Error('非 AI 主持模式')
  }
  await tickTimeout(room)
  room = (await getRoomById(event.roomId)) || room
  const g = room.game
  const ai = ensureAi(g)
  if (g.phase !== 'sheriff_transfer') throw new Error('当前非移交警徽阶段')
  if (actorOpenId !== ai.sheriffTransferFrom) throw new Error('仅出局警长可移交警徽')
  const target = String(event.targetOpenId || '')
  if (!target || target === actorOpenId) throw new Error('请选择存活玩家')
  if (g.alive[target] === false) throw new Error('目标已暂离')
  await completeSheriffTransfer(room, target)
  await saveRoom(room)
  return { ok: true, sheriffOpenId: getSheriffOpenId(g), needRefresh: true }
}

/** 警长放弃移交（AI 局） */
async function handleSkipTransfer(event, actorOpenId) {
  let room = await getRoomById(event.roomId)
  if (!room || room.status !== 'playing') throw new Error('对局未进行中')
  if (!room.game || !room.game.ai || !room.game.ai.aiMode) {
    throw new Error('非 AI 主持模式')
  }
  await tickTimeout(room)
  room = (await getRoomById(event.roomId)) || room
  const g = room.game
  const ai = ensureAi(g)
  if (g.phase !== 'sheriff_transfer') throw new Error('当前非移交警徽阶段')
  if (actorOpenId !== ai.sheriffTransferFrom) throw new Error('仅出局警长可操作')
  await completeSheriffTransfer(room, null)
  await saveRoom(room)
  return { ok: true, needRefresh: true }
}

async function reportAction(event, actorOpenId) {
  let room = await getRoomById(event.roomId)
  if (!room || room.status !== 'playing') throw new Error('对局未进行中')
  if (!room.game || !room.game.ai || !room.game.ai.aiMode) {
    throw new Error('非 AI 主持模式')
  }

  await tickTimeout(room)
  room = (await getRoomById(event.roomId)) || room
  const g = room.game
  const ai = ensureAi(g)
  const action = String(event.action || '')
  const target = String(event.targetOpenId || '')
  const extra = event.extra || {}

  const myR = getRole(room, actorOpenId)
  const ph = g.phase

  if (action === 'transferSheriff' && ph === 'sheriff_transfer') {
    return await handleTransferSheriff(event, actorOpenId)
  }
  if (action === 'skipTransfer' && ph === 'sheriff_transfer') {
    return await handleSkipTransfer(event, actorOpenId)
  }

  if (action === 'finishSpeak' && ph === 'speak') {
    const cur = (ai.speakOrder || [])[ai.currentSpeakerIndex | 0]
    if (cur !== actorOpenId) throw new Error('未轮到你发言')
    await advanceSpeak(room)
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (action === 'withdraw' && ph === 'sheriff_withdraw') {
    return await handleWithdraw(event, actorOpenId)
  }

  if (ph === 'sheriff_signup' && (action === 'sheriff_run' || action === 'sheriff_skip')) {
    if (room.game.alive[actorOpenId] === false) throw new Error('已暂离')
    if (ai.sheriffWithdrawn && ai.sheriffWithdrawn[actorOpenId]) {
      throw new Error('已退水，不能再次上警')
    }
    ai.sheriffSignup[actorOpenId] = action === 'sheriff_run' ? 'run' : 'skip'
    const alive = alivePlayers(room)
    const allDone = alive.every((m) => ai.sheriffSignup[m.openId])
    if (allDone) {
      const r = finalizeSheriffSignup(room)
      if (r.next === 'speak') await dayAnnounceToSpeak(room)
      else if (r.next === 'withdraw') await startSheriffWithdraw(room)
      else await startSheriffSpeak(room)
    }
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (action === 'finishSheriffSpeak' && ph === 'sheriff_speak') {
    const cur = (ai.sheriffSpeakOrder || [])[ai.sheriffSpeakIndex | 0]
    if (cur !== actorOpenId) throw new Error('未轮到你警上发言')
    await advanceSheriffSpeak(room)
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (ph === 'sheriff_vote' && action === 'sheriff_vote') {
    if (room.game.alive[actorOpenId] === false) throw new Error('已暂离')
    if (!target) throw new Error('请选择候选人')
    if ((ai.sheriffCandidates || []).indexOf(target) < 0) {
      throw new Error('只能投票给上警玩家')
    }
    if (room.game.alive[target] === false) throw new Error('候选人已暂离')
    ai.sheriffVotes = { ...(ai.sheriffVotes || {}), [actorOpenId]: target }
    const alive = alivePlayers(room)
    const voted = Object.keys(ai.sheriffVotes).filter(
      (k) => ai.sheriffVotes[k] && room.game.alive[k] !== false
    ).length
    if (voted >= alive.length) {
      await advanceSheriffVote(room)
    }
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (ph === 'vote' && action === 'vote') {
    if (room.game.alive[actorOpenId] === false) throw new Error('已暂离')
    if (!target || target === actorOpenId) throw new Error('请选择他人')
    if (room.game.alive[target] === false) throw new Error('目标已暂离')
    ai.voteResults = { ...(ai.voteResults || {}), [actorOpenId]: target }
    const alive = alivePlayers(room)
    const voted = Object.keys(ai.voteResults).filter(
      (k) => ai.voteResults[k] && room.game.alive[k] !== false
    ).length
    if (voted >= alive.length) {
      await advanceVote(room)
    }
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (ph === 'hunter' && action === 'shoot') {
    if (ai.pendingHunter !== actorOpenId) throw new Error('非协定者环节')
    if (extra.decline === true) {
      await resolveHunterSkip(room)
    } else {
      await onHunterShot(room, target)
    }
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (myR === 'white_wolf' && (action === 'self_destruct' || action === 'boom_kill')) {
    if (ph !== 'speak' && ph !== 'vote' && ph !== 'day_announce') {
      throw new Error('仅白天可自爆')
    }
    if (action === 'self_destruct' && !target) {
      ai.whiteWolfBoomStep = 'pick'
      ai.whiteWolfBoomOpenId = actorOpenId
      resetPhaseTimer(ai, 15)
      g.publicLog = (g.publicLog || []).concat(['白狼王自爆，请选择带走对象'])
      await saveRoom(room)
      return { ok: true, needRefresh: true, needPick: true }
    }
    if (ai.whiteWolfBoomStep === 'pick' || action === 'boom_kill') {
      await whiteWolfSelfDestruct(room, actorOpenId, target)
      await saveRoom(room)
      return { ok: true, needRefresh: true }
    }
  }

  if (ph !== 'night') throw new Error('当前阶段不可操作')
  const step = (ai.nightSteps || [])[ai.nightStepIndex | 0]

  if (step === 'wolf' && action === 'kill' && isWolfRole(myR)) {
    if (room.game.alive[actorOpenId] === false) throw new Error('已暂离')
    if (!target) throw new Error('请选择目标')
    ai.wolfVotes = { ...(ai.wolfVotes || {}), [actorOpenId]: target }
    ai.actedWolves[actorOpenId] = true
    const wolves = aliveWolves(room)
    const voted = wolves.filter((w) => ai.wolfVotes[w.openId]).length
    if (voted >= wolves.length) {
      await advanceNightStep(room)
    }
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  if (step === 'seer' && action === 'check' && myR === 'seer') {
    if (!target || target === actorOpenId) throw new Error('请选择他人')
    ai.seerTarget = target
    ai.actedSeer = true
    const isW = isWolfRole(getRole(room, target))
    ai.seerResult = { target, isW, label: isW ? '暗位侧' : '村民侧' }
    await advanceNightStep(room)
    await saveRoom(room)
    return {
      ok: true,
      needRefresh: true,
      isW,
      label: ai.seerResult.label
    }
  }

  if (step === 'witch' && myR === 'witch') {
    if (action === 'save' && ai.witchPhaseStep === 1) {
      ai.witchSave = extra.save === true
      ai.actedWitchSave = true
      await advanceNightStep(room)
      await saveRoom(room)
      return { ok: true, needRefresh: true }
    }
    if (action === 'poison' && ai.witchPhaseStep === 2) {
      if (target) {
        if (target === actorOpenId) throw new Error('不能对自己')
        ai.witchPoisonTarget = target
      }
      ai.actedWitchPoison = true
      await advanceNightStep(room)
      await saveRoom(room)
      return { ok: true, needRefresh: true }
    }
  }

  if (step === 'guard' && action === 'guard' && myR === 'guard') {
    if (!target) throw new Error('请选择守护目标')
    if (ai.lastGuardTarget && ai.lastGuardTarget === target) {
      throw new Error('不能连续两夜守护同一人')
    }
    ai.guardTarget = target
    ai.actedGuard = true
    await advanceNightStep(room)
    await saveRoom(room)
    return { ok: true, needRefresh: true }
  }

  throw new Error('当前不可执行该操作')
}

async function getCurrentState(event, openId) {
  let ro = await getRoomById(event.roomId)
  if (!ro) throw new Error('聚会组无效')
  if (!(ro.members || []).some((m) => m.openId === openId)) {
    return { inRoom: false, myOpenId: openId }
  }
  let advanced = false
  if (ro.game && ro.game.ai && ro.game.ai.aiMode) {
    advanced = await tickTimeout(ro)
    if (advanced) ro = (await getRoomById(event.roomId)) || ro
  }
  const pub = buildPubFromRoom(ro)
  const view = buildPlayerView(ro, openId)
  return {
    ok: true,
    inRoom: true,
    advanced,
    state: pub,
    view,
    phase: pub.currentPhase,
    remainingSeconds: pub.remainingSeconds,
    nightStepIndex: pub.nightStepIndex,
    nightSteps: pub.nightSteps,
    currentSpeaker: pub.currentSpeakerOpenId,
    voteResults: pub.voteResults,
    gameEnded: ro.status === 'ended' || pub.currentPhase === 'end',
    winner: pub.winner || pub.winSide || '',
    needTransfer: !!pub.needTransfer,
    transferRemainingSeconds: pub.transferRemainingSeconds | 0,
    sheriffTransferFrom: pub.sheriffTransferFrom || ''
  }
}

async function advancePhase(event, openId) {
  const ro = await getRoomById(event.roomId)
  if (!ro || !ro.game || !ro.game.ai || !ro.game.ai.aiMode) {
    throw new Error('非 AI 局')
  }
  const g = ro.game
  const ai = ensureAi(g)
  const ph = g.phase
  if (ph === 'night') await advanceNightStep(ro)
  else if (ph === 'day_announce') await afterDayAnnounce(ro)
  else if (ph === 'sheriff_signup') {
    const r = finalizeSheriffSignup(ro)
    if (r.next === 'speak') await dayAnnounceToSpeak(ro)
    else if (r.next === 'withdraw') await startSheriffWithdraw(ro)
    else await startSheriffSpeak(ro)
  } else if (ph === 'sheriff_withdraw') await finishSheriffWithdrawWindow(ro)
  else if (ph === 'sheriff_speak') await advanceSheriffSpeak(ro)
  else if (ph === 'sheriff_vote') await advanceSheriffVote(ro)
  else if (ph === 'speak') await advanceSpeak(ro)
  else if (ph === 'vote') await advanceVote(ro)
  else if (ph === 'hunter') await resolveHunterSkip(ro)
  else if (ph === 'sheriff_transfer') await completeSheriffTransfer(ro, null)
  await saveRoom(ro)
  return { ok: true }
}

exports.main = async (event) => {
  try {
    const action = event.action
    const o = await getOpenId()
    if (action === 'startAIMode') {
      return await startAIMode(event, o)
    }
    if (action === 'reportAction') {
      return await reportAction(event, o)
    }
    if (action === 'getCurrentState') {
      return await getCurrentState(event, o)
    }
    if (action === 'advancePhase') {
      return await advancePhase(event, o)
    }
    if (action === 'transferSheriff') {
      return await handleTransferSheriff(event, o)
    }
    if (action === 'skipTransfer') {
      return await handleSkipTransfer(event, o)
    }
    if (action === 'withdraw') {
      return await handleWithdraw(event, o)
    }
    throw new Error('未知 action: ' + action)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}
