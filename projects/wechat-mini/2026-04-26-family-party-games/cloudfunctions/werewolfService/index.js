const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
function assertTestAction(e) {
  if (!e || !e._test) {
    throw new Error('test action denied')
  }
}
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/**
 * 云库 doc().set({ data }) 中禁止 _id / _openid（含嵌套）；公屏从 game 等对象拼出来时可能误带入。
 */
function omitIdDeep (x) {
  if (x == null) {
    return x
  }
  if (Array.isArray(x)) {
    return x.map(omitIdDeep)
  }
  if (typeof x === 'object') {
    if (x instanceof Date) {
      return x
    }
    if (Object.getPrototypeOf(x) !== Object.prototype) {
      return x
    }
    const o = {}
    for (const k of Object.keys(x)) {
      if (k === '_id' || k === '_openid') {
        continue
      }
      o[k] = omitIdDeep(x[k])
    }
    return o
  }
  return x
}
const {
  MAXN,
  DECK,
  MIN_PLAYERS,
  isWolfRole,
  membersOf,
  roomSeatCap,
  rolesForPlayerCount
} = require('./wolfDeck')
const R = 'werewolf_rooms'
const S = 'werewolf_state'
const MOCK_PREFIX = 'mock:ww:'
/** @deprecated 使用 membersOf；保留别名减少 diff */
const participantsOf = membersOf
const now = () => Date.now()
async function getOpenId() {
  return cloud.getWXContext().OPENID
}
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
function mk6() {
  return String(100000 + ((Math.random() * 900000) | 0))
}

function isMockOpenId(id) {
  return String(id || '').startsWith(MOCK_PREFIX)
}

function addOneMockMember(members, rid) {
  const ms = members || []
  const mockCount = ms.filter((m) => isMockOpenId(m.openId)).length
  const mockOid = MOCK_PREFIX + String(rid) + ':' + (mockCount + 1)
  return ms.concat([
    {
      openId: mockOid,
      nickName: '模拟玩家' + (mockCount + 1),
      avatarUrl: '',
      profileReady: true,
      isMock: true,
      joinedAt: now()
    }
  ])
}

async function getRoomById(id) {
  if (!id) {
    return null
  }
  const r = await db.collection(R).doc(String(id)).get()
  return r.data || null
}
async function getRoomByCode(code) {
  const c = String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  if (c.length !== 6) {
    return null
  }
  const r = await db
    .collection(R)
    .where({ roomCode: c, status: _.neq('ended') })
    .limit(1)
    .get()
  return r.data[0] || null
}
function nn(room, oid) {
  const m = (room.members || []).find((u) => u.openId === oid)
  return m ? m.nickName : '参与者'
}
function getRole(room, oid) {
  return (room.playerRoles || {})[oid] || ''
}

function getSheriffOpenIdManual(g) {
  return String((g && g.sheriffOpenId) || '')
}

function transferRemainingSecondsManual(g) {
  const end = (g && g.sheriffTransferTimeout) | 0
  if (!end) return 0
  return Math.max(0, Math.ceil((end - now()) / 1000))
}

/** 警长出局 → 移交阶段（手动局，15s 超时） */
function tryStartSheriffTransferManual(ro, deadSheriffOid, continueKind) {
  const g = ro.game
  if (!deadSheriffOid || getSheriffOpenIdManual(g) !== deadSheriffOid) return false
  g.sheriffTransferFrom = deadSheriffOid
  g.sheriffTransferPending = true
  g.sheriffTransferContinue = continueKind || ''
  g.sheriffTransferTimeout = now() + 15000
  g.phase = 'sheriff_transfer'
  g.publicLog = (g.publicLog || []).concat([
    '警长 ' +
      nn(ro, deadSheriffOid) +
      ' 出局，请在15秒内移交警徽（可交给存活玩家）'
  ])
  return true
}

async function completeSheriffTransferManual(ro, targetOid) {
  const g = ro.game
  if (g.phase !== 'sheriff_transfer' && !g.sheriffTransferPending) return
  const from = String(g.sheriffTransferFrom || getSheriffOpenIdManual(g) || '')
  g.sheriffTransferPending = false
  g.sheriffTransferFrom = ''
  g.sheriffTransferTimeout = 0
  const kind = g.sheriffTransferContinue || ''
  g.sheriffTransferContinue = ''

  let tid = String(targetOid || '').trim()
  if (tid && (tid === from || g.alive[tid] === false)) tid = ''
  if (tid) {
    g.sheriffOpenId = tid
    g.publicLog = (g.publicLog || []).concat([
      '警长将警徽移交给了 ' + nn(ro, tid)
    ])
  } else {
    g.sheriffOpenId = ''
    g.publicLog = (g.publicLog || []).concat(['警长未能移交警徽，警徽流失'])
  }
  resumeAfterSheriffTransferManual(ro, kind)
}

function resumeAfterSheriffTransferManual(ro, kind) {
  const g = ro.game
  if (checkWin(ro)) return

  if (kind === 'manual_day_announce') {
    g.phase = 'day_announce'
    return
  }
  if (kind === 'manual_vote_hunter') {
    g.phase = 'hunter'
    return
  }
  if (kind === 'manual_vote_night') {
    g.voteOpen = 0
    g.currentVotes = {}
    g.phase = 'night'
    g.day = (g.day | 0) + 1
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      lastGuardTarget: (g.night && g.night.lastGuardTarget) || '',
      wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
    }
    g.publicLog = (g.publicLog || []).concat(['第' + g.day + ' 夜。'])
    return
  }
  if (kind === 'manual_white_wolf_night') {
    g.voteOpen = 0
    g.currentVotes = {}
    g.day = (g.day | 0) + 1
    g.phase = 'night'
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      lastGuardTarget: (g.night && g.night.lastGuardTarget) || '',
      wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
    }
    g.publicLog = (g.publicLog || []).concat(['第' + g.day + ' 夜。'])
    return
  }
  if (kind === 'manual_hunter_after') {
    g.pendingHunter = null
    g.phase = 'night'
    g.day = (g.day | 0) + 1
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      lastGuardTarget: (g.night && g.night.lastGuardTarget) || '',
      wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
    }
    g.publicLog = (g.publicLog || []).concat(['第' + g.day + ' 夜。'])
  }
}

async function maybeExpireSheriffTransfer(ro) {
  const g = ro.game || {}
  if (g.phase !== 'sheriff_transfer' || !g.sheriffTransferPending) return false
  if (transferRemainingSecondsManual(g) > 0) return false
  await completeSheriffTransferManual(ro, null)
  await saveFullRoom(ro)
  return true
}

const DUR_SHERIFF_WITHDRAW_MS = 10000

function withdrawRemainingSecondsManual(g) {
  const end = (g && g.withdrawEndTime) | 0
  if (!end) return 0
  return Math.max(0, Math.ceil((end - now()) / 1000))
}

/** 手动局：报名结束后的候选人列表与下一阶段 */
function finalizeSheriffSignupManual(ro) {
  const g = ro.game
  const alive = membersOf(ro).filter((m) => g.alive[m.openId] !== false)
  alive.forEach((m) => {
    if (!g.sheriffSignup[m.openId]) g.sheriffSignup[m.openId] = 'skip'
  })
  g.sheriffElectionDone = true
  g.sheriffCandidates = alive
    .filter((m) => g.sheriffSignup[m.openId] === 'run')
    .map((m) => m.openId)
  if (g.sheriffCandidates.length === 0) {
    g.sheriffPhase = 'done'
    g.publicLog = (g.publicLog || []).concat(['无人上警，本局无警长'])
    return { next: 'speak' }
  }
  if (g.sheriffCandidates.length === 1) {
    g.sheriffPhase = 'done'
    g.sheriffOpenId = g.sheriffCandidates[0]
    g.publicLog = (g.publicLog || []).concat([
      nn(ro, g.sheriffOpenId) + ' 独自上警，当选警长'
    ])
    return { next: 'speak' }
  }
  g.publicLog = (g.publicLog || []).concat([
    '上警 ' +
      g.sheriffCandidates.length +
      ' 人：' +
      g.sheriffCandidates.map((id) => nn(ro, id)).join('、')
  ])
  return { next: 'withdraw' }
}

function startSheriffWithdrawManual(ro) {
  const g = ro.game
  g.sheriffPhase = 'withdraw'
  g.withdrawEndTime = now() + DUR_SHERIFF_WITHDRAW_MS
  g.phase = 'sheriff_withdraw'
  g.publicLog = (g.publicLog || []).concat([
    '退水窗口开启（10秒），上警玩家可选择退水'
  ])
}

function afterWithdrawManual(ro, endWindow) {
  const g = ro.game
  const cands = (g.sheriffCandidates || []).slice()
  const n = cands.length
  if (!endWindow && n >= 2) return { stayed: true }
  g.sheriffPhase = 'done'
  g.withdrawEndTime = 0
  if (n === 0) {
    g.sheriffOpenId = ''
    g.publicLog = (g.publicLog || []).concat(['退水结束后无人上警，本局无警长'])
    g.phase = 'speak'
    g.speakIndex = 0
    return { next: 'speak' }
  }
  if (n === 1) {
    g.sheriffOpenId = cands[0]
    g.publicLog = (g.publicLog || []).concat([
      nn(ro, cands[0]) + ' 成为唯一候选人，当选警长'
    ])
    g.phase = 'speak'
    g.speakIndex = 0
    return { next: 'speak' }
  }
  g.sheriffSpeakOrder = cands.slice()
  g.sheriffSpeakIndex = 0
  g.phase = 'sheriff_speak'
  g.sheriffPhase = 'speak'
  g.publicLog = (g.publicLog || []).concat(['警上发言开始'])
  return { next: 'sheriff_speak' }
}

async function maybeExpireSheriffWithdraw(ro) {
  const g = ro.game || {}
  if (g.phase !== 'sheriff_withdraw' || g.sheriffPhase !== 'withdraw') return false
  if (withdrawRemainingSecondsManual(g) > 0) return false
  afterWithdrawManual(ro, true)
  await saveFullRoom(ro)
  return true
}

function buildPubFromRoom(room) {
  if (!room || !room._id) {
    return null
  }
  const g = room.game || {}
  const al = g.alive || {}
  return {
    roomCode: room.roomCode,
    status: room.status,
    maxPlayers: room.maxPlayers,
    currentPhase: g.phase || 'lobby',
    day: g.day || 0,
    hostOpenId: room.hostOpenId || '',
    players: (room.members || []).map((m, i) =>
      Object.assign(jp.withProfileReadyFlag(m), {
        isHost: m.openId === room.hostOpenId,
        isAlive: al[m.openId] !== false,
        isSheriff: String(g.sheriffOpenId || '') === m.openId,
        seat: i + 1
      })
    ),
    sheriffOpenId: g.sheriffOpenId || '',
    sheriffElectionDone: !!g.sheriffElectionDone,
    sheriffCandidates: (g.sheriffCandidates || []).map((oid) => ({
      openId: oid,
      nickName: nn(room, oid)
    })),
    sheriffPhase: g.sheriffPhase || '',
    withdrawRemainingSeconds:
      g.phase === 'sheriff_withdraw' ? withdrawRemainingSecondsManual(g) : 0,
    publicLog: g.publicLog || [],
    lastNightReport: g.lastNightReport,
    speakIndex: g.speakIndex | 0,
    speakOrder: g.speakOrder || [],
    voteOpen: !!g.voteOpen,
    currentVotes: g.currentVotes || {},
    gameEnd: g.endReason,
    winSide: g.winSide,
    pendingHunter: g.pendingHunter,
    needTransfer: g.phase === 'sheriff_transfer' && !!g.sheriffTransferPending,
    transferRemainingSeconds:
      g.phase === 'sheriff_transfer' ? transferRemainingSecondsManual(g) : 0,
    sheriffTransferFrom: g.sheriffTransferFrom || '',
    updatedAt: now()
  }
}
async function setPub(room) {
  const doc = buildPubFromRoom(room)
  if (!doc) {
    return
  }
  const safe = omitIdDeep(doc)
  await db
    .collection(S)
    .doc(String(room._id))
    .set({ data: safe })
}
function buildPlayerView(ro, o) {
  if (!ro) {
    return {}
  }
  const pr = ro.playerRoles || {}
  const myR = pr[o]
  const g = ro.game || {}
  const al = g.alive || {}
  const wm = (ro.members || [])
    .filter((m) => isWolfRole(pr[m.openId]) && m.openId !== o)
    .map((m) => m.nickName)
  return {
    isHost: ro.hostOpenId === o,
    myOpenId: o,
    iAmAlive: al[o] !== false,
    myRole: myR,
    roomCode: ro.roomCode,
    maxPlayers: ro.maxPlayers,
    roomStatus: ro.status,
    phase: g.phase,
    day: g.day,
    night: g.night,
    alive: g.alive,
    publicLog: g.publicLog,
    lastNightReport: g.lastNightReport,
    gameEnd: g.endReason,
    winSide: g.winSide,
    players: (ro.members || []).map((m, i) =>
      Object.assign(jp.withProfileReadyFlag(m), {
        isAlive: al[m.openId] !== false,
        seat: i + 1
      })
    ),
    wolfMates: isWolfRole(myR) ? wm : [],
    seer: myR === 'seer' && g.night && g.night.seer ? g.night.seer : null,
    allRoles:
      ro.hostOpenId === o
        ? membersOf(ro).map((m) => ({
          o: m.openId,
          n: m.nickName,
          r: pr[m.openId]
        }))
        : null,
    speakIndex: g.speakIndex | 0,
    speakOrder: g.speakOrder || [],
    voteOpen: !!g.voteOpen,
    currentVotes: g.currentVotes || {},
    pendingHunter: g.pendingHunter,
    isSheriffCandidate: (g.sheriffCandidates || []).indexOf(o) >= 0
  }
}
async function doSyncState(event, o) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    throw new Error('无房间')
  }
  let ro = await getRoomById(rid)
  if (!ro) {
    throw new Error('聚会组无效或已结束')
  }
  if (!(ro.members || []).some((m) => m.openId === o)) {
    return { ok: 1, myOpenId: o, inRoom: false }
  }
  if (await maybeExpireSheriffTransfer(ro)) {
    ro = (await getRoomById(rid)) || ro
  }
  if (await maybeExpireSheriffWithdraw(ro)) {
    ro = (await getRoomById(rid)) || ro
  }
  const pub = buildPubFromRoom(ro)
  const view = buildPlayerView(ro, o)
  return {
    ok: 1,
    myOpenId: o,
    inRoom: true,
    isHost: ro.hostOpenId === o,
    state: pub,
    view
  }
}
function aggWolfVote(wvote) {
  const c = {}
  let best = 0
  let out = null
  Object.keys(wvote || {}).forEach((k) => {
    const t = wvote[k]
    c[t] = (c[t] || 0) + 1
    if (c[t] > best) {
      best = c[t]
      out = t
    }
  })
  return out
}
function checkWin(room) {
  const g = room.game
  const pr = room.playerRoles
  const al = g.alive || {}
  let w = 0
  let good = 0
  membersOf(room).forEach((m) => {
    if (al[m.openId] === false) {
      return
    }
    if (isWolfRole(pr[m.openId])) {
      w += 1
    } else if (pr[m.openId]) {
      good += 1
    }
  })
  if (w === 0) {
    g.phase = 'end'
    g.endReason = '暗位成员均已暂离，村民侧本环节可收束'
    g.winSide = 'good'
    room.status = 'ended'
    return true
  }
  if (w >= good) {
    g.phase = 'end'
    g.endReason = '暗位人数不少于村民侧，本环节收束'
    g.winSide = 'wolf'
    room.status = 'ended'
    return true
  }
  return false
}
async function saveFullRoom(room) {
  await db
    .collection(R)
    .doc(String(room._id))
    .update({
      data: {
        game: room.game,
        status: room.status,
        playerRoles: room.playerRoles,
        updatedAt: now()
      }
    })
  const fresh = await getRoomById(room._id)
  if (fresh) {
    await setPub(fresh)
  }
}
exports.main = async (event) => {
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}
async function run(event) {
  const action = event.action
  const o = await getOpenId()
  if (action === 'create') {
    let code = mk6()
    for (let i = 0; i < 16; i += 1) {
      const e = await getRoomByCode(code)
      if (!e) {
        break
      }
      code = mk6()
    }
    const d = {
      roomCode: code,
      hostOpenId: o,
      maxPlayers: 0,
      status: 'waiting',
      members: [
        {
          openId: o,
          nickName:
            event.nickName && String(event.nickName).trim().slice(0, 12)
              ? String(event.nickName).trim().slice(0, 12)
              : '房主',
          avatarUrl: String((event && event.avatarUrl) || '').trim(),
          joinedAt: now()
        }
      ],
      game: { phase: 'lobby', day: 0, publicLog: [] },
      createdAt: now(),
      updatedAt: now()
    }
    const { _id } = await db.collection(R).add({ data: d })
    const room = await getRoomById(_id)
    room._id = _id
    await setPub(room)
    return { roomId: _id, roomCode: code, myOpenId: o }
  }
  if (action === 'join') {
    const ro = event.roomId ? await getRoomById(event.roomId) : await getRoomByCode(event.roomCode)
    if (!ro) {
      throw new Error('聚会组无效或已结束')
    }
    if (ro.status !== 'waiting') {
      throw new Error('已开始，无法加入')
    }
    if ((ro.members || []).length >= roomSeatCap(ro)) {
      throw new Error('聚会组人数已满')
    }
    const ms = ro.members || []
    let next
    if (ms.some((u) => u.openId === o)) {
      next = ms.map((m) =>
        m.openId === o ? Object.assign({}, m, jp.mergeJoinFields(event, m)) : m
      )
    } else {
      next = ms.concat([
        Object.assign({ openId: o, joinedAt: now() }, jp.mergeJoinFields(event, {}))
      ])
    }
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { roomId: String(ro._id), roomCode: ro.roomCode, myOpenId: o }
  }
  if (action === 'setSize') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长/主持可设人数')
    }
    if (ro.status !== 'waiting') {
      throw new Error('本环节中不可改')
    }
    const n = parseInt(event.maxPlayers, 10) || 6
    if (MAXN.indexOf(n) < 0) {
      throw new Error('只支持 6/8/10/12 人')
    }
    if (participantsOf(ro).length > n) {
      throw new Error('参与者已超人数，请调整或另建聚会组')
    }
    await db
      .collection(R)
      .doc(String(event.roomId))
      .update({ data: { maxPlayers: n, updatedAt: now() } })
    await setPub(await getRoomById(event.roomId))
    return { maxPlayers: n }
  }
  if (action === 'addMockPlayer') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长可添加')
    }
    if (ro.status !== 'waiting') {
      throw new Error('仅等待阶段可添加')
    }
    const cap = roomSeatCap(ro)
    const ms = ro.members || []
    if (participantsOf(ro).length >= cap) {
      throw new Error('参与者已满')
    }
    if (ms.length >= roomSeatCap(ro)) {
      throw new Error('已满员')
    }
    const next = addOneMockMember(ms, ro._id)
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { ok: 1, added: next[next.length - 1].openId }
  }
  if (action === 'fillMockPlayers') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长可添加')
    }
    if (ro.status !== 'waiting') {
      throw new Error('仅等待阶段可添加')
    }
    const cap = roomSeatCap(ro)
    let next = ro.members || []
    let added = 0
    for (let i = 0; i < 12; i += 1) {
      if (participantsOf({ members: next, hostOpenId: ro.hostOpenId }).length >= cap) {
        break
      }
      if (next.length >= roomSeatCap(ro)) {
        break
      }
      next = addOneMockMember(next, ro._id)
      added += 1
    }
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { ok: 1, added }
  }
  if (action === 'start') {
    const ro = await getRoomById(event.roomId)
    if (!ro) {
      throw new Error('房间不存在')
    }
    if (!event._test && ro.hostOpenId !== o) {
      throw new Error('仅组长可开始')
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
    const g = {
      day: 1,
      phase: 'night',
      alive: al,
      sheriffOpenId: '',
      sheriffElectionDone: false,
      sheriffSignup: {},
      sheriffCandidates: [],
      sheriffPhase: 'signup',
      sheriffWithdrawn: {},
      withdrawEndTime: 0,
      sheriffSpeakOrder: [],
      sheriffSpeakIndex: 0,
      sheriffVotes: {},
      publicLog: ['第1夜。暗位选择关注对象、线索员查看、治愈者协助。完成后由主持点【结算入昼】。'],
      night: {
        wvote: {},
        wkill: null,
        seer: null,
        wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
      },
      lastNightReport: null,
      speakOrder: shuf(players.map((u) => u.openId)),
      speakIndex: 0,
      currentVotes: {},
      voteOpen: 0,
      endReason: '',
      winSide: '',
      pendingHunter: null
    }
    await db
      .collection(R)
      .doc(String(event.roomId))
      .update({
        data: {
          status: 'playing',
          playerRoles: pr,
          game: g,
          updatedAt: now()
        }
      })
    await setPub(await getRoomById(event.roomId))
    return { ok: true }
  }
  if (action === 'wWolf') {
    const ro = await getRoomById(event.roomId)
    if (
      !ro ||
      ro.status !== 'playing' ||
      ro.game.phase !== 'night' ||
      !isWolfRole(getRole(ro, o)) ||
      ro.game.alive[o] === false
    ) {
      throw new Error('当前不可选择关注目标')
    }
    const t = String(event.targetOpenId || '')
    if (!t) {
      throw new Error('请选择关注对象 openId')
    }
    if (ro.game.alive[t] === false) {
      throw new Error('请选择在场的参与者')
    }
    const wvote = (ro.game.night && ro.game.night.wvote) || {}
    wvote[o] = t
    const wkill = aggWolfVote(wvote) || t
    ro.game.night = { ...(ro.game.night || {}), wvote, wkill }
    await saveFullRoom(ro)
    return { ok: true, wkill }
  }
  if (action === 'wSeer') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'seer' || ro.game.alive[o] === false) {
      throw new Error('当前不可查看线索')
    }
    const t = String(event.targetOpenId || '')
    if (!t || t === o) {
      throw new Error('请选择他人')
    }
    if (ro.game.alive[t] === false) {
      throw new Error('已暂离')
    }
    const isW = isWolfRole(getRole(ro, t))
    ro.game.night = ro.game.night || {}
    ro.game.night.seer = { checker: o, target: t, isW, label: isW ? '倾向：暗位侧' : '倾向：村民侧' }
    await saveFullRoom(ro)
    return { isW, label: isW ? '暗位侧' : '村民侧' }
  }
  if (action === 'wWitch') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'witch' || ro.game.alive[o] === false) {
      throw new Error('当前不可使用治愈者能力')
    }
    const nk = ro.game.night || {}
    const wv = nk.wvote || {}
    const wkill = nk.wkill || aggWolfVote(wv)
    let wts = { ...(nk.wwitch || { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }) }
    if (event.save && wts.saveLeft) {
      if (wkill) {
        wts.saveOn = wkill
        wts.saveLeft = 0
      }
    }
    if (event.poison) {
      const pt = String(event.targetOpenId || '')
      if (wts.poisonLeft && pt && pt !== o) {
        wts.poisonOn = pt
        wts.poisonLeft = 0
      }
    }
    ro.game.night = { ...nk, wwitch: wts, wkill: wkill || nk.wkill }
    await saveFullRoom(ro)
    return { ok: true, knife: wkill, witch: wts }
  }
  if (action === 'wGuard') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'guard' || ro.game.alive[o] === false) {
      throw new Error('当前不可守护')
    }
    const t = String(event.targetOpenId || '')
    if (!t) {
      throw new Error('请选择守护对象')
    }
    const last = String((ro.game.night && ro.game.night.lastGuardTarget) || '')
    if (last && last === t) {
      throw new Error('不能连续两夜守护同一人')
    }
    ro.game.night = { ...(ro.game.night || {}), guardTarget: t }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'whiteWolfBoom') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || getRole(ro, o) !== 'white_wolf' || ro.game.alive[o] === false) {
      throw new Error('当前不可自爆')
    }
    const ph = ro.game.phase
    if (ph !== 'speak' && ph !== 'vote' && ph !== 'day_announce') {
      throw new Error('仅白天可自爆')
    }
    const t = String(event.targetOpenId || '')
    if (!t || t === o) {
      throw new Error('请选择带走对象')
    }
    if (ro.game.alive[t] === false) {
      throw new Error('目标已暂离')
    }
    const g = ro.game
    const sheriff = getSheriffOpenIdManual(g)
    const sheriffDead = sheriff && (sheriff === o || sheriff === t)
    g.alive[o] = false
    g.alive[t] = false
    g.publicLog = (g.publicLog || []).concat([
      '白狼王自爆，' + nn(ro, o) + ' 与 ' + nn(ro, t) + ' 同步暂离'
    ])
    g.voteOpen = 0
    g.currentVotes = {}
    if (checkWin(ro)) {
      await saveFullRoom(ro)
      return { ok: true }
    }
    if (sheriffDead && tryStartSheriffTransferManual(ro, sheriff, 'manual_white_wolf_night')) {
      ro.game = g
      await saveFullRoom(ro)
      return { ok: true }
    }
    g.day = (g.day | 0) + 1
    g.phase = 'night'
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      lastGuardTarget: (g.night && g.night.lastGuardTarget) || '',
      wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
    }
    g.publicLog = g.publicLog.concat(['第' + g.day + ' 夜。'])
    ro.game = g
    if (checkWin(ro)) {
      /* ended */
    }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostWolfSet') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持可补选关注意')
    }
    ro.game.night = { ...(ro.game.night || {}), wkill: String(event.targetOpenId || '') }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostResolveNight') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持可结算入昼')
    }
    if (ro.game.phase !== 'night') {
      throw new Error('非夜间')
    }
    const g = ro.game
    const pr = ro.playerRoles
    const prevAlive = { ...(g.alive || {}) }
    const al0 = { ...(g.alive || {}) }
    const nk = g.night || {}
    const wkill = nk.wkill || aggWolfVote(nk.wvote || {})
    const wt = nk.wwitch || { saveOn: null, poisonOn: null, saveLeft: 1, poisonLeft: 1 }
    const guardTarget = String(nk.guardTarget || '')
    const logp = []
    if (wkill) {
      const saved = wt.saveOn && wt.saveOn === wkill
      const guarded = guardTarget && guardTarget === wkill
      if (saved && guarded) {
        al0[wkill] = false
        logp.push(nn(ro, wkill) + ' 同守同救，仍暂离。')
      } else if (saved) {
        logp.push(nn(ro, wkill) + ' 已获缓解。')
      } else if (guarded) {
        logp.push(nn(ro, wkill) + ' 被守护。')
      } else {
        al0[wkill] = false
        logp.push('夜间关注后暂离：' + nn(ro, wkill))
      }
    }
    if (wt && wt.poisonOn) {
      const p = wt.poisonOn
      if (al0[p] !== false) {
        al0[p] = false
        logp.push('备用提醒后暂离：' + nn(ro, p))
      }
    }
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      guardTarget: '',
      lastGuardTarget: guardTarget || String(nk.lastGuardTarget || ''),
      wwitch: { saveLeft: wt.saveLeft, poisonLeft: wt.poisonLeft, saveOn: null, poisonOn: null }
    }
    g.alive = al0
    g.lastNightReport = logp
    const deadIds = Object.keys(al0).filter(
      (k) => prevAlive[k] !== false && al0[k] === false
    )
    const sheriffDead = deadIds.find((id) => getSheriffOpenIdManual(g) === id)
    ro.game = g
    if (checkWin(ro)) {
      await saveFullRoom(ro)
      return { over: ro.status === 'ended' }
    }
    if (sheriffDead && tryStartSheriffTransferManual(ro, sheriffDead, 'manual_day_announce')) {
      g.publicLog = (g.publicLog || []).concat(logp, ['天亮了。'])
      await saveFullRoom(ro)
      return { over: false }
    }
    g.phase = 'day_announce'
    g.publicLog = (g.publicLog || []).concat(logp, ['天亮了。'])
    if (checkWin(ro)) {
      /* ended */
    }
    await saveFullRoom(ro)
    return { over: ro.status === 'ended' }
  }
  if (action === 'wSheriffSignup') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'sheriff_signup') {
      throw new Error('当前非警长报名阶段')
    }
    if (ro.game.alive[o] === false) throw new Error('已暂离')
    ro.game.sheriffWithdrawn = ro.game.sheriffWithdrawn || {}
    if (ro.game.sheriffWithdrawn[o]) throw new Error('已退水，不能再次上警')
    const run = !!event.run
    ro.game.sheriffSignup = ro.game.sheriffSignup || {}
    ro.game.sheriffSignup[o] = run ? 'run' : 'skip'
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostSheriffToSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) throw new Error('仅主持')
    if (ro.game.phase !== 'sheriff_signup') throw new Error('当前非警长报名阶段')
    const r = finalizeSheriffSignupManual(ro)
    if (r.next === 'withdraw') startSheriffWithdrawManual(ro)
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostEndSheriffWithdraw') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) throw new Error('仅主持')
    const g = ro.game
    if (g.phase !== 'sheriff_withdraw') throw new Error('当前非退水窗口')
    afterWithdrawManual(ro, true)
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'withdraw') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'sheriff_withdraw') {
      throw new Error('当前非退水窗口')
    }
    const g = ro.game
    if ((g.sheriffCandidates || []).indexOf(o) < 0) {
      throw new Error('你未上警，无法退水')
    }
    g.sheriffCandidates = (g.sheriffCandidates || []).filter((id) => id !== o)
    g.sheriffWithdrawn = g.sheriffWithdrawn || {}
    g.sheriffWithdrawn[o] = true
    g.sheriffSignup = g.sheriffSignup || {}
    g.sheriffSignup[o] = 'withdrawn'
    g.publicLog = (g.publicLog || []).concat([nn(ro, o) + ' 退水'])
    afterWithdrawManual(ro, false)
    await saveFullRoom(ro)
    return { ok: true, candidateCount: (g.sheriffCandidates || []).length }
  }
  if (action === 'hostSheriffNextSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) throw new Error('仅主持')
    const g = ro.game
    g.sheriffSpeakIndex = (g.sheriffSpeakIndex | 0) + 1
    if (g.sheriffSpeakIndex >= (g.sheriffSpeakOrder || []).length) {
      g.phase = 'sheriff_vote'
      g.sheriffVotes = {}
      g.publicLog = (g.publicLog || []).concat(['警徽投票开始'])
    } else {
      g.publicLog = (g.publicLog || []).concat(['下一位警上发言'])
    }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostResolveSheriffVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) throw new Error('仅主持')
    const g = ro.game
    const sv = g.sheriffVotes || {}
    const tally = {}
    Object.keys(sv).forEach((v) => {
      const t = sv[v]
      if (t) tally[t] = (tally[t] || 0) + 1
    })
    let high = 0
    let winner = null
    let tie = false
    Object.keys(tally).forEach((k) => {
      if (tally[k] > high) {
        high = tally[k]
        winner = k
        tie = false
      } else if (tally[k] === high && high > 0) tie = true
    })
    if (tie) winner = null
    if (winner) {
      g.sheriffOpenId = winner
      g.publicLog = (g.publicLog || []).concat([nn(ro, winner) + ' 当选警长'])
    } else {
      g.publicLog = (g.publicLog || []).concat(['警徽投票无效，无警长'])
    }
    g.phase = 'speak'
    g.speakIndex = 0
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'sheriffVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.game.phase !== 'sheriff_vote' || ro.game.alive[o] === false) {
      throw new Error('当前不可投警徽')
    }
    const t = String(event.targetOpenId || '')
    if (!t || (ro.game.sheriffCandidates || []).indexOf(t) < 0) {
      throw new Error('请选择上警候选人')
    }
    ro.game.sheriffVotes = { ...(ro.game.sheriffVotes || {}), [o]: t }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostDawnToSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    if ((ro.game.day | 0) === 1 && !ro.game.sheriffElectionDone) {
      ro.game.phase = 'sheriff_signup'
      ro.game.sheriffSignup = {}
      ro.game.sheriffPhase = 'signup'
      ro.game.sheriffWithdrawn = {}
      ro.game.withdrawEndTime = 0
      ro.game.publicLog = (ro.game.publicLog || []).concat(['警长竞选：请选择是否上警'])
      await saveFullRoom(ro)
      return { ok: true }
    }
    ro.game.phase = 'speak'
    ro.game.speakIndex = 0
    ro.game.voteOpen = 0
    ro.game.currentVotes = {}
    ro.game.publicLog = (ro.game.publicLog || []).concat(['警下发言开始'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostNextSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    ro.game.speakIndex = (ro.game.speakIndex | 0) + 1
    ro.game.publicLog = (ro.game.publicLog || []).concat(['下一位发言。'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostStartVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    ro.game.phase = 'vote'
    ro.game.voteOpen = 1
    ro.game.currentVotes = {}
    ro.game.publicLog = (ro.game.publicLog || []).concat(['投票离场。'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'vote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'vote' || !ro.game.voteOpen || ro.game.alive[o] === false) {
      throw new Error('当前不可投')
    }
    const t0 = String(event.targetOpenId)
    if (!t0) {
      throw new Error('选择投票离场对象')
    }
    const cur = (ro.game.currentVotes || {}) || {}
    ro.game.currentVotes = { ...cur, [o]: t0 }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostResolveVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    const pr = ro.playerRoles
    const g = ro.game
    const cv = g.currentVotes || {}
    const sheriffOid = String(g.sheriffOpenId || '')
    const c = {}
    Object.keys(cv).forEach((k) => {
      const y = cv[k]
      const w = sheriffOid && k === sheriffOid ? 2 : 1
      c[y] = (c[y] || 0) + w
    })
    let high = 0
    let victim = null
    Object.keys(c).forEach((k) => {
      if (c[k] > high) {
        high = c[k]
        victim = k
      }
    })
    if (victim) {
      g.alive = g.alive || {}
      g.alive[victim] = false
      const logs = ['投票离场：' + nn(ro, victim) + '。']
      const wasSheriff = getSheriffOpenIdManual(g) === victim
      const isHunter = pr[victim] === 'hunter'
      g.publicLog = (g.publicLog || []).concat(logs)
      ro.game = g
      if (checkWin(ro)) {
        await saveFullRoom(ro)
        return { over: ro.status === 'ended' }
      }
      if (wasSheriff) {
        if (isHunter) g.pendingHunter = victim
        const cont = isHunter ? 'manual_vote_hunter' : 'manual_vote_night'
        if (tryStartSheriffTransferManual(ro, victim, cont)) {
          await saveFullRoom(ro)
          return { over: false }
        }
      }
      if (isHunter) {
        g.pendingHunter = victim
        g.phase = 'hunter'
      } else {
        g.voteOpen = 0
        g.currentVotes = {}
        g.phase = 'night'
        g.day = (g.day | 0) + 1
        g.publicLog = (g.publicLog || []).concat(['第' + (g.day || 0) + ' 夜。'])
        g.night = { wvote: {}, wkill: null, seer: null, wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null } }
      }
    } else {
      g.voteOpen = 0
    }
    ro.game = g
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { over: ro.status === 'ended' }
  }
  if (action === 'hunterShot') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'hunter' || o !== ro.game.pendingHunter) {
      throw new Error('协定者本环节不可操作')
    }
    const t1 = String(event.targetOpenId || '')
    if (!t1) {
      throw new Error('请选择一位参与者')
    }
    const g = ro.game
    if (g.alive[t1] === false) {
      throw new Error('目标已暂离')
    }
    g.alive[t1] = false
    g.publicLog = (g.publicLog || []).concat(['协定者邀请 ' + nn(ro, t1) + ' 同步暂离。'])
    if (getSheriffOpenIdManual(g) === t1) {
      ro.game = g
      if (checkWin(ro)) {
        await saveFullRoom(ro)
        return { ok: true }
      }
      if (tryStartSheriffTransferManual(ro, t1, 'manual_hunter_after')) {
        g.pendingHunter = null
        await saveFullRoom(ro)
        return { ok: true }
      }
    }
    g.pendingHunter = null
    g.phase = 'night'
    g.day = (g.day | 0) + 1
    g.night = { wvote: {}, wkill: null, seer: null, wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null } }
    ro.game = g
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'transferSheriff') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'sheriff_transfer') {
      throw new Error('当前非移交警徽阶段')
    }
    const g = ro.game
    if (o !== g.sheriffTransferFrom) throw new Error('仅出局警长可移交警徽')
    const t = String(event.targetOpenId || '')
    if (!t || t === o) throw new Error('请选择存活玩家')
    if (g.alive[t] === false) throw new Error('目标已暂离')
    await completeSheriffTransferManual(ro, t)
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { ok: true, sheriffOpenId: g.sheriffOpenId || '' }
  }
  if (action === 'skipTransfer') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'sheriff_transfer') {
      throw new Error('当前非移交警徽阶段')
    }
    if (o !== ro.game.sheriffTransferFrom) throw new Error('仅出局警长可操作')
    await completeSheriffTransferManual(ro, null)
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'getView') {
    const ro = await getRoomById(event.roomId)
    if (!ro) {
      return {}
    }
    return buildPlayerView(ro, o)
  }
  if (action === 'syncState') {
    return await doSyncState(event, o)
  }
  if (action === '__testSeedPlayers') {
    return await doTestSeedPlayers(event)
  }
  throw new Error('未知action ' + action)
}

async function doTestSeedPlayers(event) {
  assertTestAction(event)
  const ro = event.roomId
    ? await getRoomById(event.roomId)
    : await getRoomByCode(String(event.roomCode || '').replace(/\D/g, ''))
  if (!ro) {
    throw new Error('房间不存在')
  }
  if (ro.status !== 'waiting') {
    throw new Error('对局已开始，无法注入测试玩家')
  }
  let ms = ro.members || []
  const incoming = event.players || []
  for (let i = 0; i < incoming.length; i += 1) {
    const p = incoming[i] || {}
    const oid = String(p.openId || '').trim()
    if (!oid || ms.some((m) => m && m.openId === oid)) {
      continue
    }
    if (ms.length >= roomSeatCap(ro)) {
      break
    }
    ms = ms.concat([
      Object.assign(
        { openId: oid, joinedAt: now() },
        jp.mergeJoinFields(p, {})
      )
    ])
  }
  await db
    .collection(R)
    .doc(String(ro._id))
    .update({ data: { members: ms, updatedAt: now() } })
  const fresh = await getRoomById(ro._id)
  await setPub(fresh)
  return {
    ok: true,
    playerCount: participantsOf(fresh).length,
    roomId: String(ro._id),
    roomCode: fresh.roomCode
  }
}
