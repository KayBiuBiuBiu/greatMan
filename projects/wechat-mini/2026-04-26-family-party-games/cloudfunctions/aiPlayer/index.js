/**
 * AI 虚拟玩家：根据公开局面生成发言或投票建议
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const { generateText } = require('./ai')

const SYSTEM_SPEAK =
  '你是聚会游戏中的AI玩家。根据词语和阶段生成一句发言（15-40字），像真人，不要直接暴露身份。'
const SYSTEM_VOTE =
  '你是聚会游戏中的AI玩家。根据发言记录，输出要投票的玩家序号（仅一个数字）及一句理由（20字内）。格式：票号|理由'

exports.main = async (event) => {
  try {
    const action = (event && event.action) || 'speak'
    const gameKind = event.gameKind || 'undercover'
    const context = String(event.context || event.publicLog || '')
    const word = String(event.word || event.hint || '')
    const difficulty = String(event.difficulty || 'medium')

    if (action === 'speak') {
      const prompt =
        `难度:${difficulty}\n词/提示:${word}\n局面:\n${context}\n请发言：`
      const text = await generateText(SYSTEM_SPEAK, prompt)
      return { text, action: 'speak' }
    }
    if (action === 'vote') {
      const prompt = `局面:\n${context}\n可选玩家列表见记录。请投票：`
      const raw = await generateText(SYSTEM_VOTE, prompt)
      const parts = String(raw).split('|')
      return {
        voteIndex: parseInt(parts[0], 10) || 0,
        reason: (parts[1] || raw).trim(),
        text: raw,
        action: 'vote'
      }
    }
    return { errMsg: '未知 action' }
  } catch (e) {
    console.error('[aiPlayer]', e)
    return { errMsg: (e && e.message) || String(e) }
  }
}
