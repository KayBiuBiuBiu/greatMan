/**
 * 贴头猜词 · 6 位同房
 * 集合：headband_rooms, headband_players
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const _ = db.command

const HB_R = 'headband_rooms'
const HB_P = 'headband_players'

/** 部署校验：ping 应返回此字段，小程序据此判断是否为本仓库版本 */
const BUILD_ID = 'headband-repo-v6'

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

async function assertInRoom(rid, openId) {
  const room = await gRoom(rid)
  if (!room) {
    throw new Error('聚会组不存在或已结束')
  }
  const pls = await gPlayers(rid)
  if (!pls.some((p) => p.openId === openId)) {
    throw new Error('请先加入聚会组')
  }
  return { room, players: pls }
}

async function assertHost(room, openId) {
  if (room.hostOpenId !== openId) {
    throw new Error('仅组长可操作')
  }
}

/** 从 generateCharacters 返回项取展示用词 */
function wordFromItem(item) {
  if (!item || typeof item !== 'object') {
    return ''
  }
  const name = String(item.name || item.word || '').trim()
  return name
}

/** 内置词库（generateCharacters 不可用时兜底，勿依赖 AI 模块） */
const FALLBACK_BANK = {
  history: [
    '李白', '苏轼', '诸葛亮', '秦始皇', '武则天', '岳飞', '孔子', '曹操', '刘备', '项羽',
    '刘邦', '韩信', '司马迁', '霍去病', '林则徐', '孙中山', '鲁迅', '钱学森', '郑和', '康熙',
    '雍正', '乾隆', '朱元璋', '李世民', '杨玉环', '王昭君', '貂蝉', '西施', '项羽', '刘邦'
  ],
  entertainment: [
    '周杰伦', '刘德华', '成龙', '周星驰', '杨幂', '赵丽颖', '王一博', '肖战', '邓紫棋', '林俊杰',
    '王菲', '张学友', '张国荣', '梅艳芳', '黄渤', '沈腾', '贾玲', '易烊千玺', '王俊凯', '鹿晗',
    '邓超', '孙俪', '胡歌', '刘亦菲', '章子怡', '巩俐', '梁朝伟', '刘嘉玲', '陈奕迅', '李现'
  ],
  sports: [
    '姚明', '易建联', '李娜', '孙杨', '林丹', '马龙', '张继科', '郎平', '苏炳添', '谷爱凌',
    '梅西', 'C罗', '科比', '乔丹', '詹姆斯', '库里', '贝克汉姆', '罗纳尔多', '费德勒', '纳达尔',
    '刘翔', '郭晶晶', '吴敏霞', '丁宁', '朱婷', '谌龙', '樊振东', '孙颖莎', '王楚钦', '全红婵'
  ],
  anime: [
    '柯南', '路飞', '鸣人', '佐助', '小新', '哆啦A梦', '皮卡丘', '炭治郎', '祢豆子', '五条悟',
    '虎杖', '伏黑', '一护', '悟空', '贝吉塔', '樱', '纲手', '艾斯', '索隆', '山治',
    '娜美', '乔巴', '小兰', '灰原哀', '怪盗基德', '金木研', '利威尔', '三笠', '艾伦', '兵长'
  ],
  movie: [
    '钢铁侠', '蜘蛛侠', '蝙蝠侠', '超人', '美国队长', '雷神', '黑寡妇', '奇异博士', '洛基', '灭霸',
    '哈利波特', '赫敏', '邓布利多', '伏地魔', '杰克船长', '阿凡达', '哪吒', '孙悟空', '猪八戒', '唐僧',
    '紫霞', '至尊宝', '许仙', '白娘子', '小青', '李逵', '武松', '林冲', '鲁智深', '宋江'
  ],
  internet: [
    '李佳琦', '薇娅', '李子柒', 'papi酱', '罗翔', '何同学', '老番茄', '敬汉卿', '华农兄弟', '手工耿',
    '刘畊宏', '丁真', '谷爱凌', '冰墩墩', '蜜雪冰城', '可达鸭', '玲娜贝儿', '冰墩墩', '熊二', '光头强',
    '喜羊羊', '懒羊羊', '沸羊羊', '美羊羊', '灰太狼', '红太狼', '熊大', '熊二', '猪猪侠', '奥特曼'
  ]
}

function fallbackWordBank(config) {
  const cfg = config || DEFAULT_CONFIG
  const cat = FALLBACK_BANK[cfg.category] ? cfg.category : 'entertainment'
  const base = (FALLBACK_BANK[cat] || FALLBACK_BANK.entertainment).slice()
  const need = Math.max(10, Math.min(30, cfg.wordCount | 0) || 20)
  return shuf(base).slice(0, need)
}

/** 可选：调用 generateCharacters；失败则用内置词库 */
async function fetchWordBank(config) {
  const cfg = config || DEFAULT_CONFIG
  try {
    const res = await cloud.callFunction({
      name: 'generateCharacters',
      data: {
        category: cfg.category || 'entertainment',
        difficulty: cfg.difficulty || 'easy',
        count: Math.max(10, Math.min(30, cfg.wordCount | 0) || 20)
      }
    })
    const body = (res && res.result) || {}
    if (body.code !== 0) {
      throw new Error(body.message || 'code not 0')
    }
    const list = body.data || []
    const words = []
    for (let i = 0; i < list.length; i += 1) {
      const w = wordFromItem(list[i])
      if (w) {
        words.push(w)
      }
    }
    if (words.length) {
      return { words: words, source: 'cloud' }
    }
  } catch (e) {
    console.warn('[headband] generateCharacters unavailable, use fallback', e.message || e)
  }
  return { words: fallbackWordBank(cfg), source: 'fallback' }
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
  let wc = event.wordCount | 0
  if (wc !== 10 && wc !== 20 && wc !== 30) {
    wc = room.config.wordCount | 0 || 20
  }
  const config = { category: cat, difficulty: diff, wordCount: wc }
  await db.collection(HB_R).doc(rid).update({
    data: { config: config, updatedAt: t() }
  })
  return { ok: true, config: config }
}

async function doStartGame(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room, players } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status === 'playing') {
    throw new Error('游戏进行中，请先结束本局')
  }
  const n = players.length
  if (n < 2) {
    throw new Error('请至少 2 人进组再开始')
  }
  let bank = normalizeBank(event.wordBank)
  let wordSource = bank.length ? 'client' : ''
  if (!bank.length) {
    const fetched = await fetchWordBank(room.config || DEFAULT_CONFIG)
    bank = fetched.words || []
    wordSource = fetched.source || 'fallback'
  }
  if (bank.length < n) {
    throw new Error('词条数量不足（需要至少 ' + n + ' 个），请增加词条数量或更换分类/难度')
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
    version: 6,
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
    return {
      errMsg: '未知 action: ' + (rawAction || '(空)') + ' build=' + BUILD_ID
    }
  } catch (e) {
    return { errMsg: e.message || String(e) }
  }
}
