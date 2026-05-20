const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command
const { pickPool, BY_ID, WORDS } = require('./words')

const R = 'draw_rooms'
const P = 'draw_players'
const S = 'draw_gameState'
const C = 'draw_canvas'

const t = () => Date.now()

function c6 () {
  return String(100000 + ((Math.random() * 900000) | 0))
}
function shuf (a) {
  const x = a.slice()
  for (let i = x.length - 1; i > 0; i -= 1) {
    const j = (Math.random() * (i + 1)) | 0
    const t0 = x[i]
    x[i] = x[j]
    x[j] = t0
  }
  return x
}
function normGuess (s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/\s/g, '')
}
function normW (o) {
  if (!o || o.w == null) {
    return ''
  }
  return String(o.w)
    .trim()
    .toLowerCase()
    .replace(/\s/g, '')
}
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

async function oid () {
  return cloud.getWXContext().OPENID
}
async function gRoom (id) {
  const d = await db
    .collection(R)
    .doc(String(id))
    .get()
  return d.data
}
async function gRoomByCode (code) {
  const c = String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  if (c.length !== 6) {
    return null
  }
  const r = await db
    .collection(R)
    .where({ roomCode: c, status: _.neq('finished') })
    .limit(1)
    .get()
  return r.data[0] || null
}
async function gPlayers (rid) {
  const r = await db
    .collection(P)
    .where({ roomId: String(rid) })
    .get()
  return r.data || []
}
function sortPlayers (arr) {
  return arr
    .slice()
    .sort((a, b) => (a.joinedAt | 0) - (b.joinedAt | 0))
}
function drawerForRound (players, round, total) {
  const s = sortPlayers(players)
  if (!s.length) {
    return { openId: '', nick: '' }
  }
  const ix = ((round | 0) - 1 + 1000 * s.length) % s.length
  return { openId: s[ix].openId, nick: s[ix].nickName }
}

async function gState (roomId) {
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
async function setState (room, patch) {
  if (!room || !room._id) {
    return
  }
  const prev = (await gState(room._id)) || {}
  const g = Object.assign({}, prev, patch)
  const pls = await gPlayers(room._id)
  const pub = buildPub(room, pls, g)
  await db
    .collection(S)
    .doc(String(room._id))
    .set({ data: omitIdDeep(pub) })
}

function buildPub (room, players, st) {
  const g = st || {}
  const sorted = sortPlayers(players)
    .slice()
    .sort((a, b) => (b.score | 0) - (a.score | 0))
  const drow = g.currentDrawerOpenId
    ? sorted.find((p) => p.openId === g.currentDrawerOpenId)
    : null
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    status: room.status,
    hostOpenId: room.hostOpenId,
    totalRounds: room.totalRounds | 0,
    currentRound: g.currentRound | 0,
    roundDuration: room.roundDuration | 0,
    phase: g.phase || 'waiting',
    roundStartTime: g.roundStartTime | 0,
    currentDrawerOpenId: g.currentDrawerOpenId || '',
    currentDrawerNick: drow ? drow.nickName : (g.currentDrawerNick || ''),
    publicPlayers: sorted.map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      score: p.score | 0
    })),
    roundHits: g.roundHits || [],
    revealedWord: g.revealedWord || '',
    publicLog: g.publicLog || [],
    wordCategory: room.wordCategory || 'all',
    canvasSeq: g.canvasSeq | 0
  }
}

function pickNewWord (room) {
  const used = new Set((room.usedWordIds || []) || [])
  const pool = shuf(
    pickPool(room.wordCategory || 'all').filter((w) => !used.has(w.id))
  )
  if (!pool.length) {
    return null
  }
  const w = pool[0]
  return w
}

async function clearCanvasDoc (roomId) {
  const id = String(roomId)
  await db
    .collection(C)
    .doc(id)
    .set({
      data: {
        roomId: id,
        image: '',
        v: (t() % 100000000) | 0
      }
    })
}

exports.main = async (event) => {
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}

async function run (e) {
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
      status: 'waiting',
      totalRounds: 6,
      roundDuration: 60,
      wordCategory: 'all',
      usedWordIds: [],
      createdAt: t(),
      updatedAt: t()
    }
    const { _id } = await db.collection(R).add({ data: room })
    await db.collection(P).add({
      data: {
        roomId: _id,
        openId: o,
        nickName: e.nickName && String(e.nickName).trim().slice(0, 12) ? String(e.nickName).trim().slice(0, 12) : '房主',
        isHost: true,
        score: 0,
        joinedAt: t()
      }
    })
    const row = Object.assign({ _id }, room)
    await setState(
      Object.assign(row, { _id }),
      {
        currentRound: 0,
        phase: 'waiting',
        roundStartTime: 0,
        roundHits: [],
        publicLog: [],
        canvasSeq: 0
      }
    )
    await clearCanvasDoc(_id)
    return { roomId: _id, roomCode: code }
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
    if (r0.status === 'finished') {
      throw new Error('房间已结束')
    }
    const pl0 = await gPlayers(r0._id)
    const exist = pl0.find((p) => p.openId === o)
    const nm = String(e.nickName || '')
      .trim()
      .slice(0, 12) || '参与者'
    if (exist) {
      if (exist._id) {
        await db
          .collection(P)
          .doc(String(exist._id))
          .update({ data: { nickName: nm, updatedAt: t() } })
      }
    } else {
      if (pl0.length >= 20) {
        throw new Error('满员')
      }
      await db.collection(P).add({
        data: {
          roomId: r0._id,
          openId: o,
          nickName: nm,
          isHost: r0.hostOpenId === o,
          score: 0,
          joinedAt: t()
        }
      })
    }
    const r1 = await gRoom(r0._id)
    const g0 = (await gState(r0._id)) || { roundHits: [], publicLog: [] }
    await setState(r1, g0)
    return { roomId: String(r0._id) }
  }
  if (a === 'setConfig') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主可设')
    }
    if (room0.status !== 'waiting') {
      throw new Error('已开始过')
    }
    const n = [5, 6, 8, 9, 10, 12].indexOf((e.totalRounds | 0) || 0) >= 0
      ? e.totalRounds | 0
      : 6
    const cat = (e.wordCategory && String(e.wordCategory)) || 'all'
    await db
      .collection(R)
      .doc(String(rid))
      .update({
        data: { totalRounds: n, wordCategory: cat, updatedAt: t() }
      })
    const r2 = await gRoom(rid)
    const g = (await gState(rid)) || {}
    await setState(r2, g)
    return { totalRounds: n, wordCategory: cat }
  }
  if (a === 'setPendingWord') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主可设')
    }
    if (room0.status !== 'waiting') {
      throw new Error('已开始过')
    }
    const word = String(e.word || '')
      .trim()
      .slice(0, 16)
    if (!word) {
      throw new Error('词语无效')
    }
    await db
      .collection(R)
      .doc(String(rid))
      .update({ data: { pendingWord: word, updatedAt: t() } })
    return { word: word }
  }
  if (a === 'startGame') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主可开始')
    }
    if (room0.status !== 'waiting') {
      throw new Error('已开始')
    }
    const pls = await gPlayers(rid)
    if (pls.length < 2) {
      throw new Error('至少2人才能开始')
    }
    let w = null
    const pending = String(room0.pendingWord || '').trim()
    if (pending) {
      w = { id: 'ai_' + t(), word: pending.slice(0, 16) }
    } else {
      w = pickNewWord(
        Object.assign({ usedWordIds: room0.usedWordIds || [] }, room0, {
          wordCategory: room0.wordCategory || 'all'
        })
      )
    }
    if (!w) {
      throw new Error('词库不足，请改分类后重试')
    }
    const d = drawerForRound(pls, 1, room0.totalRounds | 0)
    const now = t()
    const used1 = w && w.id ? [w.id] : []
    await db
      .collection(R)
      .doc(String(rid))
      .update({
        data: {
          status: 'playing',
          currentWordId: w.id,
          usedWordIds: used1,
          pendingWord: '',
          updatedAt: t()
        }
      })
    const g = {
      currentRound: 1,
      phase: 'drawing',
      roundStartTime: now,
      roundHits: [],
      publicLog: ['第1轮。绘画：' + d.nick + '。大家猜词。'],
      currentDrawerOpenId: d.openId,
      currentDrawerNick: d.nick,
      revealedWord: '',
      canvasSeq: 1
    }
    const r3 = await gRoom(rid)
    await setState(r3, g)
    await clearCanvasDoc(rid)
    return { ok: 1 }
  }
  if (a === 'reveal') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0) {
      throw new Error('房间无效')
    }
    const g = (await gState(rid)) || {}
    if (room0.status !== 'playing' || g.phase !== 'drawing') {
      return { same: 1 }
    }
    const dur = (room0.roundDuration | 0) * 1000
    const rs = g.roundStartTime | 0
    const isHost = room0.hostOpenId === o
    if (!isHost && t() < rs + dur) {
      throw new Error('倒计时未结束')
    }
    const w = (room0.currentWordId && BY_ID[room0.currentWordId]) || null
    const wordStr = w ? w.w : ''
    const r2 = await gRoom(rid)
    await setState(r2, {
      phase: 'revealed',
      revealedWord: wordStr,
      publicLog: (g.publicLog || []).concat(
        '揭晓：' + wordStr + '。' + guessSummary(g.roundHits || [])
      )
    })
    return { ok: 1 }
  }
  if (a === 'nextRound') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主的下一题')
    }
    if (room0.status !== 'playing') {
      throw new Error('非进行中的环节')
    }
    const g = (await gState(rid)) || {}
    if (g.phase === 'drawing') {
      throw new Error('请先揭晓本词')
    }
    const tr = (room0.totalRounds | 0) || 1
    const cr = (g.currentRound | 0) + 0
    if (cr >= tr) {
      await db
        .collection(R)
        .doc(String(rid))
        .update({
          data: { status: 'finished', updatedAt: t() }
        })
      const g2 = {
        currentRound: cr,
        phase: 'finished',
        publicLog: (g.publicLog || []).concat(['全部轮次结束。']),
        finishedAt: t()
      }
      const r4 = await gRoom(rid)
      await setState(
        r4,
        g2
      )
      return { over: 1 }
    }
    const pls = await gPlayers(rid)
    const w = pickWithUsed(room0)
    if (!w) {
      const used = (room0.usedWordIds || []).length
      if (used >= WORDS.length) {
        await db
          .collection(R)
          .doc(String(rid))
          .update({ data: { status: 'finished', updatedAt: t() } })
        const r5 = await gRoom(rid)
        await setState(
          r5,
          {
            currentRound: cr,
            phase: 'finished',
            publicLog: (g.publicLog || []).concat(['词已用尽，结束。'])
          }
        )
        return { over: 1, wordsOut: 1 }
      }
      throw new Error('无可用新词，请重开')
    }
    const nextR = cr + 1
    const d = drawerForRound(pls, nextR, tr)
    const usedList = (room0.usedWordIds || []).concat([w.id])
    const now = t()
    await db
      .collection(R)
      .doc(String(rid))
      .update({
        data: { currentWordId: w.id, usedWordIds: usedList, updatedAt: t() }
      })
    const r6 = await gRoom(rid)
    const g3 = {
      currentRound: nextR,
      phase: 'drawing',
      roundStartTime: now,
      roundHits: [],
      currentDrawerOpenId: d.openId,
      currentDrawerNick: d.nick,
      revealedWord: '',
      publicLog: (g.publicLog || []).concat(
        [
          '第' + nextR + '轮。绘画：' + d.nick + '。'
        ]
      ),
      canvasSeq: (g.canvasSeq | 0) + 1
    }
    await setState(
      r6,
      g3
    )
    await clearCanvasDoc(rid)
    return { currentRound: nextR }
  }
  if (a === 'skipWord') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主的换词')
    }
    if (room0.status !== 'playing') {
      throw new Error('非进行中的环节')
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'drawing') {
      throw new Error('非绘画中')
    }
    const w = pickWithUsed(room0)
    if (!w) {
      throw new Error('无词可换')
    }
    const u0 = room0.usedWordIds || []
    const usedList = Array.from(new Set(u0.concat([w.id])))
    const now = t()
    await db
      .collection(R)
      .doc(String(rid))
      .update({ data: { currentWordId: w.id, usedWordIds: usedList, updatedAt: t() } })
    const r6 = await gRoom(rid)
    const g3 = {
      roundStartTime: now,
      roundHits: g.roundHits || [],
      publicLog: (g.publicLog || []).concat(
        [ '房主已换题。' ]
      ),
      canvasSeq: (g.canvasSeq | 0) + 1
    }
    await setState(
      r6,
      g3
    )
    await clearCanvasDoc(rid)
    return { ok: 1 }
  }
  if (a === 'submitGuess') {
    const rid = e.roomId
    const raw = String(e.answer || '')
    const room0 = await gRoom(rid)
    if (!room0) {
      throw new Error('房间无效')
    }
    if (room0.status !== 'playing') {
      throw new Error('未在猜画')
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'drawing') {
      return { done: 1, ok: 0 }
    }
    const w = (room0.currentWordId && BY_ID[room0.currentWordId]) || null
    if (!w) {
      return { err: 1, ok: 0 }
    }
    const dur = (room0.roundDuration | 0) * 1000
    if (t() > (g.roundStartTime | 0) + dur) {
      return { late: 1, ok: 0 }
    }
    if (g.currentDrawerOpenId && o === g.currentDrawerOpenId) {
      return { drawerNoGuess: 1, ok: 0 }
    }
    const pls = await gPlayers(rid)
    const me = pls.find((p) => p.openId === o)
    if (!me) {
      throw new Error('非本聚会组成员')
    }
    if ((g.roundHits || []).find((h) => h.openId === o)) {
      return { already: 1, ok: 0 }
    }
    if (normGuess(raw) !== normW(w)) {
      return { wrong: 1, ok: 0 }
    }
    const nHit = (g.roundHits || []).length
    const points = nHit === 0 ? 3 : 1
    const h = { openId: o, nickName: me.nickName, order: nHit + 1, points }
    const roundHits2 = (g.roundHits || []).concat([h])
    const newG = (me.score | 0) + points
    await db
      .collection(P)
      .doc(
        (await db
          .collection(P)
          .where({ roomId: String(rid), openId: o })
          .limit(1)
          .get()
        ).data[0]._id
      )
      .update({ data: { score: newG, updatedAt: t() } })
    const dPl = pls.find((p) => p.openId === (g && g.currentDrawerOpenId))
    if (dPl && nHit < 5) {
      const dp = (dPl.score | 0) + 1
      await db
        .collection(P)
        .doc(
          (await db
            .collection(P)
            .where({ roomId: String(rid), openId: g.currentDrawerOpenId })
            .limit(1)
            .get()
          ).data[0]._id
        )
        .update({ data: { score: dp, updatedAt: t() } })
    }
    const r5 = await gRoom(rid)
    await setState(
      r5,
      { roundHits: roundHits2 }
    )
    return { ok: 1, points, order: h.order, score: newG }
  }
  if (a === 'updateCanvas') {
    const rid = e.roomId
    const im = (e.image && String(e.image)) || ''
    const room0 = await gRoom(rid)
    if (!room0 || room0.status !== 'playing') {
      return { no: 1 }
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'drawing' || o !== g.currentDrawerOpenId) {
      return { no: 1 }
    }
    if (im.length < 20) {
      return { no: 1 }
    }
    if (im.length > 800000) {
      throw new Error('画布过大，请清屏或重绘')
    }
    const id = String(rid)
    const ver = t()
    await db
      .collection(C)
      .doc(id)
      .set({
        data: { roomId: id, image: im, v: ver, updatedAt: t() }
      })
    return { ok: 1 }
  }
  if (a === 'endGame') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅组长可结束')
    }
    if (room0.status === 'finished') {
      return { ok: 1 }
    }
    await db
      .collection(R)
      .doc(String(rid))
      .update({ data: { status: 'finished', updatedAt: t() } })
    const g0 = (await gState(rid)) || {}
    const r5 = await gRoom(rid)
    await setState(
      r5,
      { phase: 'finished', publicLog: (g0.publicLog || []).concat(['组长结束本环节。']) }
    )
    return { ok: 1 }
  }
  if (a === 'getView') {
    return await getView(e.roomId, o)
  }
  throw new Error('未知' + a)
}

function pickWithUsed (room0) {
  const used = new Set((room0.usedWordIds || []) || [])
  const cur = room0.currentWordId || ''
  const pool0 = shuf(
    pickPool(room0.wordCategory || 'all').filter(
      (w) => !used.has(w.id) && w.id !== cur
    )
  )
  if (pool0.length) {
    return pool0[0]
  }
  const pool1 = shuf(WORDS.filter((w) => w.id !== cur && !used.has(w.id)))
  return pool1[0] || null
}

function guessSummary (hits) {
  if (!hits || !hits.length) {
    return '无人猜中。'
  }
  return (
    '猜中：' +
    hits
      .map((h) => h.nickName)
      .join('、') +
    '。'
  )
}

async function getView (roomId, openId) {
  const room = await gRoom(roomId)
  if (!room) {
    return {}
  }
  const g = (await gState(roomId)) || {}
  const pls = await gPlayers(roomId)
  const w = (room.currentWordId && BY_ID[room.currentWordId]) || null
  const isDrawer = !!(g.currentDrawerOpenId && g.currentDrawerOpenId === openId)
  return {
    isHost: room.hostOpenId === openId,
    isDrawer: !!isDrawer,
    painterWord: isDrawer && g.phase === 'drawing' && w ? w.w : '',
    myScore: (pls.find((p) => p.openId === openId) || { score: 0 }).score | 0,
    hasGuessedThisRound: !!(g.roundHits || []).find((h) => h.openId === openId),
    publicPlayers: (pls || [])
      .slice()
      .sort((a, b) => (b.score | 0) - (a.score | 0))
      .map((p) => ({ openId: p.openId, nickName: p.nickName, score: p.score | 0 })),
    phase: g.phase,
    currentRound: g.currentRound,
    currentDrawerNick: g.currentDrawerNick,
    revealedWord: g.revealedWord
      || (g.phase === 'revealed' && w ? w.w : '')
      || '',
    roomStatus: room.status
  }
}
