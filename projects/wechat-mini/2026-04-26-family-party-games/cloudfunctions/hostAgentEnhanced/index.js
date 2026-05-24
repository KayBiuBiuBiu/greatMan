/**
 * AI 主持增强：analyze / getHint / recap
 * 入参：{ action, data } 或扁平字段
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const { generateText } = require('./ai')
const { loadState, summarizeForPrompt, detectPhase } = require('./state')

const BUILD_ID = 'hostAgentEnhanced-v1'

const SYSTEM_ANALYZE =
  '你是聚会游戏分析助手。根据公开局面用 100 字内说明：当前阶段、关键局势、各方应注意什么。不要泄露未公开身份或私密词。'
const SYSTEM_HINT =
  '你是聚会游戏私人助手。根据公开信息给当前玩家一条策略建议（不超过 80 字），不要泄露未公开身份。'
const SYSTEM_RECAP =
  '你是聚会战报写手。根据游戏记录写一篇趣味短文：MVP、最搞笑、最坑、高光语录。Markdown 分段，300 字内。'

function ok(data) {
  return { ok: true, data: data || {} }
}

function fail(msg) {
  return { ok: false, errMsg: String(msg || 'error'), data: null }
}

function pickPayload(event) {
  const e = event || {}
  const action = String(e.action || '').trim()
  const data = e.data && typeof e.data === 'object' ? e.data : e
  return { action, data }
}

async function doAnalyze(data) {
  const gameKind = data.gameKind || 'undercover'
  const roomId = data.roomId
  const bundle = await loadState(gameKind, roomId)
  const summary = summarizeForPrompt(bundle)
  const phase = detectPhase(bundle)
  let analysis = summary
  try {
    const extra = JSON.stringify(data).slice(0, 1200)
    analysis = await generateText(
      SYSTEM_ANALYZE,
      '局面：\n' + summary + '\n\n客户端附加：\n' + extra
    )
  } catch (e) {
    console.warn('[hostAgentEnhanced] analyze AI fallback', e.message || e)
  }
  return ok({
    phase: phase,
    summary: summary,
    analysis: analysis,
    gameKind: gameKind,
    roomId: roomId
  })
}

async function doGetHint(data) {
  const gameKind = data.gameKind || 'undercover'
  const roomId = data.roomId
  const bundle = await loadState(gameKind, roomId)
  const summary = summarizeForPrompt(bundle)
  const hint = await generateText(
    SYSTEM_HINT,
    '玩家提示：' +
      String(data.playerHint || '') +
      '\n\n局面：\n' +
      summary +
      '\n\n请给出下一步建议。'
  )
  return ok({ hint: hint, summary: summary })
}

async function doRecap(data) {
  const logs = data.publicLog || data.logs || []
  const gameName = data.gameName || data.gameKind || '聚会'
  const prompt =
    '游戏：' + gameName + '\n记录：\n' + JSON.stringify(logs).slice(0, 4000)
  const recap = await generateText(SYSTEM_RECAP, prompt)
  return ok({ recap: recap, text: recap })
}

exports.main = async (event) => {
  try {
    const { action, data } = pickPayload(event)
    if (action === 'ping') {
      return ok({
        buildId: BUILD_ID,
        hasAi: !!(cloud.extend && cloud.extend.AI)
      })
    }
    if (action === 'analyze') {
      return await doAnalyze(data)
    }
    if (action === 'getHint') {
      return await doGetHint(data)
    }
    if (action === 'recap') {
      return await doRecap(data)
    }
    return fail('未知 action: ' + (action || '(空)'))
  } catch (e) {
    console.error('[hostAgentEnhanced]', e)
    return fail((e && e.message) || String(e))
  }
}
