/**
 * AI 文本：优先混元 OpenAPI（环境变量 HUNYUAN_API_KEY），否则 extend.AI generateText
 */
const cloud = require('wx-server-sdk')
const { chatCompletions } = require('./hunyuanOpenApi')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

let aiProvider = 'hunyuan-v3'
let aiModels = ['hy3-preview']
/** OpenAPI（HUNYUAN_API_KEY）用 hunyuan-lite；extend.AI 用 hy3-preview */
let openApiModels = ['hunyuan-lite']
let hunyuanApiBase = 'https://api.hunyuan.cloud.tencent.com/v1/'
try {
  const cfg = require('./cloud-env.js')
  if (cfg.aiProvider) aiProvider = cfg.aiProvider
  if (cfg.aiModels && cfg.aiModels.length) aiModels = cfg.aiModels.slice()
  if (cfg.openApiModels && cfg.openApiModels.length) openApiModels = cfg.openApiModels.slice()
  if (cfg.hunyuanApiBase) hunyuanApiBase = cfg.hunyuanApiBase
} catch (e) {
  /* defaults */
}

let deploySecrets = null
try {
  deploySecrets = require('./deploySecrets')
} catch (e) {
  deploySecrets = null
}

function getApiKey() {
  const fromEnv = String(process.env.HUNYUAN_API_KEY || '').trim()
  if (fromEnv) return fromEnv
  if (deploySecrets && deploySecrets.HUNYUAN_API_KEY) {
    return String(deploySecrets.HUNYUAN_API_KEY).trim()
  }
  return ''
}

function getApiBase() {
  const fromEnv = String(process.env.HUNYUAN_API_BASE || '').trim()
  if (fromEnv) return fromEnv
  if (deploySecrets && deploySecrets.HUNYUAN_API_BASE) {
    return String(deploySecrets.HUNYUAN_API_BASE).trim()
  }
  return hunyuanApiBase
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
  for (let i = 0; i < openApiModels.length; i++) {
    const modelName = openApiModels[i]
    try {
      const r = await chatCompletions({
        apiKey,
        baseUrl: getApiBase(),
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

  const apiKey = getApiKey()
  if (apiKey) {
    try {
      return await chatViaOpenApi(prompt, system)
    } catch (e1) {
      const msg = String((e1 && e1.message) || e1)
      console.warn('[aiPartyService] OpenAPI 失败', msg)
      throw new Error('混元 API 调用失败：' + msg)
    }
  }

  try {
    return await chatViaExtendAi(prompt, system)
  } catch (e2) {
    const msg = String((e2 && e2.message) || e2)
    if (/extend\.AI/.test(msg)) {
      throw new Error(
        '未配置 HUNYUAN_API_KEY。请运行 node scripts/deploy-ai-party-service.js 或在云开发控制台为 aiPartyService 添加环境变量后重新部署'
      )
    }
    throw e2
  }
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
