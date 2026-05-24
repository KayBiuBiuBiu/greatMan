/**
 * AI 文本：优先混元 OpenAPI（环境变量 HUNYUAN_API_KEY），否则 extend.AI generateText
 */
const cloud = require('wx-server-sdk')
const { chatCompletions } = require('./hunyuanOpenApi')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

let aiProvider = 'hunyuan-v3'
let aiModels = ['hy3-preview']
let hunyuanApiBase = 'https://api.hunyuan.cloud.tencent.com/v1/'
try {
  const cfg = require('./cloud-env.js')
  if (cfg.aiProvider) aiProvider = cfg.aiProvider
  if (cfg.aiModels && cfg.aiModels.length) aiModels = cfg.aiModels.slice()
  if (cfg.hunyuanApiBase) hunyuanApiBase = cfg.hunyuanApiBase
} catch (e) {
  /* defaults */
}

function getApiKey() {
  return String(process.env.HUNYUAN_API_KEY || '').trim()
}

function extractText(res) {
  const body = (res && res.data) || res
  const text = String(
    (body &&
      body.choices &&
      body.choices[0] &&
      body.choices[0].message &&
      body.choices[0].message.content) ||
      (res &&
        res.choices &&
        res.choices[0] &&
        res.choices[0].message &&
        res.choices[0].message.content) ||
      ''
  ).trim()
  if (!text) {
    throw new Error('generateText 返回空文本')
  }
  return { text, usage: (body && body.usage) || (res && res.usage) || null }
}

async function chatViaExtendAi(prompt, system) {
  if (!cloud.extend || !cloud.extend.AI || !cloud.extend.AI.createModel) {
    throw new Error('云函数未支持 extend.AI，请升级 wx-server-sdk 3.x 并重新部署')
  }

  let messages
  if (aiProvider === 'hunyuan' || aiProvider === 'hunyuan-v3' || aiProvider === 'hunyuan-exp') {
    messages = [{ role: 'user', content: system ? system + '\n\n' + prompt : prompt }]
  } else {
    messages = []
    if (system) messages.push({ role: 'system', content: system })
    messages.push({ role: 'user', content: prompt })
  }

  const model = cloud.extend.AI.createModel(aiProvider)
  let lastErr = null
  for (let i = 0; i < aiModels.length; i++) {
    const modelName = aiModels[i]
    try {
      const res = await model.generateText({
        model: modelName,
        messages: messages
      })
      const r = extractText(res)
      return {
        text: r.text,
        via: 'cloudFunction',
        modelUsed: aiProvider + '/' + modelName,
        usage: r.usage
      }
    } catch (e) {
      lastErr = e
      console.warn('[aiPartyService] extend.AI', aiProvider, modelName, e.message || e)
    }
  }
  throw lastErr || new Error('extend.AI 调用失败')
}

async function chatViaOpenApi(prompt, system) {
  const apiKey = getApiKey()
  let lastErr = null
  for (let i = 0; i < aiModels.length; i++) {
    const modelName = aiModels[i]
    try {
      const r = await chatCompletions({
        apiKey,
        baseUrl: process.env.HUNYUAN_API_BASE || hunyuanApiBase,
        model: modelName,
        prompt,
        system,
        provider: aiProvider
      })
      return {
        text: r.text,
        via: 'cloudFunction',
        modelUsed: r.modelUsed,
        usage: r.usage
      }
    } catch (e) {
      lastErr = e
      console.warn('[aiPartyService] OpenAPI', modelName, e.message || e)
    }
  }
  throw lastErr || new Error('混元 OpenAPI 调用失败')
}

async function chat(event) {
  const prompt = String((event && event.prompt) || '').trim()
  const system = String((event && event.system) || '').trim()
  if (!prompt) throw new Error('缺少 prompt')

  if (getApiKey()) {
    try {
      return await chatViaOpenApi(prompt, system)
    } catch (e1) {
      console.warn('[aiPartyService] OpenAPI 失败，尝试 extend.AI', e1.message || e1)
    }
  }

  return chatViaExtendAi(prompt, system)
}

exports.main = async function (event) {
  const action = (event && event.action) || 'chat'
  try {
    if (action === 'chat') return await chat(event)
    throw new Error('未知 action ' + action)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}
