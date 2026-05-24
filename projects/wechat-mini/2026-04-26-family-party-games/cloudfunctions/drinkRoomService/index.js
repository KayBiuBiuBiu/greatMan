/**
 * 趣味抽签 / 同场同步：6 位聚会组 + drink_rooms / drink_players / drink_gameState / drink_votes
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const R = 'drink_rooms'
const P = 'drink_players'
const S = 'drink_gameState'
const V = 'drink_votes'

const COUNTDOWN_MS = 10000
const VOTE_MS = 30000
const AGENT_AUTH = 'family-party-agent-v1'
let _currentEvent = null
const t = () => Date.now()

function agentOk() {
  return !!(_currentEvent && _currentEvent._agentAuth === AGENT_AUTH)
}

function c6() {
  return String(100000 + ((Math.random() * 900000) | 0))
}
function randomDrinkSips() {
  return 1 + ((Math.random() * 10) | 0)
}
function shuf(a) {
  const x = a.slice()
  for (let i = x.length - 1; i > 0; i -= 1) {
    const j = (Math.random() * (i + 1)) | 0
    const t0 = x[i]
    x[i] = x[j]
    x[j] = t0
  }
  return x
}
function omitIdDeep(x) {
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
async function oid() {
  return cloud.getWXContext().OPENID
}
async function gRoom(id) {
  const d = await db
    .collection(R)
    .doc(String(id))
    .get()
  return d.data
}
async function gRoomByCode(c) {
  const code = String(c || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  if (code.length !== 6) {
    return null
  }
  const r = await db
    .collection(R)
    .where({ roomCode: code, status: _.neq('finished') })
    .limit(1)
    .get()
  return r.data[0] || null
}
async function gPlayers(rid) {
  const r = await db
    .collection(P)
    .where({ roomId: String(rid) })
    .get()
  return (r.data || []).slice()
}
async function gState(roomId) {
  try {
    const d = await db
      .collection(S)
      .doc(String(roomId))
      .get()
    return d.data || null
  } catch (e) {
    return null
  }
}
function byJoin(a) {
  return a.slice().sort((x, y) => (x.joinedAt | 0) - (y.joinedAt | 0))
}
function nn(pl, o) {
  const f = (pl || []).find((p) => p.openId === o)
  return f ? f.nickName : '参与者'
}
function recomputeTally(m) {
  const tall = {}
  for (const k of Object.keys(m || {})) {
    const to = m[k]
    if (to == null || to === '' || to === 'ABSTAIN') {
      continue
    }
    tall[to] = (tall[to] | 0) + 1
  }
  return tall
}
function buildPub(room, players, g) {
  if (!room || !room._id) {
    return null
  }
  const st = g || {}
  const sorted = byJoin(players || [])
  const m = st.votesByVoter && typeof st.votesByVoter === 'object' ? st.votesByVoter : {}
  const cast = sorted.filter(
    (p) => m[p.openId] != null && m[p.openId] !== ''
  ).length
  const need = sorted.length
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    roomName: room.roomName || '',
    status: room.status,
    hostOpenId: room.hostOpenId,
    currentRound: st.currentRound | 0,
    phase: st.phase || 'waiting',
    countdownEndsAt: st.countdownEndsAt | 0,
    targetOpenId: st.targetOpenId || '',
    targetNick: st.targetNick || '',
    votingDeadline: st.votingDeadline | 0,
    votesByVoter: m,
    voteTally: st.voteTally && typeof st.voteTally === 'object' ? st.voteTally : recomputeTally(m),
    voteProgress: { cast, need },
    publicPlayers: sorted.map((p) =>
      Object.assign(jp.withProfileReadyFlag(p), { isHost: !!p.isHost })
    ),
    result: st.result != null ? st.result : null,
    updatedAt: t()
  }
}
async function setFullState(room, stPatch) {
  if (!room || !room._id) {
    return
  }
  const prev = (await gState(room._id)) || {}
  const nst = Object.assign({}, prev, stPatch, { updatedAt: t() })
  const pl = await gPlayers(room._id)
  const pub = buildPub(room, pl, nst)
  if (pub) {
    await db
      .collection(S)
      .doc(String(room._id))
      .set({ data: omitIdDeep(pub) })
  }
}
function computeResultFromVotes(targetOpenId, pls, list) {
  const tOid = String(targetOpenId)
  const targetSips = (list || []).filter(
    (x) => x && x.toOpenId && String(x.toOpenId) === tOid
  ).length
  const wrongVoters = []
  for (const v of list || []) {
    if (!v || !v.toOpenId) {
      continue
    }
    if (String(v.toOpenId) === tOid) {
      continue
    }
    wrongVoters.push({
      openId: v.fromOpenId,
      nickName: nn(pls, v.fromOpenId),
      sips: 1
    })
  }
  return {
    targetOpenId: tOid,
    targetNick: nn(pls, tOid),
    targetSips,
    wrongVoters
  }
}
async function assertInRoom(rid) {
  if (agentOk()) {
    const room = await gRoom(rid)
    const pls = await gPlayers(rid)
    if (!room) {
      throw new Error('房间不存在')
    }
    return {
      openId: room.hostOpenId || '',
      players: pls,
      self: null,
      agent: true
    }
  }
  const o = await oid()
  const pls = await gPlayers(rid)
  const p = pls.find((q) => q.openId === o)
  if (!p) {
    throw new Error('你不在本房间')
  }
  return { openId: o, players: pls, self: p }
}
async function assertHostRid(rid) {
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('房间不存在')
  }
  if (agentOk()) {
    return { room, openId: room.hostOpenId }
  }
  const o = await oid()
  if (room.hostOpenId !== o) {
    throw new Error('仅房主可执行')
  }
  return { room, openId: o }
}

exports.main = async (event) => {
  _currentEvent = event
  try {
    return await run(event)
  } catch (e) {
    console.error('[drinkRoomService]', e)
    return { errMsg: e && e.message ? e.message : String(e) }
  } finally {
    _currentEvent = null
  }
}
async function run(event) {
  const action = (event && event.action) || ''
  if (action === 'getOpenId') {
    return { openId: await oid() }
  }
  if (action === 'create') {
    return doCreate(event)
  }
  if (action === 'join') {
    return doJoin(event)
  }
  if (action === 'setRoomName') {
    return doSetRoomName(event)
  }
  if (action === 'startRound') {
    return doStartRound(event)
  }
  if (action === 'revealRinger') {
    return doRevealRinger(event)
  }
  if (action === 'submitVote') {
    return doSubmitVote(event)
  }
  if (action === 'submitAbstain') {
    return doSubmitAbstain(event)
  }
  if (action === 'finalizeVoting') {
    return doFinalizeVoting(event)
  }
  if (action === 'nextRound') {
    return doNextRound(event)
  }
  if (action === 'getView') {
    return doGetView(event)
  }
  if (action === 'syncState') {
    return doSyncState(event)
  }
  if (action === 'rerollRinger') {
    return doRerollRinger(event)
  }
  return { errMsg: '未知 action' }
}

async function doSyncState(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const o = await oid()
  const room = await gRoom(rid)
  if (!room) {
    return { errMsg: '房间不存在' }
  }
  const pls = byJoin(await gPlayers(rid))
  if (!pls.find((p) => p.openId === o)) {
    return { ok: 1, myOpenId: o, inRoom: false }
  }
  const st = (await gState(rid)) || {}
  const pub = buildPub(room, pls, st)
  if (!pub) {
    return { errMsg: '状态异常' }
  }
  return {
    ok: 1,
    myOpenId: o,
    inRoom: true,
    isHost: room.hostOpenId === o,
    state: pub
  }
}

async function doGetView(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const { openId } = await assertInRoom(rid)
  const room = await gRoom(rid)
  if (!room) {
    return { errMsg: '房间不存在' }
  }
  const st = (await gState(rid)) || {}
  const pls = byJoin(await gPlayers(rid))
  const out = {
    ok: 1,
    phase: st.phase || 'waiting',
    myOpenId: openId,
    isHost: room.hostOpenId === openId,
    currentRound: st.currentRound | 0,
    targetOpenId: st.targetOpenId || '',
    targetNick: st.targetNick || ''
  }
  if (room.hostOpenId !== openId || st.phase !== 'voting') {
    return out
  }
  const tally =
    (st.voteTally && typeof st.voteTally === 'object' && st.voteTally) ||
    recomputeTally(st.votesByVoter || {})
  const voteStats = pls
    .map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      count: tally[p.openId] | 0
    }))
    .sort((a, b) => (b.count | 0) - (a.count | 0))
  out.voteStats = voteStats
  return out
}

async function doRerollRinger(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const { room } = await assertHostRid(rid)
  const st = (await gState(rid)) || {}
  if (st.phase !== 'voting') {
    return { errMsg: '当前非投票阶段' }
  }
  const pls = byJoin(await gPlayers(rid))
  if (pls.length < 1) {
    return { errMsg: '无参与者' }
  }
  const rno = st.currentRound | 0
  const old = st.targetOpenId || ''
  let pool = pls
  if (pls.length > 1 && old) {
    const rest = pls.filter((p) => p.openId !== old)
    if (rest.length) {
      pool = rest
    }
  }
  const one = shuf(pool)[0]
  const deadline = t() + VOTE_MS
  const votes = await db
    .collection(V)
    .where({ roomId: String(rid), round: rno })
    .get()
  for (const row of votes.data || []) {
    if (row && row._id) {
      try {
        await db.collection(V).doc(row._id).remove()
      } catch (e) {
        /* ignore */
      }
    }
  }
  const room2 = await gRoom(rid)
  await setFullState(room2, {
    targetOpenId: one.openId,
    targetNick: one.nickName,
    votingDeadline: deadline,
    votesByVoter: {},
    voteTally: {}
  })
  return {
    ok: 1,
    targetOpenId: one.openId,
    targetNick: one.nickName,
    votingDeadline: deadline
  }
}

async function doCreate(event) {
  const o = await oid()
  const nick0 = (event && event.nickName) || '房主'
  const av0 = String((event && event.avatarUrl) || '').trim()
  for (let k = 0; k < 12; k += 1) {
    const code = c6()
    if (await gRoomByCode(code)) {
      continue
    }
    const add = await db.collection(R).add({
      data: {
        roomCode: code,
        roomName: '聚会组',
        hostOpenId: o,
        status: 'open',
        currentRound: 0,
        createdAt: t(),
        updatedAt: t()
      }
    })
    const id = add._id
    await db.collection(P).add({
      data: {
        roomId: String(id),
        openId: o,
        nickName: String(nick0).trim().slice(0, 12) || '房主',
        avatarUrl: av0,
        isHost: true,
        joinedAt: t()
      }
    })
    const room = await gRoom(id)
    await setFullState(room, {
      currentRound: 0,
      phase: 'waiting',
      votesByVoter: {},
      voteTally: {},
      result: null,
      targetOpenId: '',
      targetNick: '',
      countdownEndsAt: 0,
      votingDeadline: 0
    })
    return { roomId: String(id), roomCode: code, myOpenId: o }
  }
  return { errMsg: '重试' }
}
async function doJoin(event) {
  const o = await oid()
  const code = String((event && event.roomCode) || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  if (code.length !== 6) {
    return { errMsg: '请输入 6 位数字口令' }
  }
  const room = await gRoomByCode(code)
  if (!room || !room._id) {
    return { errMsg: '房间不存在' }
  }
  const pls0 = await gPlayers(room._id)
  const exist = pls0.find((p) => p.openId === o)
  if (exist) {
    if (exist._id) {
      const fields = jp.mergeJoinFields(event, exist)
      await db
        .collection(P)
        .doc(String(exist._id))
        .update({
          data: Object.assign(fields, { updatedAt: t() })
        })
    }
    const room2 = await gRoom(room._id)
    const st0 = (await gState(String(room._id))) || {}
    await setFullState(room2, st0)
    const pls1 = await gPlayers(room._id)
    return {
      roomId: String(room._id),
      roomCode: room.roomCode,
      joined: true,
      myOpenId: o,
      playerCount: pls1.length
    }
  }
  await db.collection(P).add({
    data: Object.assign(
      {
        roomId: String(room._id),
        openId: o,
        isHost: false,
        joinedAt: t()
      },
      jp.mergeJoinFields(event, {})
    )
  })
  const room2 = await gRoom(room._id)
  const st0 = (await gState(String(room._id))) || {}
  await setFullState(room2, st0)
  const pls1 = await gPlayers(room._id)
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    myOpenId: o,
    playerCount: pls1.length
  }
}
async function doSetRoomName(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  await assertHostRid(rid)
  const name = String((event && event.roomName) || '聚会组')
    .trim()
    .slice(0, 20)
  await db
    .collection(R)
    .doc(String(rid))
    .update({ data: { roomName: name, updatedAt: t() } })
  const r2 = await gRoom(rid)
  const st = (await gState(rid)) || {}
  await setFullState(r2, Object.assign({}, st, { roomName: r2.roomName }))
  return { ok: true, roomName: r2.roomName }
}
async function doStartRound(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const { room } = await assertHostRid(rid)
  const pls = byJoin(await gPlayers(rid))
  if (pls.length < 2) {
    return { errMsg: '至少 2 人才能开' }
  }
  const st0 = (await gState(rid)) || {}
  if (st0.phase === 'countdown') {
    return { errMsg: '请先等待本回合倒计时结束' }
  }
  if (st0.phase === 'result') {
    return { errMsg: '请先点「下一轮」再开始' }
  }
  const nextR = (room.currentRound | 0) + 1
  await db
    .collection(R)
    .doc(rid)
    .update({ data: { currentRound: nextR, status: 'playing', updatedAt: t() } })
  const dline = t() + COUNTDOWN_MS
  const room2 = await gRoom(rid)
  await setFullState(room2, {
    currentRound: nextR,
    phase: 'countdown',
    countdownEndsAt: dline,
    targetOpenId: '',
    targetNick: '',
    votingDeadline: 0,
    votesByVoter: {},
    voteTally: {},
    result: null
  })
  return { ok: true, currentRound: nextR, countdownEndsAt: dline }
}
async function doRevealRinger(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  await assertInRoom(rid)
  const room = await gRoom(rid)
  const st = (await gState(rid)) || {}
  if (st.phase !== 'countdown') {
    return { ok: true, phase: st.phase, idle: true }
  }
  const pls = byJoin(await gPlayers(rid))
  if (pls.length < 1) {
    return { errMsg: '无参与者' }
  }
  const one = shuf(pls)[0]
  const drinkSips = randomDrinkSips()
  const result = {
    targetOpenId: one.openId,
    targetNick: one.nickName,
    drinkSips
  }
  const room2 = await gRoom(rid)
  await setFullState(room2, {
    phase: 'result',
    targetOpenId: one.openId,
    targetNick: one.nickName,
    votingDeadline: 0,
    votesByVoter: {},
    voteTally: {},
    result
  })
  return {
    ok: true,
    targetOpenId: one.openId,
    targetNick: one.nickName,
    drinkSips,
    result
  }
}
async function doSubmitVote(event) {
  const rid = String((event && event.roomId) || '')
  const to = String((event && event.toOpenId) || '')
  if (!rid || !to) {
    return { errMsg: '参数不足' }
  }
  const { openId, players: pls } = await assertInRoom(rid)
  const st = (await gState(rid)) || {}
  if (st.phase !== 'voting') {
    return { errMsg: '当前非投票' }
  }
  if (t() > (st.votingDeadline | 0) + 500) {
    return { errMsg: '投票已结束' }
  }
  const pids = new Set(pls.map((p) => p.openId))
  if (!pids.has(to)) {
    return { errMsg: '非本聚会组成员' }
  }
  if (st.votesByVoter && st.votesByVoter[openId] === 'ABSTAIN') {
    return { errMsg: '已选弃权' }
  }
  const rno = st.currentRound | 0
  if (rno < 1) {
    return { errMsg: '尚未开始本环节' }
  }
  const existing = await db
    .collection(V)
    .where({ roomId: String(rid), round: rno, fromOpenId: openId })
    .limit(1)
    .get()
  if (existing.data && existing.data.length) {
    return { errMsg: '已投过' }
  }
  await db.collection(V).add({
    data: {
      roomId: String(rid),
      round: rno,
      fromOpenId: openId,
      toOpenId: to,
      createdAt: t()
    }
  })
  const m = Object.assign({}, (st.votesByVoter && { ...st.votesByVoter }) || {}, {
    [openId]: to
  })
  const room2 = await gRoom(rid)
  await setFullState(room2, { votesByVoter: m, voteTally: recomputeTally(m) })
  return { ok: true }
}
async function doSubmitAbstain(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const { openId } = await assertInRoom(rid)
  const st = (await gState(rid)) || {}
  if (st.phase !== 'voting') {
    return { errMsg: '当前非投票' }
  }
  if (t() > (st.votingDeadline | 0) + 500) {
    return { errMsg: '投票已结束' }
  }
  const rno = st.currentRound | 0
  const exVote = await db
    .collection(V)
    .where({ roomId: String(rid), round: rno, fromOpenId: openId })
    .limit(1)
    .get()
  if (exVote.data && exVote.data.length) {
    return { errMsg: '已投过' }
  }
  const m = Object.assign({}, (st.votesByVoter && { ...st.votesByVoter }) || {}, {
    [openId]: 'ABSTAIN'
  })
  const room2 = await gRoom(rid)
  await setFullState(room2, { votesByVoter: m, voteTally: recomputeTally(m) })
  return { ok: true }
}
async function doFinalizeVoting(event) {
  const rid = String((event && event.roomId) || '')
  const force = !!(event && event.force)
  if (!rid) {
    return { errMsg: '无房间' }
  }
  if (force) {
    await assertHostRid(rid)
  } else {
    await assertInRoom(rid)
  }
  const st = (await gState(rid)) || {}
  if (st.phase !== 'voting') {
    return { ok: true, phase: st.phase, idle: true }
  }
  const pls0 = byJoin(await gPlayers(rid))
  const m0 = (st.votesByVoter && { ...st.votesByVoter }) || {}
  const committed0 = pls0.filter(
    (p) => m0[p.openId] != null && m0[p.openId] !== ''
  ).length
  const allIn = pls0.length
  const now = t()
  if (
    !force &&
    now < (st.votingDeadline | 0) - 300 &&
    !(committed0 >= allIn && allIn > 0)
  ) {
    return { errMsg: '未到时' }
  }
  if (!st.targetOpenId) {
    return { errMsg: '无响者' }
  }
  const rno = st.currentRound | 0
  const vres = await db
    .collection(V)
    .where({ roomId: String(rid), round: rno })
    .get()
  const pls = await gPlayers(rid)
  const result = computeResultFromVotes(st.targetOpenId, pls, vres.data)
  const room2 = await gRoom(rid)
  await setFullState(room2, { phase: 'result', result })
  return { ok: true, result }
}
async function doNextRound(event) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    return { errMsg: '无房间' }
  }
  const { room } = await assertHostRid(rid)
  const g = (await gState(rid)) || {}
  if (g.phase === 'countdown') {
    return { errMsg: '请先等待本回合结束' }
  }
  if (g.phase === 'waiting') {
    return { ok: true, idle: true }
  }
  if (g.phase !== 'result') {
    return { errMsg: '无待结算' }
  }
  await setFullState(room, {
    phase: 'waiting',
    targetOpenId: '',
    targetNick: '',
    result: null,
    votesByVoter: {},
    voteTally: {},
    countdownEndsAt: 0,
    votingDeadline: 0
  })
  return { ok: true, phase: 'waiting' }
}
