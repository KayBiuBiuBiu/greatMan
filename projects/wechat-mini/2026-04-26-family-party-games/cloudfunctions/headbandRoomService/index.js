/**
 * 贴头猜词 · 6 位同房
 * 集合：headband_rooms, headband_players
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
const { seedPlayersCollection } = require('./testSeedPlayers')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const _ = db.command

const HB_R = 'headband_rooms'
const HB_P = 'headband_players'

/** 部署校验：ping 应返回此字段，小程序据此判断是否为本仓库版本 */
const BUILD_ID = 'headband-repo-v8'

const DEFAULT_CONFIG = {
  category: 'entertainment',
  difficulty: 'easy',
  wordCount: 20
}

const t = () => Date.now()

async function oid() {
  return cloud.getWXContext().OPENID
}

function c6() {
  return String(100000 + ((Math.random() * 900000) | 0))
}

function shuf(arr) {
  const x = (arr || []).slice()
  for (let i = x.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    const tmp = x[i]
    x[i] = x[j]
    x[j] = tmp
  }
  return x
}

function clampWordCount(v) {
  const n = v | 0
  if (n === 10 || n === 20 || n === 30 || n === 50) {
    return n
  }
  return 20
}

function nn(pl, openId) {
  const f = (pl || []).find((p) => p.openId === openId)
  return f ? f.nickName : '参与者'
}

async function gRoom(id) {
  const d = await db
    .collection(HB_R)
    .doc(String(id))
    .get()
  return d.data
}

function normCode(code) {
  return String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
}

/** 口令是否已被任意房间占用（roomCode 唯一索引） */
async function roomCodeTaken(code) {
  const c = normCode(code)
  if (c.length !== 6) {
    return true
  }
  const r = await db.collection(HB_R).where({ roomCode: c }).limit(1).get()
  return !!(r.data && r.data[0])
}

/** 按口令查找可加入的房间（未结束） */
async function gRoomByCode(code) {
  const c = normCode(code)
  if (c.length !== 6) {
    return null
  }
  const r = await db
    .collection(HB_R)
    .where({ roomCode: c, status: _.neq('finished') })
    .limit(1)
    .get()
  return r.data[0] || null
}

async function gPlayers(rid) {
  const r = await db
    .collection(HB_P)
    .where({ roomId: String(rid) })
    .get()
  return (r.data || []).slice().sort((a, b) => (a.joinedAt | 0) - (b.joinedAt | 0))
}

async function assertInRoom(rid, openId, event) {
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('聚会组不存在或已结束')
  }
  const pls = await gPlayers(rid)
  if (event && event._test) {
    return { room, players: pls }
  }
  if (!pls.some((p) => p.openId === openId)) {
    throw new Error('请先加入聚会组')
  }
  return { room, players: pls }
}

async function assertHost(room, openId, event) {
  if (event && event._test) {
    return
  }
  if (room.hostOpenId !== openId) {
    throw new Error('仅组长可操作')
  }
}

/** 从 AI 返回项取展示用词 */
function wordFromItem(item) {
  if (!item || typeof item !== 'object') {
    return ''
  }
  const name = String(item.name || item.word || '').trim()
  return name
}

function categoryLabel(category) {
  const map = {
    history: '历史名人',
    entertainment: '娱乐明星',
    sports: '体育人物',
    anime: '动漫角色',
    movie: '影视角色',
    internet: '网络热门'
  }
  return map[category] || '娱乐明星'
}

function difficultyLabel(difficulty) {
  const map = {
    easy: '简单，大家熟悉',
    medium: '中等，有一定辨识度',
    hard: '困难，适合熟人局'
  }
  return map[difficulty] || map.easy
}

function parseAiWordBank(text) {
  const raw = String(text || '').trim()
  if (!raw) {
    return []
  }
  const tryJson = (s) => {
    try {
      return JSON.parse(s)
    } catch (e) {
      return null
    }
  }
  let body = tryJson(raw)
  if (!body) {
    const obj = raw.match(/\{[\s\S]*\}/)
    const arr = raw.match(/\[[\s\S]*\]/)
    body = tryJson(obj && obj[0]) || tryJson(arr && arr[0])
  }
  if (Array.isArray(body)) {
    return normalizeBank(body)
  }
  if (body && typeof body === 'object' && Array.isArray(body.words)) {
    return normalizeBank(body.words)
  }
  return normalizeBank(
    raw
      .split(/[\n,，、;；]/)
      .map((x) => x.replace(/^\s*[-*\d.、)）]+/, '').trim())
  )
}

async function fetchAiWordBank(config) {
  const cfg = config || DEFAULT_CONFIG
  const need = Math.max(10, Math.min(50, cfg.wordCount | 0) || 20)
  const system =
    '你是家庭聚会小游戏「贴头猜词」的出题助手。只返回 JSON，不要解释。词条必须是适合全年龄聚会的中文人物、角色或公众熟悉对象，避免低俗、敏感和重复。'
  const prompt =
    '请生成 ' +
    need +
    ' 个贴头猜词词条。分类：' +
    categoryLabel(cfg.category) +
    '；难度：' +
    difficultyLabel(cfg.difficulty) +
    '。返回格式严格为：{"words":["词条1","词条2"]}。每个词条 2 到 8 个中文字符，尽量不要包含标点。'
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
  const words = parseAiWordBank(body.text)
  if (words.length < need) {
    throw new Error('AI 词条不足')
  }
  return words.slice(0, need)
}

/** 贴头猜词只使用 AI 出题；AI 不可用时阻止开局 */
async function fetchWordBank(config) {
  const cfg = config || DEFAULT_CONFIG
  try {
    const words = await fetchAiWordBank(cfg)
    return { words: words, source: 'ai' }
  } catch (e) {
    const detail = String((e && e.message) || e || '').trim()
    console.warn('[headband] aiPartyService unavailable', detail)
    throw new Error(
      detail && !/AI 词库生成失败/.test(detail)
        ? 'AI 词库生成失败：' + detail
        : 'AI 词库生成失败，请确认 aiPartyService 已部署且 HUNYUAN_API_KEY / 混元 AI 已配置'
    )
  }
}

function normalizeBank(raw) {
  const out = []
  const seen = {}
  for (let i = 0; i < (raw || []).length; i += 1) {
    const item = raw[i]
    let w = ''
    if (typeof item === 'string') {
      w = item.trim()
    } else if (item && typeof item === 'object') {
      w = wordFromItem(item)
    }
    if (!w || seen[w]) {
      continue
    }
    seen[w] = 1
    out.push(w)
  }
  return out
}

function normText(s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '')
}

/** 构建 getView / syncState 返回（displayWord 隐私） */
function buildPublicView(room, players, viewerOpenId) {
  const pubPlayers = (players || []).map((p) => {
    const isSelf = p.openId === viewerOpenId
    return Object.assign(jp.withProfileReadyFlag(p), {
      isHost: !!p.isHost || p.openId === room.hostOpenId,
      displayWord:
        room.status === 'playing' && isSelf
          ? '保密'
          : String(p.myWord || '—').trim() || '—'
    })
  })
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    status: room.status || 'waiting',
    config: room.config || DEFAULT_CONFIG,
    hostOpenId: room.hostOpenId,
    isHost: room.hostOpenId === viewerOpenId,
    myOpenId: viewerOpenId,
    players: pubPlayers,
    playerCount: pubPlayers.length,
    winnerOpenId: room.winnerOpenId || '',
    winnerNickName: room.winnerOpenId ? nn(players, room.winnerOpenId) : '',
    startedAt: room.startedAt | 0,
    updatedAt: room.updatedAt | 0
  }
}

async function doCreate(event) {
  const openId = await oid()
  const nick = String(event.nickName || '房主')
    .trim()
    .slice(0, 12) || '房主'
  const av = String(event.avatarUrl || '').trim().slice(0, 500)

  // 测试模式：快速创建不检查房间号重复
  if (event._test) {
    const code = '000001'
    const now = t()
    const add = await db.collection(HB_R).add({
      data: {
        roomCode: code,
        hostOpenId: openId,
        status: 'waiting',
        config: Object.assign({}, DEFAULT_CONFIG),
        winnerOpenId: '',
        createdAt: now,
        updatedAt: now,
        startedAt: 0
      }
    })
    const rid = add._id
    await db.collection(HB_P).add({
      data: {
        roomId: String(rid),
        openId: openId,
        nickName: nick,
        avatarUrl: av,
        isHost: true,
        myWord: '',
        joinedAt: now
      }
    })
    return {
      ok: true,
      roomId: String(rid),
      roomCode: code,
      myOpenId: openId,
      playerCount: 1
    }
  }

  for (let k = 0; k < 12; k += 1) {
    const code = c6()
    if (await roomCodeTaken(code)) {
      continue
    }
    const now = t()
    const add = await db.collection(HB_R).add({
      data: {
        roomCode: code,
        hostOpenId: openId,
        status: 'waiting',
        config: Object.assign({}, DEFAULT_CONFIG),
        winnerOpenId: '',
        createdAt: now,
        updatedAt: now,
        startedAt: 0
      }
    })
    const rid = add._id
    await db.collection(HB_P).add({
      data: {
        roomId: String(rid),
        openId: openId,
        nickName: nick,
        avatarUrl: av,
        isHost: true,
        myWord: '',
        joinedAt: now
      }
    })
    return {
      ok: true,
      roomId: String(rid),
      roomCode: code,
      myOpenId: openId,
      playerCount: 1
    }
  }
  throw new Error('生成口令失败，请重试')
}

async function doJoin(event) {
  const openId = await oid()
  const now = t()
  let room = null
  if (event.roomId) {
    room = await gRoom(event.roomId)
  } else {
    room = await gRoomByCode(event.roomCode)
  }
  if (!room) {
    throw new Error('聚会组不存在或已结束')
  }
  if (room.status === 'playing') {
    throw new Error('游戏已开始，无法加入')
  }
  const rid = String(room._id)
  const pls = await gPlayers(rid)
  const existed = pls.find((p) => p.openId === openId)
  if (!existed) {
    await db.collection(HB_P).add({
      data: Object.assign(
        {
          roomId: rid,
          openId: openId,
          isHost: openId === room.hostOpenId,
          myWord: '',
          joinedAt: now
        },
        jp.mergeJoinFields(event, {})
      )
    })
  } else {
    await db
      .collection(HB_P)
      .where({ roomId: rid, openId: openId })
      .update({
        data: Object.assign(jp.mergeJoinFields(event, existed), { updatedAt: now })
      })
  }
  const pls2 = await gPlayers(rid)
  await db.collection(HB_R).doc(rid).update({ data: { updatedAt: now } })
  return {
    ok: true,
    roomId: rid,
    roomCode: room.roomCode,
    myOpenId: openId,
    playerCount: pls2.length,
    view: buildPublicView(room, pls2, openId)
  }
}

async function doSetConfig(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status !== 'waiting') {
    throw new Error('仅等待阶段可修改设置')
  }
  const cats = ['history', 'entertainment', 'sports', 'anime', 'movie', 'internet']
  const diffs = ['easy', 'medium', 'hard']
  const cat = cats.indexOf(event.category) >= 0 ? event.category : room.config.category
  const diff = diffs.indexOf(event.difficulty) >= 0 ? event.difficulty : room.config.difficulty
  let wc = clampWordCount(event.wordCount)
  const config = { category: cat, difficulty: diff, wordCount: wc }
  await db.collection(HB_R).doc(rid).update({
    data: { config: config, updatedAt: t() }
  })
  return { ok: true, config: config }
}

async function doStartGame(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room, players } = await assertInRoom(rid, openId, event)
  await assertHost(room, openId, event)
  if (room.status === 'playing') {
    throw new Error('游戏进行中，请先结束本局')
  }
  const n = players.length
  if (n < 2) {
    throw new Error('请至少 2 人进组再开始')
  }
  let bank = []
  let wordSource = 'test'
  if (event && event._test) {
    bank = ['苹果', '香蕉', '西瓜', '葡萄', '橙子', '草莓', '桃子', '梨子', '芒果', '樱桃', '柠檬', '荔枝']
  } else {
    const fetched = await fetchWordBank(room.config || DEFAULT_CONFIG)
    bank = fetched.words || []
    wordSource = fetched.source || 'ai'
    if (bank.length < n) {
      throw new Error('词条数量不足（需要至少 ' + n + ' 个），请增加词条数量或更换分类/难度')
    }
  }
  const shuffled = shuf(bank)
  const now = t()
  for (let i = 0; i < players.length; i += 1) {
    const p = players[i]
    const word = shuffled[i]
    await db
      .collection(HB_P)
      .where({ roomId: rid, openId: p.openId })
      .update({
        data: { myWord: word, updatedAt: now }
      })
  }
  await db.collection(HB_R).doc(rid).update({
    data: {
      status: 'playing',
      startedAt: now,
      updatedAt: now,
      winnerOpenId: ''
    }
  })
  const room2 = await gRoom(rid)
  const pls2 = await gPlayers(rid)
  return {
    ok: true,
    view: buildPublicView(room2, pls2, openId),
    wordCount: bank.length,
    wordSource: wordSource
  }
}

async function doGetView(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  if (!rid) {
    throw new Error('缺少 roomId')
  }
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('聚会组不存在')
  }
  const pls = await gPlayers(rid)
  const inRoom = pls.some((p) => p.openId === openId)
  return {
    ok: true,
    myOpenId: openId,
    inRoom: inRoom,
    view: buildPublicView(room, pls, openId)
  }
}

async function doSubmitGuess(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const guess = normText(event.guess)
  if (!guess) {
    throw new Error('请输入猜测')
  }
  const { room, players } = await assertInRoom(rid, openId)
  if (room.status !== 'playing') {
    throw new Error('当前未在进行中')
  }
  const me = players.find((p) => p.openId === openId)
  if (!me || !me.myWord) {
    throw new Error('未分配词语')
  }
  const correct = normText(me.myWord) === guess
  if (!correct) {
    return { ok: true, correct: false }
  }
  const now = t()
  await db.collection(HB_R).doc(rid).update({
    data: {
      status: 'finished',
      winnerOpenId: openId,
      updatedAt: now
    }
  })
  return {
    ok: true,
    correct: true,
    winner: true,
    winnerOpenId: openId,
    winnerNickName: me.nickName
  }
}

/** 连通性检测：确认云函数已部署且能访问两集合 */
async function doPing() {
  const openId = await oid()
  let roomsOk = false
  let playersOk = false
  let roomsErr = ''
  let playersErr = ''
  try {
    await db.collection(HB_R).count()
    roomsOk = true
  } catch (e) {
    roomsErr = (e && e.message) || String(e)
  }
  try {
    await db.collection(HB_P).count()
    playersOk = true
  } catch (e) {
    playersErr = (e && e.message) || String(e)
  }
  return {
    ok: roomsOk && playersOk,
    service: 'headbandRoomService',
    buildId: BUILD_ID,
    version: 8,
    hasOpenId: !!openId,
    roomsOk: roomsOk,
    playersOk: playersOk,
    roomsErr: roomsErr,
    playersErr: playersErr,
    ts: t()
  }
}

async function doEndGame(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status !== 'playing') {
    throw new Error('当前无进行中的局')
  }
  await db.collection(HB_R).doc(rid).update({
    data: { status: 'finished', updatedAt: t() }
  })
  return { ok: true }
}

/** 云台 / 文档 action 别名 → 本仓库实现名 */
const ACTION_ALIASES = {
  createRoom: 'create',
  joinRoom: 'join',
  getRoom: 'getView',
  leaveRoom: 'leave',
  start: 'startGame',
  start_game: 'startGame',
  playAgain: 'startGame',
  restartGame: 'startGame'
}

function normalizeEvent(raw) {
  const e = raw || {}
  let action = String(e.action || e.type || e.cmd || '').trim()
  if (!action && e.data && typeof e.data === 'object') {
    action = String(e.data.action || '').trim()
  }
  return Object.assign({}, e, { action: action })
}

exports.main = async function (event) {
  const ev = normalizeEvent(event)
  const rawAction = ev.action
  let action = rawAction
  if (action && ACTION_ALIASES[action]) {
    action = ACTION_ALIASES[action]
  }
  try {
    if (action === 'ping') {
      return await doPing()
    }
    if (action === 'create') {
      return await doCreate(ev)
    }
    if (action === 'join') {
      return await doJoin(ev)
    }
    if (action === 'setConfig') {
      return await doSetConfig(ev)
    }
    if (action === 'startGame') {
      return await doStartGame(ev)
    }
    if (action === 'getView' || action === 'syncState') {
      return await doGetView(ev)
    }
    if (action === 'submitGuess') {
      return await doSubmitGuess(ev)
    }
    if (action === 'endGame') {
      return await doEndGame(ev)
    }
    if (action === 'leave') {
      return { ok: true, buildId: BUILD_ID, note: 'leave 暂未实现，可直接关闭页面' }
    }
    if (action === 'updatePlayerWord') {
      return await doStartGame(ev)
    }
    if (action === '__testSeedPlayers') {
      return await doTestSeedPlayers(ev)
    }
    return {
      errMsg: '未知 action: ' + (rawAction || '(空)') + ' build=' + BUILD_ID
    }
  } catch (e) {
    return { errMsg: e.message || String(e) }
  }
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
    playersCol: HB_P,
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
      myWord: '',
      joinedAt: t()
    }),
    refreshState: async (id) => {
      await db.collection(HB_R).doc(id).update({ data: { updatedAt: t() } })
    }
  })
}
