/**
 * 谁是卧底（6 位房 + uc_rooms / uc_players / uc_state）
 * 与旧版 roomService.rooms(4 位) 数据隔离
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const UC_R = 'uc_rooms'
const UC_P = 'uc_players'
const UC_S = 'uc_state'

const PAIRS = [
  ['饺子', '包子'],
  ['牛奶', '豆浆'],
  ['苹果', '梨'],
  ['口红', '唇膏'],
  ['手机', '平板'],
  ['咖啡', '奶茶'],
  ['老师', '教练'],
  ['火锅', '麻辣烫'],
  ['电影', '电视剧'],
  ['公交车', '地铁'],
  ['书包', '行李箱'],
  ['羽毛球', '网球'],
  ['太阳', '月亮'],
  ['雨伞', '雨衣'],
  ['冰箱', '空调'],
  ['面包', '蛋糕'],
  ['西瓜', '哈密瓜'],
  ['猫', '狗'],
  ['飞机', '高铁'],
  ['医生', '护士']
]
const t = () => Date.now()
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
      .map((p) => ({
        openId: p.openId,
        nickName: p.nickName,
        isAlive: !!p.isAlive,
        seat: p.seat,
        isHost: !!p.isHost,
        wordAck: !!p.wordAck
      })),
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
    lastElim: r.lastElim,
    gameResult: r.gameResult,
    winSide: r.winSide
  }
}
async function assertHost(rid) {
  const o = await oid()
  const room = await gRoom(rid)
  if (!room || room.hostOpenId !== o) {
    throw new Error('仅房主可执行')
  }
  return o
}
exports.main = async (event) => {
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
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
      maxPlayers: 6,
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
    await db.collection(UC_P).add({
      data: {
        roomId: _id,
        openId: o,
        nickName: '房主',
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
    return { roomId: _id, roomCode: code }
  }
  if (a === 'join') {
    const code = String(e.roomCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (code.length !== 6) {
      throw new Error('需6位房间码')
    }
    const r0 = await gRoomByCode(code)
    if (!r0) {
      throw new Error('房间不存在')
    }
    if (r0.status !== 'waiting') {
      throw new Error('已开始，无法进房')
    }
    const pl0 = await gPlayers(r0._id)
    const max = r0.maxPlayers | 0 || 6
    if (pl0.length >= max) {
      throw new Error('满员')
    }
    const nm = String(e.nickName || '')
      .trim()
      .slice(0, 12) || '参与者'
    if (pl0.some((p) => p.openId === o)) {
      await db
        .collection(UC_P)
        .where({ roomId: r0._id, openId: o })
        .get()
        .then((res) => {
          if (res.data[0] && res.data[0]._id) {
            return db
              .collection(UC_P)
              .doc(res.data[0]._id)
              .update({ data: { nickName: nm, updatedAt: t() } })
          }
        })
    } else {
      const seat = pl0.length
      await db.collection(UC_P).add({
        data: {
          roomId: r0._id,
          openId: o,
          nickName: nm,
          isHost: false,
          seat,
          role: '',
          word: '',
          isAlive: true,
          wordAck: false,
          currentVote: null,
          joinedAt: t()
        }
      })
    }
    const r = await gRoom(r0._id)
    const pl2 = await gPlayers(r0._id)
    await setState(r, pl2)
    return { roomId: String(r0._id) }
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
  if (a === 'startGame') {
    const rid = e.roomId
    await assertHost(rid)
    const room = await gRoom(rid)
    if (room.status !== 'waiting') {
      throw new Error('已开局')
    }
    const pl = await gPlayers(rid)
    if (pl.length < 3) {
      throw new Error('至少3人')
    }
    if (pl.length !== (room.maxPlayers | 0) && (room.maxPlayers | 0) > 0) {
      throw new Error('人未满' + (room.maxPlayers | 0) + '，暂不可开')
    }
    const p0 = PAIRS[((Math.random() * PAIRS.length) | 0) % PAIRS.length]
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
    const rMerge = {
      status: 'playing',
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
      publicLog: ['发词完成，大家查看词语。']
    }
    await saveR(Object.assign({}, await gRoom(rid), rMerge))
    return { ok: 1, pair: p0 }
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
    const rnew = (room.publicLog || []).concat([nn(pls, out) + (isUc ? ' 是卧底' : ' 是平民') + '，被放逐。'])
    if (isUc) {
      const room2 = {
        currentPhase: 'ended',
        status: 'finished',
        gameResult: 'civilian',
        winSide: 'good',
        lastElim: { o: out, u: 1, round: room.currentRound | 0 },
        publicLog: rnew.concat(['本环节以普通词侧描述收束。'])
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
          publicLog: rnew.concat(['仅剩两人且持不同词仍在场，本环节以特殊词侧收束。'])
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
  throw new Error('未知' + a)
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
    .map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      isAlive: !!p.isAlive,
      seat: p.seat,
      isHost: !!p.isHost,
      wordAck: !!p.wordAck
    }))
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
        r: p.role,
        o: p.openId,
        dead: !p.isAlive
      }))
      : null
  }
}
