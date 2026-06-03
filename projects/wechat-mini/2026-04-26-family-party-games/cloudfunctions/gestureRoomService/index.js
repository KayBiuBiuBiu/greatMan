const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const ROOMS = 'gesture_rooms'
const PLAYERS = 'gesture_players'
const GAME_STATE = 'gesture_gameState'
const ROOM_TTL = 1000 * 60 * 60 * 4

const WORDS_DB = [
  { id: 'w1', w: '大象', c: 'all' },
  { id: 'w2', w: '直升机', c: 'all' },
  { id: 'w3', w: '弹吉他', c: 'all' },
  { id: 'w4', w: '洗衣机', c: 'all' },
  { id: 'w5', w: '游泳', c: 'all' },
  { id: 'w6', w: '骑马', c: 'all' },
  { id: 'w7', w: '打喷嚏', c: 'all' },
  { id: 'w8', w: '刷牙', c: 'all' },
  { id: 'w9', w: '开车', c: 'all' },
  { id: 'w10', w: '跳舞', c: 'all' },
  { id: 'w11', w: '下棋', c: 'all' },
  { id: 'w12', w: '煮饭', c: 'all' },
  { id: 'w13', w: '放风筝', c: 'all' },
  { id: 'w14', w: '踢足球', c: 'all' },
  { id: 'w15', w: '投篮', c: 'all' },
  { id: 'w16', w: '滑冰', c: 'all' },
  { id: 'w17', w: '爬山', c: 'all' },
  { id: 'w18', w: '看电影', c: 'all' },
  { id: 'w19', w: '弹钢琴', c: 'all' },
  { id: 'w20', w: '做瑜伽', c: 'all' }
]

function getOpenId() {
  return cloud.getWXContext().OPENID
}

function normalizeNickName(nick) {
  return String(nick || '参与者').slice(0, 12).trim() || '参与者'
}

function normalizeRoomCode(code) {
  return String(code || '').replace(/\D/g, '').slice(0, 6)
}

function normGuess(s) {
  return String(s || '')
    .trim()
    .toLowerCase()
    .replace(/\s/g, '')
}

function genRoomCode() {
  return String(Math.floor(Math.random() * 999999)).padStart(6, '0')
}

function performerForRound(players, round, totalRounds) {
  if (!players || players.length === 0) return null
  const idx = (round - 1) % players.length
  return players[idx].openId
}

function buildPubState(room, players, gameState) {
  return {
    roomId: room._id,
    roomCode: room.roomCode,
    status: room.status,
    hostOpenId: room.hostOpenId,
    totalRounds: room.totalRounds,
    roundDuration: room.roundDuration,
    phase: gameState.phase || 'waiting',
    currentRound: gameState.currentRound || 0,
    roundStartTime: gameState.roundStartTime || 0,
    performerOpenId: gameState.performerOpenId || '',
    performerNickName: gameState.performerNickName || '',
    publicPlayers: gameState.publicPlayers || [],
    roundHits: gameState.roundHits || [],
    revealedWord: gameState.revealedWord || '',
    publicLog: gameState.publicLog || [],
    wordCategory: room.wordCategory || 'all',
    syncAt: Date.now()
  }
}

async function getPlayerList(rid) {
  const res = await db.collection(PLAYERS)
    .where({ roomId: rid })
    .get()
  return res.data || []
}

async function getRoom(rid) {
  const res = await db.collection(ROOMS).doc(rid).get()
  return res.data || null
}

async function getGameState(rid) {
  const res = await db.collection(GAME_STATE).doc(rid).get()
  return res.data || null
}

async function fetchAiWord(category) {
  try {
    const res = await cloud.callFunction({
      name: 'aiPartyService',
      data: {
        action: 'chat',
        system: '你是「你比划我猜」游戏的出题助手。只返回 JSON 格式的词语，格式：{"word":"词语"}。词语必须是名词、动词或短语（2-8个字），适合用肢体表演。',
        prompt: `请生成 1 个词语。分类：${category || 'all'}。只返回 JSON。`
      }
    })
    const text = res.result && res.result.text
    if (text) {
      try {
        const match = text.match(/"word"\s*:\s*"([^"]+)"/)
        if (match && match[1]) {
          return { id: 'ai_' + Date.now(), w: match[1].slice(0, 8) }
        }
      } catch (e) {
        console.error('Parse AI word failed:', e)
      }
    }
  } catch (e) {
    console.error('AI call failed:', e)
  }
  return fallbackWord(category)
}

function fallbackWord(category) {
  const words = WORDS_DB.filter(w => !category || w.c === category || w.c === 'all')
  if (words.length === 0) return WORDS_DB[0]
  return words[Math.floor(Math.random() * words.length)]
}

async function createRoom(event) {
  const openId = getOpenId()
  const nick = normalizeNickName(event.nickName)
  const roomCode = genRoomCode()

  const room = {
    roomCode,
    hostOpenId: openId,
    status: 'waiting',
    totalRounds: event.totalRounds || 6,
    roundDuration: event.roundDuration || 60,
    wordCategory: event.wordCategory || 'all',
    usedWordIds: [],
    currentWordId: '',
    currentWordText: '',
    createdAt: Date.now(),
    updatedAt: Date.now()
  }

  const addRes = await db.collection(ROOMS).add({ data: room })
  const rid = addRes.id || addRes._id

  const player = {
    roomId: rid,
    openId,
    nickName: nick,
    avatarUrl: event.avatarUrl || '',
    isHost: true,
    score: 0,
    joinedAt: Date.now()
  }
  await db.collection(PLAYERS).add({ data: player })

  const gameState = {
    _id: rid,
    roomId: rid,
    phase: 'waiting',
    currentRound: 0,
    roundStartTime: 0,
    performerOpenId: '',
    performerNickName: '',
    publicPlayers: [],
    roundHits: [],
    revealedWord: '',
    publicLog: [],
    updatedAt: Date.now()
  }
  await db.collection(GAME_STATE).add({ data: gameState })

  return {
    roomId: rid,
    roomCode,
    myOpenId: openId,
    ok: 1
  }
}

async function joinRoom(event) {
  const openId = getOpenId()
  const roomCode = normalizeRoomCode(event.roomCode)
  const nick = normalizeNickName(event.nickName)

  const res = await db.collection(ROOMS)
    .where({ roomCode, status: _.neq('finished') })
    .limit(1)
    .get()

  if (!res.data || res.data.length === 0) {
    throw new Error('房间不存在或已过期')
  }

  const room = res.data[0]
  const rid = room._id
  const players = await getPlayerList(rid)

  if (players.length >= 20) {
    throw new Error('房间已满')
  }

  const existing = players.find(p => p.openId === openId)
  if (existing) {
    await db.collection(PLAYERS).doc(existing._id).update({
      data: { nickName: nick, avatarUrl: event.avatarUrl || '', updatedAt: Date.now() }
    })
  } else {
    const player = {
      roomId: rid,
      openId,
      nickName: nick,
      avatarUrl: event.avatarUrl || '',
      isHost: false,
      score: 0,
      joinedAt: Date.now()
    }
    await db.collection(PLAYERS).add({ data: player })
  }

  return {
    roomId: rid,
    roomCode: room.roomCode,
    playerCount: players.length + (existing ? 0 : 1),
    myOpenId: openId,
    ok: 1
  }
}

async function setConfig(event) {
  const openId = getOpenId()
  const { roomId, totalRounds, roundDuration, wordCategory } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId) throw new Error('仅房主可设置')
  if (room.status !== 'waiting') throw new Error('已开始，无法修改')

  await db.collection(ROOMS).doc(roomId).update({
    data: {
      totalRounds: totalRounds || room.totalRounds,
      roundDuration: roundDuration || room.roundDuration,
      wordCategory: wordCategory || room.wordCategory,
      updatedAt: Date.now()
    }
  })

  return { ok: 1 }
}

async function startGame(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId && !event._test) throw new Error('仅房主可开始')
  if (room.status !== 'waiting') throw new Error('已开始')

  const players = await getPlayerList(roomId)
  if (players.length < 2) throw new Error('至少需要 2 人')

  const word = event._test
    ? { id: 'test', w: '苹果' }
    : await fetchAiWord(room.wordCategory)

  const performerId = performerForRound(players, 1, room.totalRounds)
  const performer = players.find(p => p.openId === performerId)

  await db.collection(ROOMS).doc(roomId).update({
    data: {
      status: 'playing',
      currentWordId: word.id,
      currentWordText: word.w,
      usedWordIds: [word.id],
      updatedAt: Date.now()
    }
  })

  const publicPlayers = players.map(p => ({
    openId: p.openId,
    nickName: p.nickName,
    avatarUrl: p.avatarUrl,
    isHost: p.isHost,
    score: p.score
  }))

  const gameState = {
    _id: roomId,
    phase: 'performing',
    currentRound: 1,
    roundStartTime: Date.now(),
    performerOpenId: performerId,
    performerNickName: performer.nickName,
    publicPlayers,
    roundHits: [],
    revealedWord: '',
    publicLog: [`第1轮。表演者：${performer.nickName}。大家猜词。`],
    updatedAt: Date.now()
  }
  await db.collection(GAME_STATE).doc(roomId).set({ data: gameState })

  return {
    ok: 1,
    performerOpenId: performerId,
    currentWord: word.w
  }
}

async function submitGuess(event) {
  const openId = getOpenId()
  const { roomId, answer } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')

  const gameState = await getGameState(roomId)
  if (!gameState || gameState.phase !== 'performing') throw new Error('游戏未进行')

  const nowTime = Date.now()
  const roundStart = gameState.roundStartTime || 0
  const duration = (room.roundDuration || 60) * 1000
  if (nowTime > roundStart + duration) {
    throw new Error('时间已到')
  }

  if (gameState.performerOpenId === openId) {
    throw new Error('表演者不能猜词')
  }

  const already = gameState.roundHits.find(h => h.openId === openId)
  if (already) {
    throw new Error('本轮已经猜过了')
  }

  const word = room.currentWordText
  if (!word) throw new Error('题目异常')

  if (normGuess(answer) !== normGuess(word)) {
    return { wrong: 1, ok: 0 }
  }

  const players = await getPlayerList(roomId)
  const guessPlayer = players.find(p => p.openId === openId)
  if (!guessPlayer) throw new Error('玩家不存在')

  const nHits = gameState.roundHits.length
  const points = nHits === 0 ? 3 : 1

  const newRoundHits = [
    ...gameState.roundHits,
    {
      openId,
      nickName: guessPlayer.nickName,
      order: nHits + 1,
      points
    }
  ]

  await db.collection(PLAYERS).doc(guessPlayer._id).update({
    data: { score: guessPlayer.score + points, updatedAt: Date.now() }
  })

  const publicPlayers = players.map(p => {
    const newScore = p.openId === openId ? p.score + points : p.score
    return {
      openId: p.openId,
      nickName: p.nickName,
      avatarUrl: p.avatarUrl,
      isHost: p.isHost,
      score: newScore
    }
  }).sort((a, b) => b.score - a.score)

  const log = `${guessPlayer.nickName} 猜对了！`
  const newLog = [...gameState.publicLog, log]

  await db.collection(GAME_STATE).doc(roomId).update({
    data: {
      roundHits: newRoundHits,
      publicPlayers,
      publicLog: newLog,
      updatedAt: Date.now()
    }
  })

  return {
    ok: 1,
    points,
    order: nHits + 1,
    newScore: guessPlayer.score + points
  }
}

async function skipWord(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId) throw new Error('仅房主可操作')

  const gameState = await getGameState(roomId)
  if (!gameState || gameState.phase !== 'performing') throw new Error('游戏未进行')

  const word = await fetchAiWord(room.wordCategory)

  await db.collection(ROOMS).doc(roomId).update({
    data: {
      currentWordId: word.id,
      currentWordText: word.w,
      usedWordIds: [...(room.usedWordIds || []), word.id],
      updatedAt: Date.now()
    }
  })

  const newLog = [...gameState.publicLog, '房主已换词。']
  await db.collection(GAME_STATE).doc(roomId).update({
    data: {
      roundStartTime: Date.now(),
      roundHits: [],
      revealedWord: '',
      publicLog: newLog,
      updatedAt: Date.now()
    }
  })

  return { ok: 1 }
}

async function reveal(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId) throw new Error('仅房主可揭晓')

  const gameState = await getGameState(roomId)
  if (!gameState || gameState.phase !== 'performing') throw new Error('游戏未进行')

  const log = gameState.roundHits.length > 0
    ? `本轮答案：${room.currentWordText}。猜中：${gameState.roundHits.map(h => h.nickName).join('、')}。`
    : `本轮答案：${room.currentWordText}。无人猜中。`

  await db.collection(GAME_STATE).doc(roomId).update({
    data: {
      phase: 'revealed',
      revealedWord: room.currentWordText,
      publicLog: [...gameState.publicLog, log],
      updatedAt: Date.now()
    }
  })

  return { ok: 1 }
}

async function nextRound(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId) throw new Error('仅房主可操作')

  const gameState = await getGameState(roomId)
  if (!gameState) throw new Error('游戏状态异常')

  const nextRound = (gameState.currentRound || 0) + 1
  const isEnd = nextRound > room.totalRounds

  if (isEnd) {
    await db.collection(ROOMS).doc(roomId).update({
      data: { status: 'finished', updatedAt: Date.now() }
    })
    await db.collection(GAME_STATE).doc(roomId).update({
      data: { phase: 'finished', updatedAt: Date.now() }
    })
    return { ok: 1, finished: true }
  }

  const players = await getPlayerList(roomId)
  const word = await fetchAiWord(room.wordCategory)
  const performerId = performerForRound(players, nextRound, room.totalRounds)
  const performer = players.find(p => p.openId === performerId)

  await db.collection(ROOMS).doc(roomId).update({
    data: {
      currentWordId: word.id,
      currentWordText: word.w,
      usedWordIds: [...(room.usedWordIds || []), word.id],
      updatedAt: Date.now()
    }
  })

  const publicPlayers = players.map(p => ({
    openId: p.openId,
    nickName: p.nickName,
    avatarUrl: p.avatarUrl,
    isHost: p.isHost,
    score: p.score
  })).sort((a, b) => b.score - a.score)

  await db.collection(GAME_STATE).doc(roomId).update({
    data: {
      phase: 'performing',
      currentRound: nextRound,
      roundStartTime: Date.now(),
      performerOpenId: performerId,
      performerNickName: performer.nickName,
      publicPlayers,
      roundHits: [],
      revealedWord: '',
      publicLog: [...gameState.publicLog, `第${nextRound}轮。表演者：${performer.nickName}。`],
      updatedAt: Date.now()
    }
  })

  return { ok: 1, nextRound, performerOpenId: performerId }
}

async function endGame(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) throw new Error('房间不存在')
  if (room.hostOpenId !== openId) throw new Error('仅房主可操作')

  await db.collection(ROOMS).doc(roomId).update({
    data: { status: 'finished', updatedAt: Date.now() }
  })
  await db.collection(GAME_STATE).doc(roomId).update({
    data: { phase: 'finished', updatedAt: Date.now() }
  })

  return { ok: 1 }
}

async function getView(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  const gameState = await getGameState(roomId)
  const players = await getPlayerList(roomId)

  const isHost = room && room.hostOpenId === openId
  const isPerformer = gameState && gameState.performerOpenId === openId
  const me = players.find(p => p.openId === openId)

  let performerWord = ''
  if (isPerformer && room && room.currentWordText) {
    performerWord = room.currentWordText
  }

  const publicPlayers = (players || [])
    .map(p => ({
      openId: p.openId,
      nickName: p.nickName,
      avatarUrl: p.avatarUrl,
      isHost: p.isHost,
      score: p.score
    }))
    .sort((a, b) => b.score - a.score)

  return {
    myOpenId: openId,
    isHost,
    isPerformer,
    myScore: me ? me.score : 0,
    performerWord,
    publicPlayers,
    phase: gameState ? gameState.phase : 'waiting',
    currentRound: gameState ? gameState.currentRound : 0,
    roundStartTime: gameState ? gameState.roundStartTime : 0,
    totalRounds: room ? room.totalRounds : 0,
    roomStatus: room ? room.status : 'closed'
  }
}

async function syncState(event) {
  const openId = getOpenId()
  const { roomId } = event

  const room = await getRoom(roomId)
  if (!room) return { errMsg: '房间不存在', ok: 0 }

  const gameState = await getGameState(roomId)
  const players = await getPlayerList(roomId)
  const inRoom = players.some(p => p.openId === openId)

  const state = buildPubState(room, players, gameState || {})
  const view = await getView(event)

  return {
    ok: 1,
    state,
    view,
    inRoom
  }
}

exports.main = async (event, context) => {
  const action = event.action
  try {
    switch (action) {
      case 'create':
        return await createRoom(event)
      case 'join':
        return await joinRoom(event)
      case 'setConfig':
        return await setConfig(event)
      case 'startGame':
        return await startGame(event)
      case 'submitGuess':
        return await submitGuess(event)
      case 'skipWord':
        return await skipWord(event)
      case 'reveal':
        return await reveal(event)
      case 'nextRound':
        return await nextRound(event)
      case 'endGame':
        return await endGame(event)
      case 'getView':
        return await getView(event)
      case 'syncState':
        return await syncState(event)
      default:
        throw new Error('未知操作：' + action)
    }
  } catch (e) {
    return { errMsg: e.message || String(e), ok: 0 }
  }
}
