/**
 * 谁是卧底（6 位房 + uc_rooms / uc_players / uc_state）
 * 与旧版 roomService.rooms(4 位) 数据隔离
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const UC_R = 'uc_rooms'
const UC_P = 'uc_players'
const UC_S = 'uc_state'
const MAX_ROOM_PLAYERS = 12

const AGENT_AUTH = 'family-party-agent-v1'
let _currentEvent = null
const t = () => Date.now()

function agentOk() {
  return !!(_currentEvent && _currentEvent._agentAuth === AGENT_AUTH)
}

function assertTestAction(event) {
  if (!event || event._test !== true) {
    throw new Error('测试接口未授权')
  }
}

function roomJoinCap(room) {
  const fixed = room && (room.maxPlayers | 0)
  if (fixed > 0) {
    return Math.min(fixed, MAX_ROOM_PLAYERS)
  }
  return MAX_ROOM_PLAYERS
}

async function oid() {
  return cloud.getWXContext().OPENID
}
function c6() {
  return String(100000 + ((Math.random() * 900000) | 0))
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
/**
 * 云库 doc().set({ data }) 中禁止出现 _id / _openid（含任意嵌套）；从 DB 读回的对象子字段里可能带 _id。
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
async function gRoom(id) {
  const d = await db
    .collection(UC_R)
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
    .collection(UC_R)
    .where({ roomCode: code, status: _.neq('finished') })
    .limit(1)
    .get()
  return r.data[0] || null
}
async function gPlayers(rid) {
  const r = await db
    .collection(UC_P)
    .where({ roomId: String(rid) })
    .get()
  return r.data || []
}
function nn(pl, o) {
  const f = (pl || []).find((p) => p.openId === o)
  return f ? f.nickName : '参与者'
}

function parseJsonObject(text) {
  const raw = String(text || '').trim()
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw)
  } catch (e) {
    const m = raw.match(/\{[\s\S]*\}/)
    if (m) {
      try {
        return JSON.parse(m[0])
      } catch (e2) {}
    }
  }
  return null
}

function pickText(obj, keys) {
  for (let i = 0; i < keys.length; i += 1) {
    const v = obj && obj[keys[i]]
    if (v != null && String(v).trim()) {
      return String(v).trim().slice(0, 12)
    }
  }
  return ''
}

async function fetchAiPair() {
  const system =
    '你是聚会小游戏「谁是卧底」的出题助手。只返回 JSON，不要解释。词对必须适合全年龄线下聚会，两个词相似但可区分，避免敏感、低俗、重复。'
  const prompt =
    '请生成 1 组谁是卧底词对，难度中等。返回格式严格为：{"civilianWord":"平民词","undercoverWord":"卧底词"}。每个词 2 到 6 个中文字符。'
  const res = await cloud.callFunction({
    name: 'aiPartyService',
    data: {
      action: 'chat',
      system: system,
      prompt: prompt
    }
  })
  const body = (res && res.result) || {}
  if (body.errMsg) {
    throw new Error(body.errMsg)
  }
  const obj = parseJsonObject(body.text)
  const civ = pickText(obj, ['civilianWord', 'civilian', 'word1'])
  const uc = pickText(obj, ['undercoverWord', 'undercover', 'word2'])
  if (!civ || !uc || civ === uc) {
    throw new Error('AI 词对无效')
  }
  return [civ, uc]
}

async function resetRoomForRematch(rid) {
  const pl = await gPlayers(rid)
  for (const p of pl) {
    await db
      .collection(UC_P)
      .doc(p._id)
      .update({
        data: {
          isAlive: true,
          wordAck: false,
          currentVote: null,
          role: '',
          word: '',
          updatedAt: t()
        }
      })
  }
}

async function dealUndercoverRound(rid, room, pl, opts) {
  const o = opts || {}
  let p0
  if (o._test) {
    // 测试模式：使用本地数据，避免 AI 超时
    p0 = ['香蕉', '黄瓜']
  } else {
    p0 = await fetchAiPair()
  }
  const wCiv = p0[0]
  const wUc = p0[1]
  const pSh = shuf(pl)
  for (let j = 0; j < pSh.length; j += 1) {
    const p = pSh[j]
    const isUc = j === 0
    const word = isUc ? wUc : wCiv
    const role = isUc ? 'undercover' : 'civilian'
    await db
      .collection(UC_P)
      .doc(p._id)
      .update({
        data: {
          role,
          word,
          isAlive: true,
          wordAck: false,
          currentVote: null
        }
      })
  }
  const prevLog = o.appendLog ? room.publicLog || [] : []
  const logLine = o.logLine || '发词完成，大家查看词语。'
  const rMerge = {
    status: 'playing',
    pendingPair: null,
    currentRound: 1,
    currentPhase: 'word',
    pair: p0,
    speakIndex: 0,
    speakOrder: shuf(
      pSh
        .filter((x) => x.isAlive)
        .map((x) => x.openId)
    ),
    tieBreakOids: [],
    gameResult: null,
    winSide: null,
    lastElim: null,
    publicLog: o.rematch ? [logLine] : prevLog.concat([logLine])
  }
  await saveR(Object.assign({}, await gRoom(rid), rMerge))
  const rAfter = await gRoom(rid)
  const plAfter = await gPlayers(rid)
  await setState(rAfter, plAfter)
  return { ok: 1, pair: p0 }
}
async function setState(room, players) {
  const g = gPub(room, players)
  if (!g) {
    return
  }
  const safe = omitIdDeep(g)
  await db
    .collection(UC_S)
    .doc(String(room._id))
    .set({ data: safe })
}
function gPub(room, players) {
  if (!room || !room._id) {
    return null
  }
  const pl = players || []
  const alive = pl.filter((p) => p.isAlive)
  const ph0 = room.currentPhase || ''
  const needVote =
    ph0 === 'vote' || ph0 === 'vote_tie' ? alive.length : 0
  const cast = needVote
    ? alive.filter((p) => p.currentVote).length
    : 0
  return {
    roomCode: room.roomCode,
    roomId: String(room._id),
    status: room.status,
    currentPhase: room.currentPhase || 'waiting',
    currentRound: room.currentRound | 0,
    maxPlayers: room.maxPlayers,
    hostOpenId: room.hostOpenId,
    publicPlayers: pl
      .slice()
      .sort((a, b) => (a.seat | 0) - (b.seat | 0))
      .map((p) =>
        Object.assign(jp.withProfileReadyFlag(p), {
          isAlive: !!p.isAlive,
          seat: p.seat,
          isHost: !!p.isHost,
          wordAck: !!p.wordAck
        })
      ),
    speakIndex: room.speakIndex | 0,
    speakOrder: room.speakOrder || [],
    tieOids: room.tieBreakOids || [],
    voteProgress: { cast, need: needVote ? needVote : 0 },
    publicLog: room.publicLog || [],
    lastElim: room.lastElim,
    gameResult: room.gameResult,
    winSide: room.winSide,
    updatedAt: t()
  }
}
async function saveR(room) {
  await db
    .collection(UC_R)
    .doc(String(room._id))
    .update({ data: { ...stripRoomForDb(room), updatedAt: t() } })
  const pl = await gPlayers(room._id)
  await setState(room, pl)
}
function stripRoomForDb(r) {
  return {
    roomCode: r.roomCode,
    hostOpenId: r.hostOpenId,
    maxPlayers: r.maxPlayers,
    status: r.status,
    currentRound: r.currentRound,
    currentPhase: r.currentPhase,
    publicLog: r.publicLog,
    speakIndex: r.speakIndex,
    speakOrder: r.speakOrder,
    tieBreakOids: r.tieBreakOids,
    pair: r.pair,
    pendingPair: r.pendingPair,
    lastElim: r.lastElim,
    gameResult: r.gameResult,
    winSide: r.winSide
  }
}
async function assertHost(rid) {
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('房间不存在')
  }
  if (agentOk()) {
    return room.hostOpenId
  }
  const o = await oid()
  if (room.hostOpenId !== o) {
    throw new Error('仅房主可执行')
  }
  return o
}
exports.main = async (event) => {
  _currentEvent = event
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  } finally {
    _currentEvent = null
  }
}
async function run(e) {
  const a = e.action
  const o = await oid()
  if (a === 'create') {
    let code = c6()
    for (let i = 0; i < 16; i += 1) {
      if (!(await gRoomByCode(code))) {
        break
      }
      code = c6()
    }
    const room = {
      roomCode: code,
      hostOpenId: o,
      maxPlayers: 0,
      status: 'waiting',
      currentRound: 0,
      currentPhase: 'waiting',
      publicLog: [],
      speakIndex: 0,
      speakOrder: [],
      tieBreakOids: [],
      createdAt: t(),
      updatedAt: t()
    }
    const { _id } = await db.collection(UC_R).add({ data: room })
    const row = { ...room, _id }
    const hostNick =
      e.nickName && String(e.nickName).trim().slice(0, 12)
        ? String(e.nickName).trim().slice(0, 12)
        : '房主'
    const hostAv = String((e && e.avatarUrl) || '').trim()
    await db.collection(UC_P).add({
      data: {
        roomId: _id,
        openId: o,
        nickName: hostNick,
        avatarUrl: hostAv,
        isHost: true,
        seat: 0,
        role: '',
        word: '',
        isAlive: true,
        wordAck: false,
        currentVote: null,
        joinedAt: t()
      }
    })
    const pl = await gPlayers(_id)
    await setState(Object.assign(row, { _id }), pl)
    return { roomId: _id, roomCode: code, myOpenId: o }
  }
  if (a === 'join') {
    const code = String(e.roomCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (code.length !== 6) {
      throw new Error('需 6 位数字口令')
    }
    const r0 = await gRoomByCode(code)
    if (!r0) {
      throw new Error('房间不存在')
    }
    if (r0.status !== 'waiting') {
      throw new Error('已开始，无法进房')
    }
    const pl0 = await gPlayers(r0._id)
    const cap = roomJoinCap(r0)
    if (pl0.length >= cap) {
      throw new Error('满员')
    }
    const existUc = pl0.find((p) => p.openId === o)
    if (existUc) {
      await db
        .collection(UC_P)
        .where({ roomId: r0._id, openId: o })
        .get()
        .then((res) => {
          if (res.data[0] && res.data[0]._id) {
            return db
              .collection(UC_P)
              .doc(res.data[0]._id)
              .update({
                data: Object.assign(jp.mergeJoinFields(e, existUc), {
                  updatedAt: t()
                })
              })
          }
        })
    } else {
      const seat = pl0.length
      await db.collection(UC_P).add({
        data: Object.assign(
          {
            roomId: r0._id,
            openId: o,
            isHost: false,
            seat,
            role: '',
            word: '',
            isAlive: true,
            wordAck: false,
            currentVote: null,
            joinedAt: t()
          },
          jp.mergeJoinFields(e, {})
        )
      })
    }
    const r = await gRoom(r0._id)
    const pl2 = await gPlayers(r0._id)
    await setState(r, pl2)
    return { roomId: String(r0._id), roomCode: r.roomCode, myOpenId: o }
  }
  if (a === 'setConfig') {
    const rid = e.roomId
    await assertHost(rid)
    const n = Math.max(4, Math.min(12, parseInt(e.maxPlayers, 10) || 6))
    const room = await gRoom(rid)
    if (room.status !== 'waiting') {
      throw new Error('本环节中无法改')
    }
    const pl0 = await gPlayers(rid)
    if (pl0.length > n) {
      throw new Error('人数已超，请踢人后再减')
    }
    await db
      .collection(UC_R)
      .doc(String(rid))
      .update({ data: { maxPlayers: n, updatedAt: t() } })
    const r2 = await gRoom(rid)
    const pl2 = await gPlayers(rid)
    await setState(r2, pl2)
    return { maxPlayers: n }
  }
  if (a === 'setCustomPair') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (!room || room.status !== 'waiting') {
      throw new Error('仅等待阶段可设词')
    }
    const civ = String(e.civilianWord || '')
      .trim()
      .slice(0, 12)
    const uc = String(e.undercoverWord || '')
      .trim()
      .slice(0, 12)
    if (!civ || !uc) {
      throw new Error('词语无效')
    }
    if (civ === uc) {
      throw new Error('两词不能相同')
    }
    await db
      .collection(UC_R)
      .doc(String(rid))
      .update({
        data: {
          pendingPair: [civ, uc],
          updatedAt: t()
        }
      })
    return { civilianWord: civ, undercoverWord: uc }
  }
  if (a === 'startGame' || a === 'playAgain') {
    const rid = e.roomId
    await assertHost(rid)
    let room = await gRoom(rid)
    const isRematch = a === 'playAgain'
    if (isRematch) {
      if (room.currentPhase !== 'ended' && room.status !== 'finished') {
        throw new Error('本局未结束')
      }
      await resetRoomForRematch(rid)
      room = await gRoom(rid)
    } else if (room.status !== 'waiting') {
      throw new Error('已开局')
    }
    const pl = await gPlayers(rid)
    if (pl.length < 3) {
      throw new Error('至少3人')
    }
    return await dealUndercoverRound(rid, room, pl, {
      rematch: isRematch,
      appendLog: isRematch,
      logLine: isRematch ? '新一轮开始，大家查看词语。' : '发词完成，大家查看词语。',
      _test: e._test
    })
  }
  if (a === 'ackWord') {
    const rid = e.roomId
    const pls = await gPlayers(rid)
    const p = pls.find((q) => q.openId === o)
    if (!p || p.isAlive === false) {
      throw new Error('无效')
    }
    await db
      .collection(UC_P)
      .doc(p._id)
      .update({ data: { wordAck: true, updatedAt: t() } })
    const r = await gRoom(rid)
    const pl2 = await gPlayers(rid)
    await setState(r, pl2)
    return { ok: 1 }
  }
  if (a === 'hostToDiscuss') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (room.currentPhase !== 'word') {
      throw new Error('非发词阶段')
    }
    const pl2 = await gPlayers(rid)
    const all = pl2.filter((p) => p.isAlive).every((p) => p.wordAck)
    if (!all) {
      throw new Error('还有人未点已读')
    }
    const so = shuf(
      pl2
        .filter((p) => p.isAlive)
        .map((p) => p.openId)
    )
    const room2 = {
      currentPhase: 'discuss',
      speakIndex: 0,
      speakOrder: so,
      publicLog: (room.publicLog || []).concat(['开始讨论。'])
    }
    await saveR(Object.assign({}, await gRoom(rid), room2))
    return { ok: 1 }
  }
  if (a === 'hostNextSpeak') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (room.currentPhase !== 'discuss') {
      throw new Error('非讨论')
    }
    const ord = room.speakOrder || []
    const n = (room.speakIndex | 0) + 1
    if (n >= ord.length) {
      throw new Error('已到最后一位，请点发起投票')
    }
    const room2 = { speakIndex: n, publicLog: (room.publicLog || []).concat(['下一位。']) }
    await saveR(Object.assign({}, await gRoom(rid), room2))
    return { ok: 1, speakIndex: n }
  }
  if (a === 'startVote') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (room.currentPhase !== 'discuss') {
      throw new Error('请在讨论后发起')
    }
    for (const p of await gPlayers(rid)) {
      if (p.isAlive) {
        await db
          .collection(UC_P)
          .doc(p._id)
          .update({ data: { currentVote: null } })
      }
    }
    const room2 = {
      currentPhase: 'vote',
      tieBreakOids: [],
      publicLog: (room.publicLog || []).concat(['投票放逐。'])
    }
    await saveR(Object.assign({}, await gRoom(rid), room2))
    return { ok: 1 }
  }
  if (a === 'startTieVote') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (room.currentPhase !== 'vote_tie') {
      throw new Error('无平票')
    }
    const pl0 = await gPlayers(rid)
    for (const p of pl0) {
      if (p.isAlive) {
        await db
          .collection(UC_P)
          .doc(p._id)
          .update({ data: { currentVote: null } })
      }
    }
    const room2 = { publicLog: (room.publicLog || []).concat(['平票，请再投。']) }
    await saveR(Object.assign({}, await gRoom(rid), room2))
    return { ok: 1 }
  }
  if (a === 'submitVote') {
    const rid = e.roomId
    const t0 = String(e.targetOpenId || '')
    if (!t0) {
      throw new Error('请选择')
    }
    const pls = await gPlayers(rid)
    const me = pls.find((p) => p.openId === o)
    const room = await gRoom(rid)
    const ph = room.currentPhase
    if (!me || me.isAlive === false) {
      throw new Error('无投票权')
    }
    if (ph !== 'vote' && ph !== 'vote_tie') {
      throw new Error('非投票阶段')
    }
    if (ph === 'vote' && t0 === o) {
      throw new Error('勿投自己')
    }
    if (ph === 'vote_tie') {
      const tb = room.tieBreakOids || []
      if (tb.length && tb.indexOf(t0) < 0) {
        throw new Error('只许投平票者')
      }
    }
    const tPl = pls.find((p) => p.openId === t0)
    if (!tPl || tPl.isAlive === false) {
      throw new Error('目标已出局')
    }
    if (me.currentVote) {
      throw new Error('已投票')
    }
    await db
      .collection(UC_P)
      .doc(me._id)
      .update({ data: { currentVote: t0, updatedAt: t() } })
    const r = await gRoom(rid)
    const pl2 = await gPlayers(rid)
    await setState(r, pl2)
    return { ok: 1 }
  }
  if (a === 'endVote') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    const pls = (await gPlayers(rid)).slice()
    const ph = room.currentPhase
    if (ph !== 'vote' && ph !== 'vote_tie') {
      throw new Error('非投票中')
    }
    const alive = pls.filter((p) => p.isAlive)
    for (const v of alive) {
      if (!v.currentVote) {
        throw new Error('未全员投票')
      }
    }
    const c = {}
    if (ph === 'vote_tie') {
      const tb = room.tieBreakOids || []
      for (const v of alive) {
        const t1 = v.currentVote
        if (tb.length && tb.indexOf(t1) < 0) {
          throw new Error('有非法票')
        }
        c[t1] = (c[t1] | 0) + 1
      }
    } else {
      for (const v of alive) {
        const t1 = v.currentVote
        c[t1] = (c[t1] | 0) + 1
      }
    }
    const sorted = Object.keys(c).map((k) => ({ o: k, n: c[k] }))
    sorted.sort((a, b) => b.n - a.n)
    if (!sorted.length) {
      throw new Error('无票')
    }
    const top = sorted[0].n
    const topList = sorted.filter((x) => x.n === top)
    if (ph === 'vote' && topList.length > 1) {
      const tids = topList.map((x) => x.o)
      for (const p0 of pls) {
        await db
          .collection(UC_P)
          .doc(p0._id)
          .update({ data: { currentVote: null } })
      }
      const room2 = {
        currentPhase: 'vote_tie',
        tieBreakOids: tids,
        publicLog: (room.publicLog || []).concat(['平票，对 ' + tids.length + ' 人再投。'])
      }
      await saveR(Object.assign({}, await gRoom(rid), room2))
      return { tie: 1, targets: tids }
    }
    if (ph === 'vote_tie' && topList.length > 1) {
      for (const p0 of pls) {
        await db
          .collection(UC_P)
          .doc(p0._id)
          .update({ data: { currentVote: null } })
      }
      const plAlive = (await gPlayers(rid)).filter((p) => p.isAlive)
      const nOrder2 = shuf(plAlive.map((p) => p.openId))
      const room2 = {
        currentPhase: 'discuss',
        speakIndex: 0,
        speakOrder: nOrder2,
        tieBreakOids: [],
        publicLog: (room.publicLog || []).concat(['平票仍同票，本轮无人出局。'])
      }
      await saveR(Object.assign({}, await gRoom(rid), room2))
      return { tie: 0, out: 0, stillTie: 1 }
    }
    const out = topList[0].o
    const vOut = pls.find((p) => p.openId === out)
    if (!vOut) {
      throw new Error('异常')
    }
    vOut.isAlive = false
    vOut.isUC = vOut.role === 'undercover'
    await db
      .collection(UC_P)
      .doc(vOut._id)
      .update({ data: { isAlive: false, currentVote: null } })
    for (const p0 of pls) {
      await db
        .collection(UC_P)
        .doc(p0._id)
        .update({ data: { currentVote: null } })
    }
    const isUc = vOut.role === 'undercover'
    const rnew = (room.publicLog || []).concat([nn(pls, out) + ' 被放逐。'])
    if (isUc) {
      const room2 = {
        currentPhase: 'ended',
        status: 'finished',
        gameResult: 'civilian',
        winSide: 'good',
        lastElim: { o: out, u: 1, round: room.currentRound | 0 },
        publicLog: rnew.concat(['本局结束。'])
      }
      await saveR(Object.assign({}, await gRoom(rid), room2))
      return { over: 1, out, wasUndercover: 1 }
    }
    const plA = await gPlayers(rid)
    const alive2 = plA.filter((p) => p.isAlive)
    if (alive2.length === 2) {
      const uLeft = alive2.filter((p) => p.role === 'undercover').length
      if (uLeft >= 1) {
        const room2 = {
          currentPhase: 'ended',
          status: 'finished',
          gameResult: 'undercover',
          winSide: 'bad',
          lastElim: { o: out, u: 0, round: room.currentRound | 0 },
          publicLog: rnew.concat(['本局结束。'])
        }
        await saveR(Object.assign({}, await gRoom(rid), room2))
        return { over: 1, out, wasUndercover: 0 }
      }
    }
    const nRound = (room.currentRound | 0) + 1
    const nOrder = shuf(
      (await gPlayers(rid))
        .filter((p) => p.isAlive)
        .map((p) => p.openId)
    )
    const room2 = {
      currentRound: nRound,
      currentPhase: 'discuss',
      speakIndex: 0,
      speakOrder: nOrder,
      tieBreakOids: [],
      lastElim: { o: out, u: 0, round: room.currentRound | 0 },
      publicLog: rnew.concat(['第' + nRound + ' 轮，继续讨论。'])
    }
    await saveR(Object.assign({}, await gRoom(rid), room2))
    return { over: 0, out, wasUndercover: 0 }
  }
  if (a === 'getView') {
    return await gView(e.roomId, o)
  }
  if (a === 'syncState') {
    return await doSyncState(e.roomId, o)
  }
  if (a === '__testSeedPlayers') {
    return await doTestSeedPlayers(e)
  }
  if (a === '__testSyncSnapshot') {
    return await doTestSyncSnapshot(e)
  }
  throw new Error('未知' + a)
}

async function doTestSyncSnapshot(e) {
  assertTestAction(e)
  const r0 = e.roomId ? await gRoom(e.roomId) : await gRoomByCode(e.roomCode)
  if (!r0) {
    throw new Error('房间不存在')
  }
  const pl = await gPlayers(r0._id)
  const host = pl.find((p) => p.isHost) || pl[0]
  const hostOid = host ? host.openId : ''
  const view = await gView(r0._id, hostOid)
  return {
    ok: true,
    state: gPub(r0, pl),
    view,
    roomId: String(r0._id),
    roomCode: r0.roomCode
  }
}

async function doTestSeedPlayers(e) {
  assertTestAction(e)
  const r0 = e.roomId ? await gRoom(e.roomId) : await gRoomByCode(e.roomCode)
  if (!r0) {
    throw new Error('房间不存在')
  }
  if (r0.status !== 'waiting') {
    throw new Error('对局已开始，无法注入测试玩家')
  }
  let pl0 = await gPlayers(r0._id)
  const incoming = e.players || []
  for (let i = 0; i < incoming.length; i += 1) {
    const p = incoming[i] || {}
    const oid = String(p.openId || '').trim()
    if (!oid || pl0.some((x) => x.openId === oid)) {
      continue
    }
    if (pl0.length >= roomJoinCap(r0)) {
      break
    }
    const seat = pl0.length
    await db.collection(UC_P).add({
      data: Object.assign(
        {
          roomId: r0._id,
          openId: oid,
          isHost: false,
          seat,
          role: '',
          word: '',
          isAlive: true,
          wordAck: false,
          currentVote: null,
          joinedAt: t()
        },
        jp.mergeJoinFields(p, {})
      )
    })
    pl0 = await gPlayers(r0._id)
  }
  const r = await gRoom(r0._id)
  const pl2 = await gPlayers(r0._id)
  await setState(r, pl2)
  return { ok: true, playerCount: pl2.length, roomId: String(r0._id), roomCode: r.roomCode }
}

async function doSyncState(rid, o) {
  const id = String(rid || '')
  if (!id) {
    throw new Error('无房间')
  }
  const room = await gRoom(id)
  if (!room) {
    throw new Error('房间不存在')
  }
  const pls = await gPlayers(id)
  if (!pls.find((p) => p.openId === o)) {
    return { ok: 1, myOpenId: o, inRoom: false }
  }
  const pub = gPub(room, pls)
  const view = await gView(id, o)
  return {
    ok: 1,
    myOpenId: o,
    inRoom: true,
    isHost: room.hostOpenId === o,
    state: pub,
    view
  }
}
async function gView(rid, o) {
  const room = await gRoom(rid)
  if (!room) {
    return {}
  }
  const pls = await gPlayers(rid)
  const me = pls.find((p) => p.openId === o)
  const isHost = room.hostOpenId === o
  const ord = room.speakOrder || []
  const sp = ord[room.speakIndex | 0]
  const al = pls.filter((p) => p.isAlive)
  const wAcked = al.filter((p) => p.wordAck).length
  const wNeed = al.length
  const phx = room.currentPhase || ''
  const voteOptions = []
  if ((phx === 'vote' || phx === 'vote_tie') && me && me.isAlive) {
    const tbo = room.tieBreakOids || []
    for (const p of pls) {
      if (!p.isAlive || p.openId === o) {
        continue
      }
      if (phx === 'vote_tie' && tbo.length && tbo.indexOf(p.openId) < 0) {
        continue
      }
      voteOptions.push({ openId: p.openId, nickName: p.nickName })
    }
  }
  const alive0 = pls.filter((p) => p.isAlive)
  const needV =
    phx === 'vote' || phx === 'vote_tie' ? alive0.length : 0
  const castV = needV
    ? alive0.filter((p) => p.currentVote).length
    : 0
  const publicPlayers = pls
    .slice()
    .sort((a, b) => (a.seat | 0) - (b.seat | 0))
    .map((p) =>
      Object.assign(jp.withProfileReadyFlag(p), {
        isAlive: !!p.isAlive,
        seat: p.seat,
        isHost: !!p.isHost,
        wordAck: !!p.wordAck
      })
    )
  return {
    roomCode: room.roomCode,
    maxPlayers: room.maxPlayers,
    isHost,
    isAlive: me ? me.isAlive : false,
    myRole: me ? me.role : '',
    myWord: me ? me.word : '',
    wordAck: me ? me.wordAck : 0,
    hasVoted: me && me.isAlive && !!me.currentVote,
    currentVote: me && me.isAlive ? me.currentVote : null,
    myOpenId: o,
    amSpeaking: phx === 'discuss' && me && me.isAlive && sp === o,
    speakIndex: room.speakIndex | 0,
    speakOrder: ord,
    currentSpeaker: sp,
    wordProgress: { acked: wAcked, need: wNeed },
    voteOptions,
    phase: phx,
    currentRound: room.currentRound,
    publicLog: room.publicLog,
    publicPlayers,
    voteProgress: { cast: castV, need: needV },
    allRoles: isHost
      ? pls.map((p) => ({
        n: p.nickName,
        w: p.word || '',
        o: p.openId,
        dead: !p.isAlive
      }))
      : null
  }
}
