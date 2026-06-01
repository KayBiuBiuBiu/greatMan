const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
const { seedPlayersCollection } = require('./testSeedPlayers')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command
const { ID_TO_SONG } = require('./songs')

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
/** 当轮主持固定为聚会组组长（房主） */
function hostAsRoundHost (room, players) {
  const oid = (room && room.hostOpenId) || ''
  if (!oid) {
    return { openId: '', nickName: '' }
  }
  const p = (players || []).find((x) => x && x.openId === oid)
  return {
    openId: oid,
    nickName: (p && p.nickName) || '组长'
  }
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

function parseJsonValue (text) {
  const raw = String(text || '').trim()
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw)
  } catch (e) {
    const obj = raw.match(/\{[\s\S]*\}/)
    const arr = raw.match(/\[[\s\S]*\]/)
    if (obj) {
      try {
        return JSON.parse(obj[0])
      } catch (e2) {}
    }
    if (arr) {
      try {
        return JSON.parse(arr[0])
      } catch (e3) {}
    }
  }
  return null
}

function normalizeAiSongs(text, count) {
  const body = parseJsonValue(text)
  const raw = Array.isArray(body)
    ? body
    : body && Array.isArray(body.songs)
      ? body.songs
      : []
  const out = []
  const seen = {}
  for (let i = 0; i < raw.length; i += 1) {
    const item = raw[i]
    const title = String((item && (item.title || item.name)) || '').trim().slice(0, 20)
    if (!title || seen[normAns(title)]) {
      continue
    }
    seen[normAns(title)] = 1
    const aliases = Array.isArray(item.aliases)
      ? item.aliases.map((x) => String(x || '').trim()).filter(Boolean).slice(0, 5)
      : []
    out.push({
      id: 'ai_song_' + (i + 1) + '_' + t(),
      title: title,
      aliases: aliases
    })
  }
  if (out.length < count) {
    throw new Error('AI 歌单数量不足')
  }
  return out.slice(0, count)
}

async function fetchAiSongs(count) {
  const n = Math.max(1, Math.min(12, count | 0 || 5))
  const system =
    '你是聚会小游戏「疯狂猜歌」的出题助手。只返回 JSON，不要解释。歌曲必须大众熟悉、适合全年龄聚会，避免敏感低俗。'
  const prompt =
    '请生成 ' +
    n +
    ' 首适合猜歌游戏的中文流行歌曲。返回格式严格为：{"songs":[{"title":"歌名","aliases":["别名或歌手+歌名"]}]}。不要重复。'
  const res = await cloud.callFunction({
    name: 'aiPartyService',
    data: { action: 'chat', system: system, prompt: prompt }
  })
  const body = (res && res.result) || {}
  if (body.errMsg) {
    throw new Error(body.errMsg)
  }
  return normalizeAiSongs(body.text, n)
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
    publicPlayers: sorted.map((p) =>
      Object.assign(jp.withProfileReadyFlag(p), { score: p.score | 0 })
    ),
    roundHits: g.roundHits || [],
    publicLog: g.publicLog || [],
    finishedAt: g.finishedAt,
    syncAt: t()
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
    // 测试模式：快速创建不检查房间号重复
    if (e._test) {
      const code = '000001'
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
          avatarUrl: String((e && e.avatarUrl) || '').trim(),
          isHost: true,
          score: 0,
          joinedAt: t()
        }
      })
      const row = Object.assign({ _id }, room)
      await setStateFromRoom(
        Object.assign(row, { _id }),
        { currentIndex: -1, playToken: 0, roundStartTime: 0, phase: 'waiting', publicLog: [], roundHits: [] }
      )
      return { roomId: _id, roomCode: code, myOpenId: o }
    }
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
        avatarUrl: String((e && e.avatarUrl) || '').trim(),
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
    const g0 =
      (await gState(r0._id)) || {
        currentIndex: -1,
        playToken: 0,
        publicLog: [],
        roundHits: []
      }
    await setStateFromRoom(r1, g0)
    const pl1 = await gPlayers(r0._id)
    return {
      roomId: String(r0._id),
      roomCode: r0.roomCode,
      playerCount: pl1.length,
      myOpenId: o
    }
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
    if (!room0) {
      throw new Error('房间不存在')
    }
    if (!e._test && room0.hostOpenId !== o) {
      throw new Error('仅房主可开始')
    }
    if (room0.status !== 'waiting') {
      throw new Error('已开始')
    }
    const pls0 = await gPlayers(rid)
    if (pls0.length < 2) {
      throw new Error('至少2人才能开始')
    }
    const n = (room0.totalRounds | 0) || 5
    let aiSongs
    if (e._test) {
      // 测试模式：使用本地数据，避免 AI 超时
      aiSongs = [
        { id: 'test_song_1', title: '菊花台', aliases: ['周杰伦 菊花台'] },
        { id: 'test_song_2', title: '稻香', aliases: ['周杰伦 稻香'] },
        { id: 'test_song_3', title: '演员', aliases: ['薛之谦 演员'] },
        { id: 'test_song_4', title: '告白气球', aliases: ['周杰伦 告白气球'] },
        { id: 'test_song_5', title: '野狼disco', aliases: ['宝石老舅 野狼disco'] }
      ].slice(0, n)
    } else {
      aiSongs = await fetchAiSongs(n)
    }
    const rounds = aiSongs.map((s) => ({
      id: s.id,
      title: s.title,
      aliases: s.aliases || []
    }))
    const pls0 = await gPlayers(rid)
    if (pls0.length < 2) {
      throw new Error('至少2人才能开始')
    }
    const rh0 = hostAsRoundHost(room0, pls0)
    const now = t()
    const st0 = {
      currentIndex: 0,
      playToken: 1,
      roundStartTime: now,
      phase: 'round_playing',
      roundHits: [],
      publicLog: [
        '互动开始。第1轮。组长主持：' + (rh0.nickName || '—') + '（请用本机外放该歌）。'
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
      const rh = hostAsRoundHost(room0, pln)
      const log = (g.publicLog || []).concat([
        '第' + (ni + 1) + '轮。组长主持：' + (rh.nickName || '—') + '。'
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
  if (a === 'syncState') {
    return await doSyncState(e.roomId, o)
  }
  if (a === '__testSeedPlayers') {
    return await doTestSeedPlayers(e)
  }
  throw new Error('未知' + a)
}

async function doTestSeedPlayers(e) {
  const r0 = e.roomId ? await gRoom(e.roomId) : await gRoomByCode(String(e.roomCode || '').replace(/\D/g, ''))
  if (!r0) {
    throw new Error('房间不存在')
  }
  if (r0.status !== 'waiting') {
    throw new Error('对局已开始，无法注入测试玩家')
  }
  return seedPlayersCollection({
    event: e,
    db,
    playersCol: P,
    jp,
    roomId: String(r0._id),
    roomCode: r0.roomCode,
    cap: 20,
    listPlayers: gPlayers,
    baseFields: (p) => ({
      roomId: String(r0._id),
      openId: String(p.openId || '').trim(),
      nickName: String(p.nickName || '测试玩家').slice(0, 12),
      avatarUrl: String(p.avatarUrl || ''),
      isHost: false,
      score: 0,
      joinedAt: t()
    }),
    refreshState: async (id) => {
      const r1 = await gRoom(id)
      const g0 = (await gState(id)) || {}
      await setStateFromRoom(r1, g0)
    }
  })
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
    myOpenId: openId,
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
      .map((p) =>
        Object.assign(jp.withProfileReadyFlag(p), {
          isHost: room.hostOpenId === p.openId,
          score: p.score | 0
        })
      ),
    currentRound: cix2 >= 0 ? cix2 + 1 : 0,
    totalRounds: (room.totalRounds | 0) || 0,
    publicLog: g.publicLog || [],
    roundHits: g.roundHits || [],
    phase: g.phase || 'waiting',
    roomStatus: room.status
  }
}
