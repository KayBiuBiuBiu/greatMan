/**
 * 聚会主持 / 玩家辅助 / 战报 / 推荐 Agent
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

let defaultAgentBotId = ''
try {
  defaultAgentBotId = String(require('./cloud-env.js').agentBotId || '').trim()
} catch (e) {
  defaultAgentBotId = ''
}

const { generateText } = require('./ai')
const { loadState, summarizeForPrompt } = require('./state')
const { runTick } = require('./tick')
const { handleAutoTick } = require('./autoTick')
const { getTemplate, fillPreset } = require('./templates')
const { textToVoice } = require('./voice')

const SYSTEM_ASSIST =
  '你是聚会游戏私人助手。根据公开信息给当前玩家一条策略建议（不超过80字），不要泄露未公开身份。'
const SYSTEM_RECAP =
  '你是聚会战报写手。根据游戏记录写一篇趣味短文：MVP、最搞笑、最坑、高光语录。Markdown 分段，300字内。'
const SYSTEM_RECOMMEND =
  '你是聚会策划助手。根据历史统计推荐下次玩的游戏与人数配置，语气轻松，150字内。'

function isTimerTrigger(event, context) {
  if (event && event.Type === 'Timer' && event.TriggerName === 'autoTick') {
    return true
  }
  if (event && event.TriggerName === 'autoTick') {
    return true
  }
  if (context && context.triggerName === 'autoTick') {
    return true
  }
  return false
}

exports.main = async (event, context) => {
  try {
    if (isTimerTrigger(event, context)) {
      return await handleAutoTick(event || {})
    }
    return await handleClientRequest(event || {})
  } catch (e) {
    console.error('[hostAgent]', e)
    return { errMsg: (e && e.message) || String(e) }
  }
}

async function handleClientRequest(event) {
  return run(event)
}

async function run(event) {
  const action = (event && event.action) || 'ping'
  if (action === 'ping') {
    return {
      ok: true,
      botId: process.env.AGENT_BOT_ID || defaultAgentBotId || '',
      hasAi: !!(cloud.extend && cloud.extend.AI)
    }
  }
  if (action === 'tick') {
    const gameKind = event.gameKind || 'drink'
    const roomId = event.roomId
    const auto = event.autoExecute !== false
    const tick = await runTick(gameKind, roomId)
    let narrate = tick.speakText || ''
    if (event.narrate && !narrate && tick.planned.length) {
      narrate = '已自动推进：' + tick.planned.map((p) => p.action).join('、')
    }
    if (!auto) {
      return Object.assign({ ok: true }, tick, { narrate })
    }
    return Object.assign({ ok: true }, tick, { speakText: narrate })
  }
  if (action === 'playerAssist') {
    return playerAssist(event)
  }
  if (action === 'hostNarrate') {
    return hostNarrate(event)
  }
  if (action === 'recap') {
    return gameRecap(event)
  }
  if (action === 'recommend') {
    return recommend(event)
  }
  if (action === 'chat') {
    const text = await generateText(
      String(event.system || '你是聚会副主持。'),
      String(event.prompt || '')
    )
    return { text }
  }
  return { errMsg: '未知 action ' + action }
}

async function playerAssist(event) {
  const gameKind = event.gameKind
  const roomId = event.roomId
  const bundle = await loadState(gameKind, roomId)
  const summary = summarizeForPrompt(bundle)
  const extra = String(event.playerHint || '')
  const prompt =
    '当前玩家视角提示：' +
    extra +
    '\n\n局面：\n' +
    summary +
    '\n\n请给出下一步建议。'
  const text = await generateText(SYSTEM_ASSIST, prompt)
  return { text, summary }
}

async function hostNarrate(event) {
  const gameKind = event.gameKind
  const roomId = event.roomId
  const scene = event.scene || 'midgame'
  const customVars = event.customVars || {}
  const bundle = await loadState(gameKind, roomId)
  const template = getTemplate(gameKind, scene)
  const preset = fillPreset(template.preset, customVars)
  const summary = summarizeForPrompt(bundle)
  const prompt = preset
    ? '场景：' + preset + '\n\n局面：\n' + summary + '\n\n请播报一句。'
    : '请根据局面播报一句：\n' + summary
  const text = await generateText(template.system, prompt)
  const voice = await textToVoice(text, {
    speed: event.voiceSpeed,
    voiceType: event.voiceType
  })
  return {
    text,
    speakText: text,
    scene,
    voiceUrl: voice.voiceUrl,
    voiceDuration: voice.duration,
    useClientTTS: voice.useClientTTS
  }
}

async function gameRecap(event) {
  const logs = event.publicLog || event.logs || []
  const gameName = event.gameName || event.gameKind || '聚会'
  const prompt =
    '游戏：' +
    gameName +
    '\n记录：\n' +
    JSON.stringify(logs).slice(0, 4000)
  const text = await generateText(SYSTEM_RECAP, prompt)
  return { text, article: text }
}

async function recommend(event) {
  const stats = event.stats || event.history || {}
  const prompt = '历史统计：\n' + JSON.stringify(stats).slice(0, 2000)
  const text = await generateText(SYSTEM_RECOMMEND, prompt)
  return { text }
}
