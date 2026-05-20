/**
 * 文本生成：优先 cloud.extend.AI，失败则 cloud.callFunction(aiPartyService)
 */
const cloud = require('wx-server-sdk')

const ATTEMPTS = [
  { provider: 'hunyuan', models: ['hunyuan-lite'] },
  { provider: 'cloudbase', models: ['hunyuan-lite', 'hy3-preview'] }
]

function pickText(data) {
  if (!data) return ''
  if (data.content) return String(data.content)
  const c = data.choices && data.choices[0]
  if (c && c.message && c.message.content) return String(c.message.content)
  if (c && c.delta && c.delta.content) return String(c.delta.content)
  return ''
}

async function collectStream(res) {
  let text = ''
  if (res.textStream) {
    for await (const s of res.textStream) text += s || ''
  }
  if (!text.trim() && res.eventStream) {
    for await (const ev of res.eventStream) {
      if (ev.data === '[DONE]') break
      try {
        text += pickText(JSON.parse(ev.data))
      } catch (e) {
        /* skip */
      }
    }
  }
  if (!text.trim()) throw new Error('stream 空文本')
  return text.trim()
}

async function generateTextFromModel(model, modelName, messages) {
  const res = await model.generateText({
    data: { model: modelName, messages }
  })
  const body = (res && res.data) || res
  const t =
    pickText(body) ||
    String(
      (body.choices && body.choices[0] && body.choices[0].message && body.choices[0].message.content) ||
        ''
    ).trim()
  if (!t) throw new Error('generateText 空文本')
  return t
}

async function invokeExtend(model, modelName, messages) {
  try {
    const res = await model.streamText({ data: { model: modelName, messages } })
    return await collectStream(res)
  } catch (e1) {
    if (typeof model.generateText !== 'function') throw e1
    return generateTextFromModel(model, modelName, messages)
  }
}

function buildMessages(system, user, provider) {
  const u = String(user || '').trim()
  const s = String(system || '').trim()
  if (provider === 'hunyuan') {
    return [{ role: 'user', content: s ? s + '\n\n' + u : u }]
  }
  const messages = []
  if (s) messages.push({ role: 'system', content: s })
  messages.push({ role: 'user', content: u })
  return messages
}

async function generateTextViaExtend(system, user) {
  if (!cloud.extend || !cloud.extend.AI) {
    throw new Error('无 extend.AI')
  }
  let lastErr = null
  for (let a = 0; a < ATTEMPTS.length; a++) {
    const att = ATTEMPTS[a]
    for (let m = 0; m < att.models.length; m++) {
      const name = att.models[m]
      try {
        const model = cloud.extend.AI.createModel(att.provider)
        const messages = buildMessages(system, user, att.provider)
        const text = await invokeExtend(model, name, messages)
        console.log('[hostAgent ai] extend.AI OK', att.provider + '/' + name)
        return text
      } catch (e) {
        lastErr = e
      }
    }
  }
  throw lastErr || new Error('extend.AI 全部失败')
}

async function callAiPartyService(system, user) {
  const res = await cloud.callFunction({
    name: 'aiPartyService',
    data: {
      action: 'chat',
      prompt: String(user || ''),
      system: String(system || '')
    }
  })
  const r = (res && res.result) || {}
  if (r.errMsg) {
    throw new Error(String(r.errMsg))
  }
  const text = String(r.text || '').trim()
  if (!text) {
    throw new Error('aiPartyService 返回空文本')
  }
  console.log('[hostAgent ai] aiPartyService OK', r.modelUsed || '')
  return text
}

async function generateTextMain(system, user) {
  let lastErr = null

  if (cloud.extend && cloud.extend.AI) {
    try {
      return await generateTextViaExtend(system, user)
    } catch (e) {
      lastErr = e
      console.warn('[hostAgent ai] extend.AI 失败，尝试 aiPartyService:', e.message || e)
    }
  }

  try {
    return await callAiPartyService(system, user)
  } catch (e2) {
    console.error('[hostAgent ai] aiPartyService 失败:', e2.message || e2)
    throw lastErr || e2
  }
}

module.exports = { generateText: generateTextMain }
