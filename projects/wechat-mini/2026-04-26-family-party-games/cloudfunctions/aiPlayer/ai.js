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
      } catch (e) {}
    }
  }
  if (!text.trim()) throw new Error('空文本')
  return text.trim()
}

async function invoke(model, modelName, messages) {
  try {
    const res = await model.streamText({ data: { model: modelName, messages } })
    return await collectStream(res)
  } catch (e1) {
    const res2 = await model.generateText({ model: modelName, messages })
    const t = pickText(res2) ||
      String((res2.choices && res2.choices[0] && res2.choices[0].message && res2.choices[0].message.content) || '').trim()
    if (!t) throw e1
    return t
  }
}

async function generateText(system, user) {
  if (!cloud.extend || !cloud.extend.AI) throw new Error('无 extend.AI')
  const messages = []
  if (system) messages.push({ role: 'system', content: String(system) })
  messages.push({ role: 'user', content: String(user) })
  let lastErr = null
  for (const att of ATTEMPTS) {
    for (const name of att.models) {
      try {
        const m = cloud.extend.AI.createModel(att.provider)
        return await invoke(m, name, messages)
      } catch (e) {
        lastErr = e
      }
    }
  }
  throw lastErr || new Error('AI 失败')
}

module.exports = { generateText }
