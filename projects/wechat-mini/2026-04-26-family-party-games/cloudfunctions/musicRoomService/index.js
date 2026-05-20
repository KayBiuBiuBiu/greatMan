const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command
const { SONGS, ID_TO_SONG } = require('./songs')

const R = 'music_rooms'
const P = 'music_players'
const S = 'music_gameState'

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
/** 随机一名轮次主持；≥2 人时尽量避免与上一轮同一人 */
function pickRoundHost (players, previousOpenId) {
  const pls = (players || []).filter((p) => p && p.openId)
  if (!pls.length) {
    return { openId: '', nickName: '' }
  }
  if (pls.length === 1) {
    return { openId: pls[0].openId, nickName: pls[0].nickName }
  }
  const candidates = previousOpenId
    ? pls.filter((p) => p.openId !== previousOpenId)
    : pls
  const pool = candidates.length ? candidates : pls
  const r = pool[(Math.random() * pool.length) | 0]
  return { openId: r.openId, nickName: r.nickName }
}
function normAns (s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/[\s·•。，、！!？?《》""''（）()【】\[\]：:\-_]/g, '')
}
function matchTitle (raw, song) {
  if (!song) {
    return false
  }
  const n = normAns(raw)
  if (!n) {
    return false
  }
  if (normAns(song.title) === n) {
    return true
  }
  return (song.aliases || []).some((a) => normAns(a) === n)
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

async function setStateFromRoom (room, extra) {
  if (!room || !room._id) {
    return
  }
  const pls = await gPlayers(room._id)
  const pub = buildPub(room, pls, extra)
  const safe = omitIdDeep(pub)
  await db
    .collection(S)
    .doc(String(room._id))
    .set({ data: safe })
}

function buildPub (room, players, st) {
  const g = st || {}
  const sorted = (players || [])
    .slice()
    .sort((a, b) => (b.score | 0) - (a.score | 0))
  const cix = typeof g.currentIndex === 'number' ? g.currentIndex : -1
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    status: room.status,
    hostOpenId: room.hostOpenId,
    totalRounds: room.totalRounds | 0,
    roundDuration: room.roundDuration | 0,
    currentIndex: cix,
    playToken: g.playToken | 0,
    roundStartTime: g.roundStartTime | 0,
    phase: g.phase || 'waiting',
    /** 公屏不暴露歌名；由轮次主持在本机用音乐 App 外放 */
    roundHostOpenId: g.roundHostOpenId || '',
    roundHostNickName: g.roundHostNickName || '',
    publicPlayers: sorted.map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      score: p.score | 0
    })),
    roundHits: g.roundHits || [],
    publicLog: g.publicLog || [],
    finishedAt: g.finishedAt
  }
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
      totalRounds: 5,
      roundDuration: 30,
      rounds: [],
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
    const pl0 = await gPlayers(_id)
    await setStateFromRoom(
      Object.assign(row, { _id }),
      { currentIndex: -1, playToken: 0, roundStartTime: 0, phase: 'waiting', publicLog: [], roundHits: [] }
    )
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
    const g0 =
      (await gState(r0._id)) || {
        currentIndex: -1,
        playToken: 0,
        publicLog: [],
        roundHits: []
      }
    await setStateFromRoom(r1, g0)
    return { roomId: String(r0._id) }
  }
  if (a === 'setRounds') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主可设')
    }
    if (room0.status !== 'waiting') {
      throw new Error('已开始过')
    }
    const n = [5, 10, 15].indexOf((e.totalRounds | 0) || 0) >= 0 ? e.totalRounds | 0 : 5
    await db
      .collection(R)
      .doc(String(rid))
      .update({ data: { totalRounds: n, updatedAt: t() } })
    const r2 = await gRoom(rid)
    const g = (await gState(rid)) || {}
    await setStateFromRoom(r2, g)
    return { totalRounds: n }
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
    const n = (room0.totalRounds | 0) || 5
    const all = SONGS.slice()
    if (n > all.length) {
      throw new Error('曲库不足' + n + '首，请少选轮数')
    }
    const sh = shuf(all).slice(0, n)
    const rounds = sh.map((s) => ({
      id: s.id,
      title: s.title,
      aliases: s.aliases,
      audioUrl: s.audioUrl
    }))
    const pls0 = await gPlayers(rid)
    if (pls0.length < 2) {
      throw new Error('至少2人才能开始')
    }
    const rh0 = pickRoundHost(pls0, null)
    const now = t()
    const st0 = {
      currentIndex: 0,
      playToken: 1,
      roundStartTime: now,
      phase: 'round_playing',
      roundHits: [],
      publicLog: [
        '互动开始。第1轮。主持：' + (rh0.nickName || '—') + '（请用本机外放该歌）。'
      ],
      currentSongId: rounds[0] ? rounds[0].id : '',
      lastRoundIndex: -1,
      roundHostOpenId: rh0.openId,
      roundHostNickName: rh0.nickName
    }
    await db
      .collection(R)
      .doc(String(rid))
      .update({
        data: { status: 'playing', rounds, updatedAt: t() }
      })
    const r3 = await gRoom(rid)
    await setStateFromRoom(r3, st0)
    return { ok: 1 }
  }
  if (a === 'nextSong') {
    const rid = e.roomId
    const room0 = await gRoom(rid)
    if (!room0 || room0.hostOpenId !== o) {
      throw new Error('仅房主的下一首')
    }
    if (room0.status !== 'playing') {
      throw new Error('非进行中的环节')
    }
    const g = (await gState(rid)) || {}
    const idx =
      typeof g.currentIndex === 'number' && g.currentIndex >= 0
        ? g.currentIndex
        : 0
    const total = (room0.rounds || []).length
    if (!total) {
      throw new Error('无歌单')
    }
    if (idx < total - 1) {
      const ni = idx + 1
      const now = t()
      const pln = await gPlayers(rid)
      const rh = pickRoundHost(pln, g.roundHostOpenId)
      const log = (g.publicLog || []).concat([
        '第' + (ni + 1) + '轮。主持：' + (rh.nickName || '—') + '。'
      ])
      const g2 = {
        currentIndex: ni,
        playToken: (g.playToken | 0) + 1,
        roundStartTime: now,
        phase: 'round_playing',
        roundHits: [],
        publicLog: log,
        lastRoundIndex: g.currentIndex,
        currentSongId: (room0.rounds[ni] && room0.rounds[ni].id) || '',
        roundHostOpenId: rh.openId,
        roundHostNickName: rh.nickName
      }
      await setStateFromRoom(
        room0,
        g2
      )
      return { currentIndex: ni }
    }
    const now2 = t()
    const g3 = {
      currentIndex: idx,
      playToken: (g.playToken | 0) + 1,
      roundStartTime: 0,
      phase: 'finished',
      publicLog: (g.publicLog || []).concat(['全部轮次结束。']),
      finishedAt: now2,
      roundHostOpenId: '',
      roundHostNickName: ''
    }
    await db
      .collection(R)
      .doc(String(rid))
      .update({ data: { status: 'finished', updatedAt: t() } })
    const r4 = await gRoom(rid)
    await setStateFromRoom(
      r4,
      g3
    )
    return { over: 1 }
  }
  if (a === 'submitAnswer') {
    const rid = e.roomId
    const raw = String(e.answer || '')
    const room0 = await gRoom(rid)
    if (!room0) {
      throw new Error('房间无效')
    }
    if (room0.status !== 'playing') {
      throw new Error('未在猜歌中')
    }
    const g = (await gState(rid)) || {}
    if (g.phase !== 'round_playing') {
      throw new Error('本轮已结束或结算中')
    }
    const idx = g.currentIndex | 0
    const row = (room0.rounds || [])[idx]
    if (!row) {
      throw new Error('歌曲异常')
    }
    const dur = (room0.roundDuration | 0) || 30
    const elapsed = t() - (g.roundStartTime | 0)
    if (elapsed > dur * 1000) {
      return { late: 1, ok: 0 }
    }
    const pls = await gPlayers(rid)
    const me = pls.find((p) => p.openId === o)
    if (!me) {
      throw new Error('非本聚会组成员')
    }
    if (g.roundHostOpenId && o === g.roundHostOpenId) {
      return { hostNoGuess: 1, ok: 0 }
    }
    const hitIds = (g.roundHits || []).map((h) => h.openId)
    if (hitIds.indexOf(o) >= 0) {
      return { already: 1, ok: 0 }
    }
    const sol = ID_TO_SONG[row.id] || row
    const good = matchTitle(raw, {
      title: sol.title,
      aliases: (sol.aliases || row.aliases) || []
    })
    if (!good) {
      return { wrong: 1, ok: 0 }
    }
    const nHit = (g.roundHits || []).length
    const points = nHit === 0 ? 3 : 1
    const h = {
      openId: o,
      nickName: me.nickName,
      order: nHit + 1,
      points
    }
    const roundHits2 = (g.roundHits || []).concat([h])
    const newSc = (me.score | 0) + points
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
      .update({ data: { score: newSc, updatedAt: t() } })
    const g2 = Object.assign({}, g, { roundHits: roundHits2 })
    const r5 = await gRoom(rid)
    await setStateFromRoom(
      r5,
      g2
    )
    return { ok: 1, points, order: h.order, score: newSc }
  }
  if (a === 'getView') {
    return await getView(e.roomId, o)
  }
  throw new Error('未知' + a)
}

async function getView (roomId, openId) {
  const room = await gRoom(roomId)
  if (!room) {
    return {}
  }
  const pls = await gPlayers(roomId)
  const me = pls.find((p) => p.openId === openId)
  const g = (await gState(roomId)) || {}
  const cix2 = typeof g.currentIndex === 'number' ? g.currentIndex : -1
  const currentSong = cix2 >= 0 && (room.rounds && room.rounds[cix2]) ? room.rounds[cix2] : null
  const isRoundHost = !!(g.roundHostOpenId && g.roundHostOpenId === openId)
  const hit = (g.roundHits || []).find((h) => h.openId === openId)
  const sol = currentSong
    ? (ID_TO_SONG[currentSong.id] || currentSong)
    : null
  return {
    isHost: room.hostOpenId === openId,
    isRoundHost,
    /** 仅轮次主持可见，用于本机去音乐 App 搜歌外放 */
    hostPlayTitle: isRoundHost && sol ? sol.title : '',
    hostPlayAliases: isRoundHost && sol
      ? (sol.aliases || (currentSong && currentSong.aliases) || [])
      : [],
    myScore: me ? (me.score | 0) : 0,
    hasAnswered: !!hit,
    currentSong:
      isRoundHost && currentSong
        ? {
          id: currentSong.id,
          title: (sol && sol.title) || currentSong.title,
          aliases: (sol && sol.aliases) || currentSong.aliases || []
        }
        : null,
    publicPlayers: pls
      .slice()
      .sort((a, b) => (b.score | 0) - (a.score | 0))
      .map((p) => ({ openId: p.openId, nickName: p.nickName, score: p.score | 0 })),
    currentRound: cix2 >= 0 ? cix2 + 1 : 0,
    totalRounds: (room.totalRounds | 0) || 0,
    publicLog: g.publicLog || [],
    roundHits: g.roundHits || [],
    phase: g.phase || 'waiting',
    roomStatus: room.status
  }
}
