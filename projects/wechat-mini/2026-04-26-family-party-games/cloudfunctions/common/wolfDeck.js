/**
 * 秘密身份推理 — 统一板子配置（werewolfService / werewolfAIService 共用）
 * 人数 = 房间内玩家总数（含组长），每人一张身份牌。
 */
const MAXN = [6, 8, 10, 12]
const MIN_PLAYERS = 6
const MAX_ROOM_PLAYERS = 12

/** 6: 狼×1 + 白狼王×1 + 预 + 巫 + 守 + 民×1 */
const DECK = {
  6: ['werewolf', 'white_wolf', 'seer', 'witch', 'guard', 'villager'],
  8: ['werewolf', 'white_wolf', 'seer', 'witch', 'guard', 'hunter', 'villager', 'villager'],
  10: [
    'werewolf',
    'werewolf',
    'white_wolf',
    'seer',
    'witch',
    'guard',
    'hunter',
    'villager',
    'villager',
    'villager'
  ],
  12: [
    'werewolf',
    'werewolf',
    'werewolf',
    'white_wolf',
    'seer',
    'witch',
    'guard',
    'hunter',
    'villager',
    'villager',
    'villager',
    'villager'
  ]
}

function isWolfRole(role) {
  return role === 'werewolf' || role === 'white_wolf'
}

function isGodRole(role) {
  return role === 'seer' || role === 'witch' || role === 'hunter' || role === 'guard'
}

function membersOf(room) {
  return (room.members || []).filter((m) => m && m.openId)
}

function roomJoinCap(room) {
  const fixed = room && (room.maxPlayers | 0)
  return fixed > 0 ? fixed : MAX_ROOM_PLAYERS
}

function roomSeatCap(room) {
  return roomJoinCap(room)
}

/** 取不小于当前人数的最小板子规模（6/8/10/12） */
function pickBoardSize(playerCount) {
  const n = playerCount | 0
  for (let i = 0; i < MAXN.length; i += 1) {
    if (MAXN[i] >= n) {
      return MAXN[i]
    }
  }
  return MAXN[MAXN.length - 1]
}

/** 按实际进组人数截取身份牌（至少 6 人） */
function rolesForPlayerCount(playerCount) {
  const n = playerCount | 0
  if (n < MIN_PLAYERS) {
    return null
  }
  const board = pickBoardSize(n)
  const deck = DECK[board]
  if (!deck || deck.length < n) {
    return null
  }
  return deck.slice(0, n)
}

module.exports = {
  MAXN,
  MIN_PLAYERS,
  MAX_ROOM_PLAYERS,
  DECK,
  isWolfRole,
  isGodRole,
  membersOf,
  roomJoinCap,
  roomSeatCap,
  pickBoardSize,
  rolesForPlayerCount
}
