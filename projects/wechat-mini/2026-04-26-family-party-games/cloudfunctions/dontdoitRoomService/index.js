/**
 * 不要做挑战 · 6 位同房
 * 集合：dontdoit_rooms, dontdoit_players
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const _ = db.command

const DD_R = 'dontdoit_rooms'
const DD_P = 'dontdoit_players'
const BUILD_ID = 'dontdoit-repo-v2'

const DEFAULT_CONFIG = {
  difficulty: 'easy'
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

function elimSet(room) {
  return (room && room.eliminatedOpenIds) || []
}

function isEliminated(room, openId) {
  return elimSet(room).indexOf(openId) >= 0
}

function alivePlayers(players, room) {
  const es = elimSet(room)
  return (players || []).filter((p) => es.indexOf(p.openId) < 0)
}

async function gRoom(id) {
  const d = await db.collection(DD_R).doc(String(id)).get()
  return d.data
}

function normCode(code) {
  return String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
}

async function roomCodeTaken(code) {
  const c = normCode(code)
  if (c.length !== 6) {
    return true
  }
  const r = await db.collection(DD_R).where({ roomCode: c }).limit(1).get()
  return !!(r.data && r.data[0])
}

async function gRoomByCode(code) {
  const c = normCode(code)
  if (c.length !== 6) {
    return null
  }
  const r = await db
    .collection(DD_R)
    .where({ roomCode: c, status: _.neq('finished') })
    .limit(1)
    .get()
  return r.data[0] || null
}

async function gPlayers(rid) {
  const r = await db
    .collection(DD_P)
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

function actionFromItem(item) {
  if (!item || typeof item !== 'object') {
    return ''
  }
  return String(item.name || item.word || item.action || '').trim()
}

function parseJsonValue(text) {
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

function difficultyLabel(difficulty) {
  const map = {
    easy: '简单，容易不小心触发',
    medium: '中等，需要一点互动诱导',
    hard: '困难，适合熟人高能局'
  }
  return map[difficulty] || map.easy
}

function actionsFromAiText(text) {
  const body = parseJsonValue(text)
  if (Array.isArray(body)) {
    return normalizeBank(body)
  }
  if (body && Array.isArray(body.actions)) {
    return normalizeBank(body.actions)
  }
  return normalizeBank(String(text || '').split(/[\n,，、;；]/))
}

/** 拉取 AI 禁止动作；失败直接阻止开局 */
async function fetchActionBank(config, playerCount) {
  const cfg = config || DEFAULT_CONFIG
  const need = Math.max(playerCount | 0, 2)
  const system =
    '你是聚会小游戏「不要做挑战」的出题助手。只返回 JSON，不要解释。禁止动作必须适合全年龄线下聚会，安全、无低俗、无羞辱、不会造成危险。'
  const prompt =
    '请生成 ' +
    Math.max(need, 10) +
    ' 条「不要做挑战」禁止动作。难度：' +
    difficultyLabel(cfg.difficulty) +
    '。返回格式严格为：{"actions":["不能微笑","不能说我"]}。每条 4 到 12 个中文字符，以“不能”开头，尽量适合朋友聚会互动。'
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
  const words = actionsFromAiText(body.text)
  if (words.length < need) {
    throw new Error('AI 动作数量不足')
  }
  return { words: shuf(words).slice(0, Math.max(need, words.length)), source: 'ai' }
}

function normalizeBank(raw) {
  const out = []
  const seen = {}
  for (let i = 0; i < (raw || []).length; i += 1) {
    const item = raw[i]
    let w = typeof item === 'string' ? item.trim() : actionFromItem(item)
    if (!w || seen[w]) {
      continue
    }
    seen[w] = 1
    out.push(w)
  }
  return out
}

/** 组装前端 view（自己动作为保密，淘汰者不展示他人动作） */
function buildPublicView(room, players, viewerOpenId) {
  const es = elimSet(room)
  const playing = room.status === 'playing'
  const pubPlayers = (players || []).map((p) => {
    const isSelf = p.openId === viewerOpenId
    const out = isEliminated(room, p.openId)
    let displayAction = '—'
    if (!out) {
      if (playing && isSelf) {
        displayAction = '保密'
      } else {
        displayAction = String(p.myAction || '—').trim() || '—'
      }
    }
    return Object.assign(jp.withProfileReadyFlag(p), {
      isHost: !!p.isHost || p.openId === room.hostOpenId,
      displayAction: displayAction,
      isEliminated: out,
      eliminatedAt: p.eliminatedAt | 0
    })
  })
  const alive = alivePlayers(players, room)
  const survivorNicks = alive.map((p) => p.nickName).join('、')
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
    eliminatedOpenIds: es.slice(),
    eliminatedCount: es.length,
    aliveCount: alive.length,
    winnerOpenId: room.winnerOpenId || '',
    winnerNickName: room.winnerOpenId ? nn(players, room.winnerOpenId) : '',
    survivorNames: survivorNicks,
    startedAt: room.startedAt | 0,
    updatedAt: room.updatedAt | 0
  }
}

/** 淘汰一名玩家；若仅剩 1 人则结束 */
async function markEliminated(rid, room, targetOpenId) {
  if (isEliminated(room, targetOpenId)) {
    return room
  }
  const es = elimSet(room).slice()
  es.push(targetOpenId)
  const now = t()
  await db
    .collection(DD_P)
    .where({ roomId: rid, openId: targetOpenId })
    .update({
      data: { isEliminated: true, eliminatedAt: now, updatedAt: now }
    })
  const pls = await gPlayers(rid)
  const alive = alivePlayers(pls, { eliminatedOpenIds: es })
  const patch = {
    eliminatedOpenIds: es,
    updatedAt: now
  }
  if (alive.length <= 1 && room.status === 'playing') {
    patch.status = 'finished'
    patch.winnerOpenId = alive[0] ? alive[0].openId : ''
    patch.winnerOpenIds = alive.map((p) => p.openId)
  }
  await db.collection(DD_R).doc(rid).update({ data: patch })
  return gRoom(rid)
}

async function doCreate(event) {
  const openId = await oid()
  const nick = String(event.nickName || '房主').trim().slice(0, 12) || '房主'
  const av = String(event.avatarUrl || '').trim().slice(0, 500)
  for (let k = 0; k < 12; k += 1) {
    const code = c6()
    if (await roomCodeTaken(code)) {
      continue
    }
    const now = t()
    const add = await db.collection(DD_R).add({
      data: {
        roomCode: code,
        hostOpenId: openId,
        status: 'waiting',
        config: Object.assign({}, DEFAULT_CONFIG),
        eliminatedOpenIds: [],
        winnerOpenId: '',
        winnerOpenIds: [],
        createdAt: now,
        updatedAt: now,
        startedAt: 0
      }
    })
    const rid = add._id
    await db.collection(DD_P).add({
      data: {
        roomId: String(rid),
        openId: openId,
        nickName: nick,
        avatarUrl: av,
        isHost: true,
        myAction: '',
        isEliminated: false,
        eliminatedAt: 0,
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
    await db.collection(DD_P).add({
      data: Object.assign(
        {
          roomId: rid,
          openId: openId,
          isHost: openId === room.hostOpenId,
          myAction: '',
          isEliminated: false,
          eliminatedAt: 0,
          joinedAt: now
        },
        jp.mergeJoinFields(event, {})
      )
    })
  } else {
    await db
      .collection(DD_P)
      .where({ roomId: rid, openId: openId })
      .update({
        data: Object.assign(jp.mergeJoinFields(event, existed), { updatedAt: now })
      })
  }
  const pls2 = await gPlayers(rid)
  await db.collection(DD_R).doc(rid).update({ data: { updatedAt: now } })
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
  if (room.status === 'playing') {
    throw new Error('对局中不可修改设置')
  }
  const diffs = ['easy', 'medium', 'hard']
  const prev = room.config || DEFAULT_CONFIG
  const diff = diffs.indexOf(event.difficulty) >= 0 ? event.difficulty : prev.difficulty || 'easy'
  const config = { difficulty: diff }
  await db.collection(DD_R).doc(rid).update({
    data: { config: config, updatedAt: t() }
  })
  return { ok: true, config: config }
}

async function doSetPlayerAction(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const action = String(event.action || '').trim()
  const { room, players } = await assertInRoom(rid, openId)
  if (room.status !== 'waiting') {
    throw new Error('只能在等待阶段输入禁止动作')
  }
  if (!action || action.length < 2) {
    throw new Error('禁止动作长度不足，需要2个中文字符以上')
  }
  if (action.length > 20) {
    throw new Error('禁止动作超过20个字符')
  }
  await db
    .collection(DD_P)
    .where({ roomId: rid, openId: openId })
    .update({
      data: { inputAction: action, updatedAt: t() }
    })
  return { ok: true, inputAction: action }
}


async function doStartGame(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const playerAction = String(event.playerAction || '').trim()
  const { room, players } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status === 'playing') {
    throw new Error('游戏进行中，请先结束本局')
  }
  const n = players.length
  if (n < 2) {
    throw new Error('请至少 2 人进组再开始')
  }

  // 人工出题模式：收集所有玩家的输入
  const bank = []
  const actionMap = {} // openId -> action mapping
  for (let i = 0; i < players.length; i += 1) {
    const p = players[i]
    const pAction = p.inputAction ? String(p.inputAction).trim() : ''
    if (pAction && pAction.length > 0) {
      bank.push({ action: pAction, openId: p.openId })
      actionMap[p.openId] = pAction
    }
  }

  // 补充主持人即将输入的动作（第一次启动时）
  if (playerAction && n > 0) {
    const myIdx = players.findIndex(p => p.openId === openId)
    if (myIdx >= 0 && !actionMap[openId]) {
      bank.push({ action: playerAction, openId: openId })
      actionMap[openId] = playerAction
    }
  }

  if (bank.length < n) {
    throw new Error('动作数量不足，需要所有 ' + n + ' 人都输入禁止动作')
  }

  // 随机分配并确保没人拿到自己的动作
  const shuffled = derangement(bank)
  if (!shuffled) {
    throw new Error('分配失败，请重试')
  }

  const now = t()
  for (let i = 0; i < players.length; i += 1) {
    const p = players[i]
    const assigned = shuffled[i]
    await db
      .collection(DD_P)
      .where({ roomId: rid, openId: p.openId })
      .update({
        data: {
          myAction: assigned.action,
          isEliminated: false,
          eliminatedAt: 0,
          updatedAt: now
        }
      })
  }
  await db.collection(DD_R).doc(rid).update({
    data: {
      status: 'playing',
      startedAt: now,
      updatedAt: now,
      eliminatedOpenIds: [],
      winnerOpenId: '',
      winnerOpenIds: []
    }
  })
  const room2 = await gRoom(rid)
  const pls2 = await gPlayers(rid)
  return {
    ok: true,
    view: buildPublicView(room2, pls2, openId),
    wordSource: 'player'
  }
}

/** 完全错排：没有任何元素在原位置上的随机排列 */
function derangement(items) {
  if (!items || items.length === 0) {
    return []
  }
  const n = items.length
  const indices = Array.from({ length: n }, (_, i) => i)
  const result = []
  const maxTries = 100

  for (let tries = 0; tries < maxTries; tries += 1) {
    // Fisher-Yates shuffle
    const perm = indices.slice()
    for (let i = n - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1))
      const tmp = perm[i]
      perm[i] = perm[j]
      perm[j] = tmp
    }

    // 检查是否是完全错排（没人在原位）
    let isDerangement = true
    const openIds = items.map(it => it.openId)
    for (let i = 0; i < n; i += 1) {
      if (openIds[perm[i]] === openIds[i]) {
        isDerangement = false
        break
      }
    }

    if (isDerangement) {
      // 构建结果
      for (let i = 0; i < n; i += 1) {
        result.push(items[perm[i]])
      }
      return result
    }
  }

  // 如果失败，返回 null
  return null
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
  return {
    ok: true,
    myOpenId: openId,
    inRoom: pls.some((p) => p.openId === openId),
    view: buildPublicView(room, pls, openId)
  }
}

/** 玩家自认触发禁止动作 → 淘汰自己 */
async function doSubmitAction(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room, players } = await assertInRoom(rid, openId)
  if (room.status !== 'playing') {
    throw new Error('当前未在进行中')
  }
  if (isEliminated(room, openId)) {
    throw new Error('你已被淘汰')
  }
  const me = players.find((p) => p.openId === openId)
  if (!me || !me.myAction) {
    throw new Error('未分配禁止动作')
  }
  const room2 = await markEliminated(rid, room, openId)
  const pls2 = await gPlayers(rid)
  const finished = room2.status === 'finished'
  return {
    ok: true,
    eliminated: true,
    self: true,
    finished: finished,
    view: buildPublicView(room2, pls2, openId),
    eliminatedNickName: me.nickName
  }
}

/** 组长强制淘汰某人 */
async function doEliminatePlayer(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const target = String(event.targetOpenId || '').trim()
  if (!target) {
    throw new Error('缺少 targetOpenId')
  }
  const { room, players } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status !== 'playing') {
    throw new Error('当前未在进行中')
  }
  if (isEliminated(room, target)) {
    throw new Error('该玩家已淘汰')
  }
  const room2 = await markEliminated(rid, room, target)
  const pls2 = await gPlayers(rid)
  return {
    ok: true,
    eliminated: true,
    targetOpenId: target,
    finished: room2.status === 'finished',
    view: buildPublicView(room2, pls2, openId),
    eliminatedNickName: nn(players, target)
  }
}

async function doEndGame(event) {
  const openId = await oid()
  const rid = String(event.roomId || '')
  const { room, players } = await assertInRoom(rid, openId)
  await assertHost(room, openId)
  if (room.status !== 'playing') {
    throw new Error('当前无进行中的局')
  }
  const alive = alivePlayers(players, room)
  await db.collection(DD_R).doc(rid).update({
    data: {
      status: 'finished',
      winnerOpenId: alive[0] ? alive[0].openId : '',
      winnerOpenIds: alive.map((p) => p.openId),
      updatedAt: t()
    }
  })
  const room2 = await gRoom(rid)
  const pls2 = await gPlayers(rid)
  return { ok: true, view: buildPublicView(room2, pls2, openId) }
}

async function doPing() {
  const openId = await oid()
  let roomsOk = false
  let playersOk = false
  try {
    await db.collection(DD_R).count()
    roomsOk = true
  } catch (e) {}
  try {
    await db.collection(DD_P).count()
    playersOk = true
  } catch (e) {}
  return {
    ok: roomsOk && playersOk,
    service: 'dontdoitRoomService',
    buildId: BUILD_ID,
    hasOpenId: !!openId,
    roomsOk: roomsOk,
    playersOk: playersOk,
    ts: t()
  }
}

const ACTION_ALIASES = {
  createRoom: 'create',
  joinRoom: 'join',
  getRoom: 'getView',
  submitGuess: 'submitAction',
  start: 'startGame',
  playAgain: 'startGame',
  restartGame: 'startGame'
}

function normalizeEvent(raw) {
  const e = raw || {}
  let action = String(e.action || e.type || '').trim()
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
    if (action === 'setPlayerAction') {
      return await doSetPlayerAction(ev)
    }
    if (action === 'startGame') {
      return await doStartGame(ev)
    }
    if (action === 'getView' || action === 'syncState') {
      return await doGetView(ev)
    }
    if (action === 'submitAction' || action === 'submitGuess') {
      return await doSubmitAction(ev)
    }
    if (action === 'eliminatePlayer') {
      return await doEliminatePlayer(ev)
    }
    if (action === 'endGame') {
      return await doEndGame(ev)
    }
    return { errMsg: '未知 action: ' + (rawAction || '(空)') + ' build=' + BUILD_ID }
  } catch (e) {
    return { errMsg: e.message || String(e) }
  }
}
