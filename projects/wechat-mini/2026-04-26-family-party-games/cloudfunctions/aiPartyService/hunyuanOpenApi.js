/**
 * 混元 OpenAPI（OpenAI 兼容 /chat/completions）
 *
 * 等价于官方示例：
 *   client = OpenAI(api_key=..., base_url="https://api.hunyuan.cloud.tencent.com/v1/")
 *   client.chat.completions.create(model="hunyuan-lite", messages=[...])
 *
 * Key 仅放环境变量 HUNYUAN_API_KEY，勿写入代码库
 */
const https = require('https')

function postChatCompletions(baseUrl, apiKey, model, messages) {
  return new Promise((resolve, reject) => {
    const base = String(baseUrl || 'https://api.hunyuan.cloud.tencent.com/v1/').replace(/\/+$/, '')
    const body = JSON.stringify({ model: model, messages: messages })
    const u = new URL(base + '/chat/completions')
    const req = https.request(
      {
        hostname: u.hostname,
        port: u.port || 443,
        path: u.pathname + u.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer ' + apiKey,
          'Content-Length': Buffer.byteLength(body)
        }
      },
      (res) => {
        let raw = ''
        res.on('data', (c) => {
          raw += c
        })
        res.on('end', () => {
          let data
          try {
            data = JSON.parse(raw || '{}')
          } catch (e) {
            reject(new Error('混元 API 响应非 JSON: ' + String(raw).slice(0, 200)))
            return
          }
          if (res.statusCode < 200 || res.statusCode >= 300) {
            const msg =
              (data.error && data.error.message) || data.message || 'HTTP ' + res.statusCode
            reject(new Error(msg))
            return
          }
          resolve(data)
        })
      }
    )
    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

function buildMessages(prompt, system, provider) {
  const p = String(prompt || '').trim()
  const s = String(system || '').trim()
  if (provider === 'hunyuan') {
    return [{ role: 'user', content: s ? s + '\n\n' + p : p }]
  }
  const m = []
  if (s) m.push({ role: 'system', content: s })
  m.push({ role: 'user', content: p })
  return m
}

async function chatCompletions(opts) {
  const apiKey = String(opts.apiKey || '').trim()
  if (!apiKey) {
    throw new Error('未配置 HUNYUAN_API_KEY')
  }
  const model = String(opts.model || 'hunyuan-lite')
  const messages = opts.messages || buildMessages(opts.prompt, opts.system, opts.provider || 'hunyuan')
  const data = await postChatCompletions(
    opts.baseUrl || 'https://api.hunyuan.cloud.tencent.com/v1/',
    apiKey,
    model,
    messages
  )
  const text = String(
    (data.choices && data.choices[0] && data.choices[0].message && data.choices[0].message.content) ||
      ''
  ).trim()
  if (!text) {
    throw new Error('混元 OpenAPI 返回空文本')
  }
  return { text: text, usage: data.usage || null, modelUsed: 'openApi/' + model }
}

module.exports = { chatCompletions, buildMessages }
