/**
 * 互动功能开关（改 false 即从首页与入口关闭）
 */
const DRAW_GUESS_ENABLED = false

/** 身份推理（秘密身份推理聚会版） */
const WEREWOLF_ENABLED = true

/** 身份推理：允许组长添加模拟玩家（少人测试用） */
const WEREWOLF_MOCK_PLAYER_ENABLED = true

/** 身份推理：AI 全自动主持（werewolfAIService） */
const WEREWOLF_AI_MODE_ENABLED = true

/** AI迷雾推理局 */
const MYSTERY_REASON_ENABLED = true

/** 各玩法页 AI 按钮（出题/战报/副主持等） */
const AI_BUTTONS_ENABLED = false

/** 首页可点的游戏（其余卡片置灰「正在开发中」） */
const HOME_ENABLED_TITLES = new Set([
  '趣味抽签',
  '疯狂猜歌',
  '真心话大冒险',
  '谁是卧底',
  '海龟汤',
  '你比划我猜',
  '贴头猜词',
  '不要做挑战',
  '秘密身份推理（聚会版）',
  'AI迷雾推理局'
])

function isDrawGuessEnabled () {
  return !!DRAW_GUESS_ENABLED
}

function isWerewolfEnabled () {
  return !!WEREWOLF_ENABLED
}

function isHomeGameEnabled (title) {
  const t = String(title || '').trim()
  if (t === '秘密身份推理（聚会版）' && isWerewolfEnabled()) {
    return true
  }
  if (t === 'AI迷雾推理局' && isMysteryReasonEnabled()) {
    return true
  }
  return HOME_ENABLED_TITLES.has(t)
}

function isWerewolfMockEnabled () {
  return !!WEREWOLF_MOCK_PLAYER_ENABLED
}

function isWerewolfAIModeEnabled () {
  return !!WEREWOLF_AI_MODE_ENABLED
}

function isMysteryReasonEnabled () {
  return !!MYSTERY_REASON_ENABLED
}

function isAiButtonsEnabled () {
  return !!AI_BUTTONS_ENABLED
}

module.exports = {
  DRAW_GUESS_ENABLED,
  WEREWOLF_ENABLED,
  WEREWOLF_MOCK_PLAYER_ENABLED,
  WEREWOLF_AI_MODE_ENABLED,
  MYSTERY_REASON_ENABLED,
  AI_BUTTONS_ENABLED,
  isDrawGuessEnabled,
  isWerewolfEnabled,
  isHomeGameEnabled,
  isWerewolfMockEnabled,
  isWerewolfAIModeEnabled,
  isMysteryReasonEnabled,
  isAiButtonsEnabled,
  HOME_ENABLED_TITLES
}
