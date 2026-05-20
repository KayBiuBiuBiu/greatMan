/**
 * streamText / generateText 聚合与错误解析
 */

function unwrapPayload(res) {
  if (!res || typeof res !== 'object') {
    return res
  }
  if (res.data && typeof res.data === 'object' && (res.data.choices || res.data.error || res.data.ret)) {
    return res.data
  }
  return res
}

/** 从接口 JSON 中提取业务错误（避免误报「空文本」） */
function detectApiError(data) {
  if (!data || typeof data !== 'object') {
    return ''
  }
  if (data.error && typeof data.error === 'object') {
    const m = data.error.message || data.error.errMsg || data.error.code
    if (m) {
      return String(m)
    }
  }
  if (data.error && typeof data.error === 'string') {
    return data.error
  }
  if (data.errMsg) {
    return String(data.errMsg)
  }
  if (data.message && !data.choices && !data.content) {
    return String(data.message)
  }
  const ret = data.ret
  if (ret) {
    const s = Array.isArray(ret) ? ret.join('; ') : String(ret)
    if (s && !/SUCCESS/i.test(s)) {
      return s
    }
  }
  if (data.code && data.code !== 0 && data.code !== '0') {
    return 'code=' + data.code + (data.msg ? ' ' + data.msg : '')
  }
  return ''
}

function extractTextFromObject(data) {
  if (!data || typeof data !== 'object') {
    return ''
  }
  const err = detectApiError(data)
  if (err) {
    const e = new Error(err)
    e.isApiError = true
    throw e
  }
  let parts = []
  if (data.type === 'TEXT_MESSAGE_CONTENT' && data.delta) {
    parts.push(String(data.delta))
  }
  if (data.content) {
    parts.push(String(data.content))
  }
  if (data.text) {
    parts.push(String(data.text))
  }
  const choice = data.choices && data.choices[0]
  if (choice) {
    if (choice.message && choice.message.content) {
      parts.push(String(choice.message.content))
    }
    if (choice.delta && choice.delta.content) {
      parts.push(String(choice.delta.content))
    }
    if (choice.text) {
      parts.push(String(choice.text))
    }
  }
  if (typeof data.delta === 'string') {
    parts.push(data.delta)
  }
  if (typeof data.result === 'string') {
    parts.push(data.result)
  }
  return parts.join('')
}

function extractTextFromGenerateRes(res) {
  const body = unwrapPayload(res)
  if (!body) {
    return ''
  }
  if (typeof body === 'string') {
    return body.trim()
  }
  const fromObj = extractTextFromObject(body)
  if (fromObj) {
    return fromObj.trim()
  }
  return String(
    (body.choices &&
      body.choices[0] &&
      body.choices[0].message &&
      body.choices[0].message.content) ||
      ''
  ).trim()
}

async function collectStreamResult(res, modelUsed) {
  let text = ''
  let usage = null
  const rawSamples = []

  if (!res) {
    throw new Error('streamText 无返回')
  }

  if (res.textStream) {
    try {
      for await (const str of res.textStream) {
        if (str) {
          text += str
        }
      }
    } catch (e) {
      if (e.isApiError) {
        throw e
      }
      rawSamples.push('textStream:' + (e.message || e))
    }
  }

  if (!text.trim() && res.eventStream) {
    try {
      for await (const event of res.eventStream) {
        if (!event || event.data == null) {
          continue
        }
        if (event.data === '[DONE]') {
          break
        }
        const raw = String(event.data)
        if (rawSamples.length < 3) {
          rawSamples.push(raw.slice(0, 200))
        }
        if (raw === '[DONE]') {
          break
        }
        try {
          const data = JSON.parse(raw)
          text += extractTextFromObject(data)
          if (data && data.usage) {
            usage = data.usage
          }
        } catch (e) {
          if (e.isApiError) {
            throw e
          }
          if (raw && raw[0] !== '{') {
            text += raw
          }
        }
      }
    } catch (e) {
      if (e.isApiError) {
        throw e
      }
      rawSamples.push('eventStream:' + (e.message || e))
    }
  }

  const out = String(text || '').trim()
  if (!out) {
    const err = new Error(
      'stream 空文本' + (rawSamples.length ? '；片段:' + rawSamples.join(' | ') : '')
    )
    err.modelUsed = modelUsed
    err.lastRaw = rawSamples.join('\n')
    throw err
  }
  return { text: out, usage: usage, modelUsed: modelUsed }
}

function streamTextOnce(chatModel, modelName, messages, wrapped) {
  return new Promise((resolve, reject) => {
    let viaCallback = ''
    const payload = { model: modelName, messages: messages }
    const opts = wrapped
      ? {
          data: payload,
          onText: (t) => {
            if (t) viaCallback += t
          },
          onFinish: (t) => {
            if (t) viaCallback += t
          }
        }
      : Object.assign({}, payload, {
          onText: (t) => {
            if (t) viaCallback += t
          },
          onFinish: (t) => {
            if (t) viaCallback += t
          }
        })
    chatModel
      .streamText(opts)
      .then((res) => {
        if (viaCallback.trim()) {
          resolve({
            text: viaCallback.trim(),
            usage: null,
            modelUsed: modelName
          })
          return
        }
        return collectStreamResult(res, modelName).then(resolve).catch(reject)
      })
      .catch(reject)
  })
}

/** 官方示例为扁平参数；部分环境仅 data 包装有效，两种都试 */
function streamTextCollect(chatModel, modelName, messages) {
  return streamTextOnce(chatModel, modelName, messages, false).catch(() =>
    streamTextOnce(chatModel, modelName, messages, true)
  )
}

function generateTextCollect(chatModel, modelName, messages) {
  function runFlat() {
    return chatModel.generateText({ model: modelName, messages: messages })
  }
  function runWrapped() {
    return chatModel.generateText({
      data: { model: modelName, messages: messages }
    })
  }
  return runFlat()
    .catch(() => runWrapped())
    .then((res) => {
      const text = extractTextFromGenerateRes(res)
      if (!text) {
        const err = new Error('generateText 空文本')
        try {
          err.lastRaw = JSON.stringify(unwrapPayload(res)).slice(0, 300)
        } catch (e) {
          err.lastRaw = ''
        }
        throw err
      }
      return {
        text: text,
        usage: (unwrapPayload(res) && unwrapPayload(res).usage) || null,
        modelUsed: modelName
      }
    })
}

function invokeModelCollect(chatModel, provider, modelName, messages) {
  return streamTextCollect(chatModel, modelName, messages).catch((streamErr) => {
    if (streamErr.isApiError) {
      throw streamErr
    }
    if (typeof chatModel.generateText !== 'function') {
      throw streamErr
    }
    return generateTextCollect(chatModel, modelName, messages).catch((genErr) => {
      const parts = [streamErr && streamErr.message, genErr && genErr.message].filter(Boolean)
      const e = new Error(parts.join(' | '))
      e.provider = provider
      e.modelUsed = modelName
      e.lastRaw = (genErr && genErr.lastRaw) || (streamErr && streamErr.lastRaw) || ''
      throw e
    })
  })
}

/** hunyuan 提供方部分环境不支持 system 角色，合并进 user */
function buildMessages(userPrompt, systemPrompt, provider) {
  const user = String(userPrompt || '').trim()
  const system = String(systemPrompt || '').trim()
  if (provider === 'hunyuan') {
    const merged = system ? system + '\n\n' + user : user
    return [{ role: 'user', content: merged }]
  }
  const list = []
  if (system) {
    list.push({ role: 'system', content: system })
  }
  list.push({ role: 'user', content: user })
  return list
}

module.exports = {
  collectStreamResult,
  streamTextCollect,
  generateTextCollect,
  invokeModelCollect,
  buildMessages,
  extractTextFromGenerateRes,
  detectApiError
}
