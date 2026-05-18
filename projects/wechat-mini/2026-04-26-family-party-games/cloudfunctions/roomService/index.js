const cloud = require('wx-server-sdk')

cloud.init({
  env: cloud.DYNAMIC_CURRENT_ENV
})

const db = cloud.database()
const _ = db.command
const ROOMS = 'rooms'
const ROOM_TTL = 1000 * 60 * 60 * 4

function createRoomCode() {
  return String(Math.floor(1000 + Math.random() * 9000))
}

function normalizeNickName(nickName) {
  const value = String(nickName || '').trim()
  return value.slice(0, 12) || '参与者'
}

function normalizeRoomCode(roomCode) {
  return String(roomCode || '').replace(/\D/g, '').slice(0, 4)
}

function normalizeAvatarUrl(avatarUrl) {
  return String(avatarUrl || '').trim().slice(0, 500)
}

async function getOpenId() {
  return cloud.getWXContext().OPENID
}

async function findActiveRoom(roomCode) {
  const expireAt = Date.now() - ROOM_TTL
  const result = await db.collection(ROOMS)
    .where({
      roomCode,
      status: _.neq('closed'),
      updatedAt: _.gt(expireAt)
    })
    .limit(1)
    .get()

  return result.data[0] || null
}

function publicRoom(room, currentOpenId) {
  if (!room) return null
  return {
    id: room._id,
    roomCode: room.roomCode,
    hostOpenId: room.hostOpenId,
    currentOpenId,
    players: room.players || [],
    selectedGame: room.selectedGame || null,
    status: room.status || 'waiting',
    createdAt: room.createdAt,
    updatedAt: room.updatedAt
  }
}

async function createRoom(event) {
  const openId = await getOpenId()
  const now = Date.now()
  const nickName = normalizeNickName(event.nickName)
  const avatarUrl = normalizeAvatarUrl(event.avatarUrl)
  const selectedGame = event.selectedGame || null
  const status = event.status || 'waiting'
  let roomCode = createRoomCode()

  for (let i = 0; i < 8; i += 1) {
    const existing = await findActiveRoom(roomCode)
    if (!existing) break
    roomCode = createRoomCode()
  }

  const room = {
    roomCode,
    hostOpenId: openId,
    players: [
      {
        openId,
        nickName,
        avatarUrl,
        isHost: true,
        joinedAt: now
      }
    ],
    selectedGame,
    status,
    createdAt: now,
    updatedAt: now
  }

  const result = await db.collection(ROOMS).add({ data: room })
  return publicRoom(Object.assign({}, room, { _id: result._id }), openId)
}

async function joinRoom(event) {
  const openId = await getOpenId()
  const now = Date.now()
  const roomCode = normalizeRoomCode(event.roomCode)
  const nickName = normalizeNickName(event.nickName)
  const avatarUrl = normalizeAvatarUrl(event.avatarUrl)

  if (roomCode.length !== 4) {
    throw new Error('请输入4位口令')
  }

  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }

  const players = room.players || []
  const existed = players.some(function (player) {
    return player.openId === openId
  })

  const nextPlayers = existed
    ? players.map(function (player) {
      if (player.openId === openId) {
        return Object.assign({}, player, { nickName, avatarUrl })
      }
      return player
    })
    : players.concat([
      {
        openId,
        nickName,
        avatarUrl,
        isHost: openId === room.hostOpenId,
        joinedAt: now
      }
    ])

  await db.collection(ROOMS).doc(room._id).update({
    data: {
      players: nextPlayers,
      updatedAt: now
    }
  })

  return publicRoom(Object.assign({}, room, {
    players: nextPlayers,
    updatedAt: now
  }), openId)
}

async function getRoom(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  return publicRoom(room, openId)
}

async function startRoom(event) {
  const openId = await getOpenId()
  const now = Date.now()
  const roomCode = normalizeRoomCode(event.roomCode)
  const selectedGame = event.selectedGame || null
  const room = await findActiveRoom(roomCode)

  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }

  if (room.hostOpenId !== openId) {
    throw new Error('只有主持可以开始')
  }

  await db.collection(ROOMS).doc(room._id).update({
    data: {
      selectedGame,
      status: 'started',
      updatedAt: now
    }
  })

  return publicRoom(Object.assign({}, room, {
    selectedGame,
    status: 'started',
    updatedAt: now
  }), openId)
}

async function closeRoom(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)

  if (!room) return null
  if (room.hostOpenId !== openId) {
    throw new Error('只有主持可以关闭聚会组')
  }

  await db.collection(ROOMS).doc(room._id).update({
    data: {
      status: 'closed',
      updatedAt: Date.now()
    }
  })

  return { ok: true }
}

/**
 * 将主持权移交给聚会组内另一名成员（仅当前主持可调用）。
 */
async function transferHost(event) {
  const openId = await getOpenId()
  const now = Date.now()
  const roomCode = normalizeRoomCode(event.roomCode)
  const targetOpenId = String(event.targetOpenId || '').trim()
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('只有主持可以移交主持权')
  }
  if (!targetOpenId) {
    throw new Error('请指定新任主持')
  }
  if (targetOpenId === openId) {
    throw new Error('不能交给自己')
  }
  const players = room.players || []
  const ok = players.some(function (p) {
    return p.openId === targetOpenId
  })
  if (!ok) {
    throw new Error('所选成员不在聚会组内')
  }
  const nextPlayers = players.map(function (player) {
    return Object.assign({}, player, { isHost: player.openId === targetOpenId })
  })
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      hostOpenId: targetOpenId,
      players: nextPlayers,
      updatedAt: now
    }
  })
  const merged = Object.assign({}, room, {
    hostOpenId: targetOpenId,
    players: nextPlayers,
    updatedAt: now
  })
  return publicRoom(merged, openId)
}

/**
 * 主持主动卸任：按进组时间（joinedAt 升序）将主持交给第一位其他成员。
 */
async function abdicateHost(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('只有主持可以移交主持权')
  }
  const players = room.players || []
  const others = players
    .filter(function (p) {
      return p.openId !== openId
    })
    .sort(function (a, b) {
      return (a.joinedAt || 0) - (b.joinedAt || 0)
    })
  if (!others.length) {
    throw new Error('组内暂无其他成员可接任主持')
  }
  const nextHost = others[0].openId
  const now = Date.now()
  const nextPlayers = players.map(function (player) {
    return Object.assign({}, player, { isHost: player.openId === nextHost })
  })
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      hostOpenId: nextHost,
      players: nextPlayers,
      updatedAt: now
    }
  })
  const merged = Object.assign({}, room, {
    hostOpenId: nextHost,
    players: nextPlayers,
    updatedAt: now
  })
  return publicRoom(merged, openId)
}

function shuffleIds(ids) {
  const a = ids.slice()
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    const t = a[i]
    a[i] = a[j]
    a[j] = t
  }
  return a
}

/**
 * 主持人发词：按当前房间内 openId 列表随机身份，每人仅能从 undercoverGetWord 取到自己的词
 * event: { roomCode, pair: [民词, 卧词], undercoverCount }
 */
async function undercoverAssign(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('仅主持人可发词')
  }
  const pair = event.pair
  if (!Array.isArray(pair) || String(pair[0] || '').length === 0 || String(pair[1] || '').length === 0) {
    throw new Error('词对无效')
  }
  const players = room.players || []
  if (players.length < 3) {
    throw new Error('请至少3位参与者进组再发词（每人手机分别进组）')
  }
  let ucount = Math.max(1, parseInt(event.undercoverCount, 10) || 1)
  if (ucount >= players.length) {
    ucount = Math.max(1, players.length - 1)
  }
  const pids = shuffleIds(players.map((p) => p.openId))
  const uSet = new Set(pids.slice(0, ucount))
  const assignments = players.map((p) => {
    const isU = uSet.has(p.openId)
    return {
      openId: p.openId,
      nickName: p.nickName,
      role: isU ? 'undercover' : 'civilian',
      word: isU ? pair[1] : pair[0]
    }
  })
  const now = Date.now()
  const prevU = room.undercover
  const ver = (prevU && prevU.version) ? prevU.version + 1 : 1
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      undercover: { pair, assignments, version: ver },
      updatedAt: now
    }
  })
  return { ok: true, playerCount: players.length, undercoverCount: ucount, version: ver }
}

/**
 * 当前用户在本局的词与身份（不泄露他人）
 */
async function undercoverGetWord(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  const u = room.undercover
  if (!u || !u.assignments || u.assignments.length === 0) {
    throw new Error('主持人尚未发词')
  }
  const row = u.assignments.find((a) => a.openId === openId)
  if (!row) {
    throw new Error('你不在本环节参与者列表中，请重新用同一账号进组')
  }
  return {
    word: row.word,
    role: row.role,
    nickName: row.nickName,
    pair: u.pair
  }
}

/**
 * 仅主持人：本环节内参与者身份（不含词），供本机投票，他人不可调
 */
async function undercoverGetHostRoster(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('仅主持人可查看本环节名单')
  }
  const u = room.undercover
  if (!u || !u.assignments || u.assignments.length === 0) {
    throw new Error('尚未发词')
  }
  const roster = u.assignments.map((a) => {
    return {
      openId: a.openId,
      nickName: a.nickName,
      role: a.role
    }
  })
  return { pair: u.pair, roster: roster }
}

// 仅平票时下发给客户端（隐藏彩蛋，不在其它界面提及）
const TRUTH_DARE_CURSE = '黄君的诅咒\n当场完成俯卧撑 20 个，并大声喊「鸡你太美」！\n由大家监督完成。主持点「进入下一轮」进入下一局。'

/**
 * 真心话大冒险·同场：随机被选中，他人投票；得票多定类型；平票时下发彩蛋文案（不对外宣导）
 */
async function tdStart(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('仅主持人可开始新轮')
  }
  const players = room.players || []
  if (players.length < 2) {
    throw new Error('请至少2位参与者进组再开始')
  }
  const t = players[Math.floor(Math.random() * players.length)]
  const round = (room.truthDare && room.truthDare.round) ? room.truthDare.round + 1 : 1
  const now = Date.now()
  const truthDare = {
    targetOpenId: t.openId,
    targetNickName: t.nickName,
    tdVotes: [],
    phase: 'voting',
    round: round,
    lastTally: null
  }
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      truthDare: truthDare,
      updatedAt: now
    }
  })
  return { targetOpenId: t.openId, targetNickName: t.nickName, round: round, playerCount: players.length }
}

async function tdVote(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const choice = String(event.choice || '') === 'dare' ? 'dare' : 'truth'
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  const td = room.truthDare
  if (!td || td.phase !== 'voting' || !td.targetOpenId) {
    throw new Error('当前没有进行中的投票')
  }
  if (td.targetOpenId === openId) {
    throw new Error('本轮你被选中了，请让其他人点真心话/大冒险')
  }
  const list = (td.tdVotes || []).filter((v) => v.openId !== openId)
  list.push({ openId: openId, choice: choice })
  const now = Date.now()
  let t = 0
  let d = 0
  for (let k = 0; k < list.length; k += 1) {
    if (list[k].choice === 'truth') {
      t += 1
    } else {
      d += 1
    }
  }
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      'truthDare.tdVotes': list,
      updatedAt: now
    }
  })
  return { ok: true, choice: choice, truthCount: t, dareCount: d }
}

async function tdTally(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  if (room.hostOpenId !== openId) {
    throw new Error('仅主持人可结束投票并结算')
  }
  const td = room.truthDare
  if (!td || td.phase !== 'voting') {
    throw new Error('没有可结算的投票')
  }
  const list = td.tdVotes || []
  let t = 0
  let d = 0
  for (let i = 0; i < list.length; i += 1) {
    if (list[i].choice === 'truth') {
      t += 1
    } else {
      d += 1
    }
  }
  const tie = t === d
  let lastTally
  if (tie) {
    lastTally = { tie: true, truthCount: t, dareCount: d, winner: null, curseText: TRUTH_DARE_CURSE }
  } else {
    const winner = t > d ? 'truth' : 'dare'
    lastTally = { tie: false, truthCount: t, dareCount: d, winner: winner, curseText: null }
  }
  const now = Date.now()
  const nextTd = Object.assign({}, td, { phase: 'resolved', lastTally: lastTally })
  await db.collection(ROOMS).doc(room._id).update({
    data: {
      truthDare: nextTd,
      updatedAt: now
    }
  })
  return lastTally
}

async function tdGetState(event) {
  const openId = await getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const room = await findActiveRoom(roomCode)
  if (!room) {
    throw new Error('聚会组不存在或已过期')
  }
  const isHost = room.hostOpenId === openId
  const td = room.truthDare
  if (!td || !td.targetOpenId) {
    return {
      isHost: isHost,
      currentOpenId: openId,
      phase: 'none',
      targetOpenId: '',
      targetNickName: '',
      round: 0,
      truthCount: 0,
      dareCount: 0,
      myChoice: null,
      lastTally: null
    }
  }
  const list = td.tdVotes || []
  let t = 0
  let d = 0
  for (let i = 0; i < list.length; i += 1) {
    if (list[i].choice === 'truth') {
      t += 1
    } else {
      d += 1
    }
  }
  const mine = list.find((v) => v.openId === openId)
  return {
    isHost: isHost,
    currentOpenId: openId,
    phase: td.phase,
    targetOpenId: td.targetOpenId,
    targetNickName: td.targetNickName,
    round: td.round,
    truthCount: t,
    dareCount: d,
    myChoice: mine ? mine.choice : null,
    lastTally: td.lastTally || null
  }
}

exports.main = async function (event) {
  const action = event.action

  if (action === 'create') return createRoom(event)
  if (action === 'join') return joinRoom(event)
  if (action === 'get') return getRoom(event)
  if (action === 'start') return startRoom(event)
  if (action === 'close') return closeRoom(event)
  if (action === 'undercoverAssign') return undercoverAssign(event)
  if (action === 'undercoverGetWord') return undercoverGetWord(event)
  if (action === 'undercoverGetHostRoster') return undercoverGetHostRoster(event)
  if (action === 'tdStart') return tdStart(event)
  if (action === 'tdVote') return tdVote(event)
  if (action === 'tdTally') return tdTally(event)
  if (action === 'tdGetState') return tdGetState(event)
  if (action === 'transferHost') return transferHost(event)
  if (action === 'abdicateHost') return abdicateHost(event)

  throw new Error('未知操作')
}
