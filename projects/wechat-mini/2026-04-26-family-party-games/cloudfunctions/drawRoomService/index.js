const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command
const { pickPool, BY_ID, WORDS } = require('./words')

const R = 'draw_rooms'
const P = 'draw_players'
const S = 'draw_gameState'
const C = 'draw_canvas'

const t = () => Date.now()

function logDraw (tag, extra) {
  console.log('[drawRoom]', tag, extra || '')
}

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
function wordText (o) {
  if (!o) {
    return ''
  }
  if (o.w != null && String(o.w).trim()) {
    return String(o.w).trim()
  }
  if (o.word != null && String(o.word).trim()) {
    return String(o.word).trim()
  }
  return ''
}

/** 系统词库 + AI/自定义题（currentWordText） */
function resolveWord (room0) {
  if (!room0 || !room0.currentWordId) {
    return null
  }
  const hit = BY_ID[room0.currentWordId]
  if (hit) {
    return hit
  }
  const text = String(room0.currentWordText || '').trim()
  if (text) {
    return { id: room0.currentWordId, w: text.slice(0, 16) }
  }
  return null
}

function normW (o) {
  const s = wordText(o)
  if (!s) {
    return ''
  }
  return s
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
    publicPlayers: sorted.map((p) =>
      Object.assign(jp.withProfileReadyFlag(p), { score: p.score | 0 })
    ),
    roundHits: g.roundHits || [],
    revealedWord: g.revealedWord || '',
    publicLog: g.publicLog || [],
    wordCategory: room.wordCategory || 'all',
    canvasSeq: g.canvasSeq | 0,
    canvasData: canvasDataForPub(g.canvasData),
    canvasDataVer: g.canvasDataVer | 0,
    syncAt: t()
  }
}

function canvasDataFromDb (raw) {
  if (Array.isArray(raw)) {
    return raw
  }
  if (typeof raw === 'string') {
    const s = raw.trim()
    if (!s) {
      return []
    }
    try {
      const p = JSON.parse(s)
      return Array.isArray(p) ? p : []
    } catch (e) {
      return []
    }
  }
  return []
}

function canvasDataForPub (raw) {
  if (typeof raw === 'string') {
    return raw
  }
  return JSON.stringify(Array.isArray(raw) ? raw : [])
}

/** 规范化画家上传的完整笔画（全量重绘，非增量） */
function normCanvasData (raw) {
  if (typeof raw === 'string') {
    raw = canvasDataFromDb(raw)
  }
  if (!Array.isArray(raw)) {
    return []
  }
  const out = []
  for (let i = 0; i < raw.length && out.length < 200; i += 1) {
    const item = raw[i]
    if (!item) {
      continue
    }
    const pts = []
    const src = item.pts || item.points || item.path || []
    for (let j = 0; j < src.length && pts.length < 800; j += 1) {
      const p = src[j]
      if (Array.isArray(p) && p.length >= 2) {
        pts.push([Math.round(p[0] | 0), Math.round(p[1] | 0)])
      } else if (p && p.x != null && p.y != null) {
        pts.push([Math.round(p.x | 0), Math.round(p.y | 0)])
      }
    }
    if (pts.length < 2) {
      continue
    }
    out.push({
      c: String(item.c || item.color || '#111111').slice(0, 16),
      w: Math.min(20, Math.max(1, (item.w | 0) || (item.width | 0) || 4)),
      pts: pts
    })
  }
  return out
}

/** 单段笔画（增量 appendStroke） */
function normStrokeSegment (raw) {
  if (!raw) {
    return null
  }
  const pts = []
  const src = raw.pts || raw.points || raw.path || []
  for (let j = 0; j < src.length && pts.length < 8; j += 1) {
    const p = src[j]
    if (Array.isArray(p) && p.length >= 2) {
      pts.push([Math.round(p[0] | 0), Math.round(p[1] | 0)])
    } else if (p && p.x != null && p.y != null) {
      pts.push([Math.round(p.x | 0), Math.round(p.y | 0)])
    }
  }
  if (pts.length < 2) {
    return null
  }
  return {
    c: String(raw.c || raw.color || '#111111').slice(0, 16),
    w: Math.min(20, Math.max(1, (raw.w | 0) || (raw.width | 0) || 4)),
    pts: pts
  }
}

function mergeStrokeIntoCanvas (canvasData, entry) {
  const list = canvasDataFromDb(canvasData).slice()
  const last = list[list.length - 1]
  if (last && last.c === entry.c && (last.w | 0) === (entry.w | 0)) {
    const merged = last.pts.slice()
    for (let i = 0; i < entry.pts.length; i += 1) {
      const p = entry.pts[i]
      const tail = merged[merged.length - 1]
      if (!tail || tail[0] !== p[0] || tail[1] !== p[1]) {
        merged.push(p)
      }
    }
    if (merged.length < 2) {
      return list
    }
    last.pts = merged.slice(-800)
    return list.slice(-200)
  }
  list.push(entry)
  return list.slice(-200)
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

async function clearCanvasDoc (roomId, canvasSeq) {
  const id = String(roomId)
  const seq = canvasSeq | 0
  await db.collection(C).doc(id).set({
    data: {
      roomId: id,
      image: '',
      strokes: [],
      canvasSeq: seq,
      v: t(),
      updatedAt: t()
    }
  })
  logDraw('clearCanvasDoc', { roomId: id, canvasSeq: seq })
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
  if (a === 'getOpenId') {
    return { openId: o }
  }
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
        avatarUrl: String((e && e.avatarUrl) || '').trim(),
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
    if (r0.status === 'finished') {
      throw new Error('房间已结束')
    }
    const pl0 = await gPlayers(r0._id)
    const exist = pl0.find((p) => p.openId === o)
    if (exist) {
      if (exist._id) {
        await db
          .collection(P)
          .doc(String(exist._id))
          .update({
            data: Object.assign(jp.mergeJoinFields(e, exist), { updatedAt: t() })
          })
      }
    } else {
      if (pl0.length >= 20) {
        throw new Error('满员')
      }
      await db.collection(P).add({
        data: Object.assign(
          {
            roomId: r0._id,
            openId: o,
            isHost: r0.hostOpenId === o,
            score: 0,
            joinedAt: t()
          },
          jp.mergeJoinFields(e, {})
        )
      })
    }
    const r1 = await gRoom(r0._id)
    const g0 = (await gState(r0._id)) || { roundHits: [], publicLog: [] }
    await setState(r1, g0)
    const pl1 = await gPlayers(r0._id)
    return {
      roomId: String(r0._id),
      roomCode: r1.roomCode,
      playerCount: pl1.length,
      myOpenId: o
    }
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
      w = { id: 'ai_' + t(), w: pending.slice(0, 16) }
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
          currentWordText: wordText(w).slice(0, 16),
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
      canvasSeq: 1,
      canvasData: [],
      canvasDataVer: t()
    }
    const r3 = await gRoom(rid)
    await setState(r3, g)
    await clearCanvasDoc(rid, g.canvasSeq)
    logDraw('startGame', {
      roomId: rid,
      drawerOpenId: d.openId,
      round: 1,
      wordId: w.id
    })
    return { ok: 1, drawerOpenId: d.openId }
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
    const w = resolveWord(room0)
    const wordStr = wordText(w)
    const r2 = await gRoom(rid)
    await setState(r2, {
      phase: 'revealed',
      revealedWord: wordStr,
      publicLog: (g.publicLog || []).concat(
        '揭晓：' + wordStr + '。' + guessSummary(g.roundHits || [])
      )
    })
    logDraw('reveal', { roomId: rid, word: wordStr })
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
        data: {
          currentWordId: w.id,
          currentWordText: wordText(w).slice(0, 16),
          usedWordIds: usedList,
          updatedAt: t()
        }
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
      canvasSeq: (g.canvasSeq | 0) + 1,
      canvasData: [],
      canvasDataVer: t()
    }
    await setState(r6, g3)
    await clearCanvasDoc(rid, g3.canvasSeq)
    logDraw('nextRound', {
      roomId: rid,
      round: nextR,
      drawerOpenId: d.openId
    })
    return { currentRound: nextR, drawerOpenId: d.openId }
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
      .update({
        data: {
          currentWordId: w.id,
          currentWordText: wordText(w).slice(0, 16),
          usedWordIds: usedList,
          updatedAt: t()
        }
      })
    const r6 = await gRoom(rid)
    const g3 = {
      roundStartTime: now,
      roundHits: g.roundHits || [],
      publicLog: (g.publicLog || []).concat(
        [ '房主已换题。' ]
      ),
      canvasSeq: (g.canvasSeq | 0) + 1,
      canvasData: [],
      canvasDataVer: t()
    }
    await setState(r6, g3)
    await clearCanvasDoc(rid, g3.canvasSeq)
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
    const w = resolveWord(room0)
    if (!w) {
      logDraw('submitGuess noWord', { roomId: rid, wordId: room0.currentWordId })
      return { err: 1, ok: 0, errHint: '题目无效' }
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
  if (a === 'appendStroke') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.status !== 'playing') {
      return { no: 1 }
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'drawing' || o !== g.currentDrawerOpenId) {
      return { no: 1 }
    }
    const entry = normStrokeSegment(e.stroke)
    if (!entry) {
      return { no: 1 }
    }
    const rNow = await gRoom(rid)
    const canvasData = mergeStrokeIntoCanvas(g.canvasData, entry)
    await setState(rNow, { canvasData: canvasData, canvasDataVer: t() })
    logDraw('appendStroke', { roomId: String(rid), pathCount: canvasData.length })
    return { ok: 1, pathCount: canvasData.length }
  }
  if (a === 'updateCanvas') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.status !== 'playing') {
      return { no: 1 }
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'drawing' || o !== g.currentDrawerOpenId) {
      return { no: 1 }
    }
    const id = String(rid)
    const canvasSeq = (g.canvasSeq | 0) || 0
    const rNow = await gRoom(rid)

    if (e.clear) {
      await setState(rNow, { canvasData: [], canvasDataVer: t() })
      await clearCanvasDoc(rid, canvasSeq)
      logDraw('updateCanvas clear', { roomId: id })
      return { ok: 1, clear: 1 }
    }

    if (e.canvasData !== undefined) {
      const canvasData = normCanvasData(e.canvasData)
      await setState(rNow, { canvasData: canvasData, canvasDataVer: t() })
      logDraw('updateCanvas canvasData', {
        roomId: id,
        pathCount: canvasData.length
      })
      return { ok: 1, pathCount: canvasData.length }
    }

    let doc = null
    try {
      doc = (await db.collection(C).doc(id).get()).data
    } catch (err) {
      doc = null
    }

    const stroke = e.stroke
    if (stroke && stroke.pts && stroke.pts.length >= 2) {
      const pts = []
      for (let i = 0; i < stroke.pts.length && pts.length < 64; i += 1) {
        const p = stroke.pts[i]
        if (!p || p.length < 2) {
          continue
        }
        pts.push([Math.round(p[0] | 0), Math.round(p[1] | 0)])
      }
      if (pts.length < 2) {
        return { no: 1 }
      }
      const entry = {
        c: String(stroke.c || '#111111').slice(0, 16),
        w: Math.min(20, Math.max(1, (stroke.w | 0) || 4)),
        pts: pts
      }
      const prev = (doc && doc.strokes) || []
      if ((doc && doc.canvasSeq | 0) !== canvasSeq) {
        await clearCanvasDoc(rid, canvasSeq)
        doc = { strokes: [], canvasSeq: canvasSeq }
      }
      const strokes = ((doc && doc.strokes) || []).concat([entry]).slice(-500)
      await db.collection(C).doc(id).set({
        data: {
          roomId: id,
          strokes: strokes,
          canvasSeq: canvasSeq,
          image: (doc && doc.image) || '',
          v: t(),
          updatedAt: t()
        }
      })
      return { ok: 1, strokeCount: strokes.length }
    }

    const im = (e.image && String(e.image)) || ''
    if (im.length < 20) {
      return { no: 1 }
    }
    if (im.length > 800000) {
      throw new Error('画布过大，请清屏或重绘')
    }
    await db.collection(C).doc(id).set({
      data: {
        roomId: id,
        image: im,
        strokes: (doc && doc.strokes) || [],
        canvasSeq: canvasSeq,
        v: t(),
        updatedAt: t()
      }
    })
    return { ok: 1, image: 1 }
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
  if (a === 'syncState') {
    return await doSyncState(e.roomId, o)
  }
  throw new Error('未知' + a)
}

async function doSyncState (roomId, openId) {
  const rid = String(roomId || '')
  if (!rid) {
    throw new Error('无房间')
  }
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('房间不存在')
  }
  const pls = await gPlayers(rid)
  const me = pls.find((p) => p.openId === openId)
  if (!me) {
    return { ok: 1, myOpenId: openId, inRoom: false }
  }
  const g = (await gState(rid)) || {}
  const state = buildPub(room, pls, g)
  const view = await getView(rid, openId)
  return {
    ok: 1,
    myOpenId: openId,
    inRoom: true,
    state,
    view
  }
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
  const w = resolveWord(room)
  const isDrawer = !!(g.currentDrawerOpenId && g.currentDrawerOpenId === openId)
  const wt = wordText(w)
  const view = {
    myOpenId: openId,
    isHost: room.hostOpenId === openId,
    isDrawer: !!isDrawer,
    myScore: (pls.find((p) => p.openId === openId) || { score: 0 }).score | 0,
    hasGuessedThisRound: !!(g.roundHits || []).find((h) => h.openId === openId),
    publicPlayers: (pls || [])
      .slice()
      .sort((a, b) => (b.score | 0) - (a.score | 0))
      .map((p) => ({
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl || '',
        isHost: room.hostOpenId === p.openId,
        score: p.score | 0
      })),
    phase: g.phase,
    currentRound: g.currentRound,
    currentDrawerNick: g.currentDrawerNick,
    revealedWord: g.revealedWord || (g.phase === 'revealed' && wt ? wt : '') || '',
    roomStatus: room.status
  }
  if (isDrawer && g.phase === 'drawing' && wt) {
    view.painterWord = wt
  }
  return view
}
