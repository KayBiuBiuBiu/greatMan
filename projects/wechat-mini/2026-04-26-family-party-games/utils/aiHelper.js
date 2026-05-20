/**
 * 微信云开发 AI（wx.cloud.extend.AI，模型见 cloud-env.js）
 * hunyuan + hunyuan-lite，非流式 generateText
 */
const PROMPTS = require('./aiSystemPrompts')
const {
  ensureCloudInit,
  getCallFunctionConfig,
  getCloudEnvId,
  debugCloudLog
} = require('./cloudInit')

const DEFAULT_MODEL = 'hunyuan-lite'
const DEFAULT_PROVIDER = 'hunyuan'

const CACHE_TTL_MS = 5 * 60 * 1000
const DEBOUNCE_MS = 800
const REQUEST_TIMEOUT_MS = 20000
const MAX_TEXT_RETRIES = 1
const LOADING_SLOW_MS = 3000
/** 与 imageService config.json timeout(60s) 对齐，略留余量 */
const IMAGE_TIMEOUT_MS = 65000

const SENSITIVE_RE = /赌博|色情|裸体|毒品|自残|自杀/i

const _cache = Object.create(null)
const _inflight = Object.create(null)

let aiProvider = DEFAULT_PROVIDER
let modelCandidates = [DEFAULT_MODEL]
try {
  const cfg = require('../cloud-env.js')
  if (cfg && cfg.aiProvider) {
    aiProvider = cfg.aiProvider
  }
  if (cfg && cfg.aiModels && cfg.aiModels.length) {
    modelCandidates = cfg.aiModels.slice()
  }
} catch (e) {
  /* use defaults */
}

function ensureCloud() {
  return ensureCloudInit()
}

function getModelCandidates() {
  return modelCandidates.slice()
}

function logAiCall(info) {
  if (!debugCloudLog) {
    return
  }
  /* eslint-disable no-console */
  console.log('[ai]', Object.assign({ env: getCloudEnvId() || '(工具当前云环境)' }, info))
  /* eslint-enable no-console */
}

function buildChatMessages(userPrompt, systemPrompt) {
  const system = String(systemPrompt || '').trim()
  const user = String(userPrompt || '').trim()
  // hunyuan 提供方部分环境不支持 system 角色，合并进 user
  if (aiProvider === 'hunyuan') {
    return [{ role: 'user', content: system ? system + '\n\n' + user : user || '你好' }]
  }
  const messages = []
  if (system) {
    messages.push({ role: 'system', content: system })
  }
  messages.push({ role: 'user', content: user || '你好' })
  return messages
}

function parseGenerateTextRes(res) {
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
    const err = new Error('generateText 返回空文本')
    try {
      err.lastRaw = JSON.stringify(body || res).slice(0, 300)
    } catch (e2) {
      err.lastRaw = ''
    }
    throw err
  }
  return {
    text: text,
    usage: (body && body.usage) || (res && res.usage) || null
  }
}

function hasClientAi() {
  return !!(wx.cloud && wx.cloud.extend && wx.cloud.extend.AI && wx.cloud.extend.AI.createModel)
}

function isTimeoutErr(err) {
  const raw = formatAiErr(err)
  return /timeout|超时|timed out/i.test(raw)
}

function formatAiErr(err) {
  const raw =
    (err && err.message) ||
    (err && err.errMsg) ||
    (typeof err === 'string' ? err : '') ||
    ''
  if (/Model not found|模型未找到|model.*not found|未开通/i.test(raw)) {
    return (
      '模型未开通。请在云开发控制台开通 hunyuan-lite（hunyuan 提供方）。' +
      (raw ? '\n' + String(raw).slice(0, 100) : '')
    )
  }
  if (/空文本|empty|FAIL|未开通|quota|余额|资源包/i.test(raw)) {
    return (
      'AI 接口无有效回复。请到云开发控制台 → AI 开通 hunyuan-lite 资源包；Console 查看 [ai] 日志。' +
      (raw ? '\n' + String(raw).slice(0, 120) : '')
    )
  }
  if (/Invalid env|环境/.test(raw)) {
    return '云环境无效：请确认 cloud-env.js 中 envId 与开发者工具一致'
  }
  if (/timeout|超时/.test(raw)) {
    return 'AI 请求超时，请稍后重试'
  }
  return raw.slice(0, 120) || 'AI 暂不可用'
}

function stableKey(parts) {
  return parts
    .map((p) => String(p == null ? '' : p))
    .join('\x1e')
}

function buildAiCacheKey(meta) {
  const m = meta || {}
  const scope = [
    m.cacheTag || m.cacheKey || 'ai',
    m.roomId || '',
    m.round != null ? String(m.round) : ''
  ].join('|')
  return stableKey([scope, String(m.system || ''), String(m.prompt || '')])
}

function getCacheEntry(key) {
  const e = _cache[key]
  if (!e) {
    return null
  }
  if (Date.now() - e.at > CACHE_TTL_MS) {
    delete _cache[key]
    return null
  }
  return e.text
}

function setCacheEntry(key, text) {
  _cache[key] = { text: String(text || ''), at: Date.now() }
  const keys = Object.keys(_cache)
  if (keys.length > 64) {
    const now = Date.now()
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i]
      if (now - _cache[k].at > CACHE_TTL_MS) {
        delete _cache[k]
      }
    }
  }
}

function clearAiCache() {
  Object.keys(_cache).forEach((k) => {
    delete _cache[k]
  })
  Object.keys(_inflight).forEach((k) => {
    delete _inflight[k]
  })
}

function resolveCacheMeta(page, opts) {
  const o = opts || {}
  const d = (page && page.data) || {}
  const st = d.state || {}
  let roomId = o.roomId != null ? o.roomId : d.roomId || ''
  if (!roomId && d.roomCode) {
    roomId = String(d.roomCode)
  }
  let round =
    o.round != null
      ? o.round
      : st.currentRound != null
        ? st.currentRound
        : d.roundDisp != null
          ? d.roundDisp
          : d.tdRound != null
            ? d.tdRound
            : ''
  return {
    cacheTag: o.cacheTag || o.cacheKey || 'ai',
    roomId: String(roomId || ''),
    round: round === '' ? '' : String(round)
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      reject(new Error('timeout'))
    }, ms)
    promise.then(
      (v) => {
        clearTimeout(t)
        resolve(v)
      },
      (e) => {
        clearTimeout(t)
        reject(e)
      }
    )
  })
}

function clientGenerateText(userPrompt, systemPrompt) {
  if (!ensureCloud()) {
    return Promise.reject(new Error('未开通云开发'))
  }
  if (!hasClientAi()) {
    return Promise.reject(new Error('当前基础库不支持 wx.cloud.extend.AI，请升级基础库至 3.15.1+'))
  }

  const models = getModelCandidates()
  let lastErr = null

  function tryAt(index) {
    if (index >= models.length) {
      return Promise.reject(lastErr || new Error('客户端 AI 失败'))
    }
    const modelName = models[index]
    const chatModel = wx.cloud.extend.AI.createModel(aiProvider)
    const messages = buildChatMessages(userPrompt, systemPrompt)
    return chatModel
      .generateText({
        data: {
          model: modelName,
          messages: messages
        }
      })
      .then((res) => {
        const parsed = parseGenerateTextRes(res)
        logAiCall({
          via: 'client',
          provider: aiProvider,
          modelUsed: modelName,
          usage: parsed.usage
        })
        return {
          text: parsed.text,
          via: 'client',
          modelUsed: aiProvider + '/' + modelName,
          usage: parsed.usage
        }
      })
      .catch((err) => {
        lastErr = err
        logAiCall({
          via: 'client',
          provider: aiProvider,
          modelUsed: modelName,
          error: formatAiErr(err)
        })
        return tryAt(index + 1)
      })
  }

  return tryAt(0)
}

function cloudGenerateText(userPrompt, systemPrompt) {
  if (!ensureCloud()) {
    return Promise.reject(new Error('未开通云开发'))
  }
  return new Promise((resolve, reject) => {
    wx.cloud.callFunction({
      name: 'aiPartyService',
      config: getCallFunctionConfig(),
      data: {
        action: 'chat',
        prompt: String(userPrompt || ''),
        system: String(systemPrompt || '')
      },
      success: (res) => {
        const r = (res && res.result) || {}
        if (r.errMsg) {
          reject(new Error(String(r.errMsg)))
          return
        }
        const text = String(r.text || '').trim()
        if (!text) {
          reject(new Error('云函数返回空文本'))
          return
        }
        logAiCall({
          via: r.via || 'cloudFunction',
          modelUsed: r.modelUsed,
          usage: r.usage
        })
        resolve({
          text: text,
          via: r.via || 'cloudFunction',
          modelUsed: r.modelUsed || '',
          usage: r.usage
        })
      },
      fail: (err) => {
        reject(err || new Error('云函数 aiPartyService 调用失败（请确认已上传并部署）'))
      }
    })
  })
}

function generateTextOnce(userPrompt, systemPrompt) {
  const p = hasClientAi()
    ? clientGenerateText(userPrompt, systemPrompt).catch((clientErr) => {
        return cloudGenerateText(userPrompt, systemPrompt).catch(() => {
          throw clientErr
        })
      })
    : cloudGenerateText(userPrompt, systemPrompt)
  return withTimeout(p, REQUEST_TIMEOUT_MS)
}

function generateTextWithRetry(userPrompt, systemPrompt) {
  let attempt = 0
  function run() {
    return generateTextOnce(userPrompt, systemPrompt).catch((err) => {
      if (attempt < MAX_TEXT_RETRIES && isTimeoutErr(err)) {
        attempt += 1
        return run()
      }
      throw err
    })
  }
  return run()
}

function generateText(userPrompt, systemPrompt) {
  return generateTextWithRetry(userPrompt, systemPrompt).then((r) => r.text)
}

/** 长按首页标题触发：跳过缓存，验证 AI 是否计入当前云环境 */
function testAiConnectivity() {
  if (!wx.cloud) {
    showAiModal('AI 不可用', '请先开通云开发')
    return
  }
  ensureCloud()
  wx.showLoading({ title: 'AI 连通测试…', mask: true })
  clearAiCache()
  const envHint = getCloudEnvId() || '(与工具当前云环境一致)'
  const testSystem = '你是聚会助手。'

  generateTextWithRetry('你好', testSystem)
    .then((r) => {
      wx.hideLoading()
      const tokens =
        r.usage && r.usage.total_tokens != null ? `\nToken：${r.usage.total_tokens}` : ''
      showAiModal(
        'AI 连通成功',
        `环境：${envHint}\n通道：${r.via || 'client'}\n模型：${r.modelUsed || DEFAULT_MODEL}\n回复：${r.text}${tokens}`
      )
    })
    .catch((err) => {
      wx.hideLoading()
      const extra = err && err.lastRaw ? '\n\n接口片段:\n' + String(err.lastRaw).slice(0, 200) : ''
      showAiModal(
        'AI 连通失败',
        formatAiErr(err) +
          extra +
          '\n\n请确认：① 云环境 cloud1-d9g01no7m292bc511；② 已开通 hunyuan-lite；③ 已重新部署 aiPartyService。'
      )
    })
}

function generateTextCached(userPrompt, systemPrompt, cacheMeta, skipRead) {
  const meta = Object.assign({}, cacheMeta, {
    prompt: userPrompt,
    system: systemPrompt
  })
  const key = buildAiCacheKey(meta)
  if (!skipRead) {
    const hit = getCacheEntry(key)
    if (hit != null) {
      return Promise.resolve({ text: hit, fromCache: true })
    }
  }
  if (_inflight[key] && !skipRead) {
    return _inflight[key]
  }
  const p = generateTextWithRetry(userPrompt, systemPrompt)
    .then((r) => {
      const text = r.text
      setCacheEntry(key, text)
      delete _inflight[key]
      return { text: text, fromCache: false }
    })
    .catch((err) => {
      delete _inflight[key]
      throw err
    })
  _inflight[key] = p
  return p
}

function stripEmoji(text) {
  return String(text || '').replace(
    /[\uD800-\uDBFF][\uDC00-\uDFFF]|[\u2600-\u27BF]|[\u2300-\u23FF]/g,
    ''
  )
}

function sanitizeDisplayText(text, maxLen) {
  let s = stripEmoji(String(text || ''))
    .replace(/\s+/g, ' ')
    .trim()
  if (SENSITIVE_RE.test(s)) {
    s = s.replace(SENSITIVE_RE, '***')
  }
  const n = maxLen | 0
  if (n > 0 && s.length > n) {
    s = s.slice(0, n) + '…'
  }
  return s
}

function postProcessText(text, opts) {
  const o = opts || {}
  return sanitizeDisplayText(text, o.maxLen || 500)
}

function parseJsonObject(text) {
  const raw = String(text || '').trim()
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw)
  } catch (e) {
    /* continue */
  }
  const m = raw.match(/\{[\s\S]*\}/)
  if (m) {
    try {
      return JSON.parse(m[0])
    } catch (e2) {
      return null
    }
  }
  return null
}

function pickWordField(obj, keys) {
  if (!obj || typeof obj !== 'object') {
    return ''
  }
  for (let i = 0; i < keys.length; i++) {
    const v = obj[keys[i]]
    if (v != null && String(v).trim()) {
      return String(v).trim()
    }
  }
  return ''
}

/**
 * 卧底词对校验；返回 { ok, civilianWord, undercoverWord, err }
 */
function validateUndercoverPair(raw) {
  const o = typeof raw === 'string' ? parseJsonObject(raw) : raw
  if (!o) {
    return { ok: false, err: '无法解析 JSON' }
  }
  const civ = pickWordField(o, ['civilianWord', 'civilian', 'word1']).slice(0, 12)
  const uc = pickWordField(o, ['undercoverWord', 'undercover', 'word2']).slice(0, 12)
  if (!civ || !uc) {
    return { ok: false, err: '缺少平民词或卧底词' }
  }
  if (civ === uc) {
    return { ok: false, err: '两词不能相同' }
  }
  if (civ.length > 6 || uc.length > 6) {
    return { ok: false, err: '每词建议不超过 6 个字' }
  }
  if (SENSITIVE_RE.test(civ + uc)) {
    return { ok: false, err: '词组含不当内容，请重试' }
  }
  return { ok: true, civilianWord: civ, undercoverWord: uc }
}

function validateDrawWord(raw) {
  const o = typeof raw === 'string' ? parseJsonObject(raw) : raw
  if (!o) {
    return { ok: false, err: '无法解析 JSON' }
  }
  const w = pickWordField(o, ['word', 'title']).slice(0, 16)
  if (!w || w.length < 1) {
    return { ok: false, err: '缺少词语' }
  }
  if (w.length > 8) {
    return { ok: false, err: '词语过长' }
  }
  if (SENSITIVE_RE.test(w)) {
    return { ok: false, err: '词语含不当内容' }
  }
  return { ok: true, word: w }
}

function showAiModal(title, content) {
  wx.showModal({
    title: title || 'AI',
    content: sanitizeDisplayText(content, 500),
    showCancel: false,
    confirmText: '知道了'
  })
}

/**
 * 展示 AI 结果；cancel「换一个」触发 onRegenerate
 */
function showAiResult(title, content, opts) {
  const o = opts || {}
  const body = sanitizeDisplayText(content, o.maxLen || 500)
  if (!o.onRegenerate) {
    showAiModal(title, body)
    return
  }
  wx.showModal({
    title: title || 'AI',
    content: body,
    confirmText: '知道了',
    cancelText: '换一个',
    success: (r) => {
      if (r.cancel && o.onRegenerate) {
        o.onRegenerate()
      }
    }
  })
}

function showAiConfirm(title, content) {
  return new Promise((resolve) => {
    wx.showModal({
      title: title || 'AI',
      content: sanitizeDisplayText(content, 500),
      confirmText: '确定',
      cancelText: '取消',
      success: (r) => {
        resolve(!!(r && r.confirm))
      },
      fail: () => {
        resolve(false)
      }
    })
  })
}

function clearLoadingTimers(page) {
  if (page && page._aiLoadingSlowTimer) {
    clearTimeout(page._aiLoadingSlowTimer)
    page._aiLoadingSlowTimer = null
  }
}

function startLoadingTimers(page, o) {
  clearLoadingTimers(page)
  const slow = (o && o.loadingSlowTitle) || '生成时间较长，请稍候…'
  page._aiLoadingSlowTimer = setTimeout(() => {
    if (page.data && page.data.aiBusy) {
      wx.showLoading({ title: slow, mask: true })
    }
  }, LOADING_SLOW_MS)
}

function stopLoading(page) {
  clearLoadingTimers(page)
  wx.hideLoading()
}

function runAiRequest(page, o, userPrompt, systemPrompt, cacheMeta, skipCacheRead) {
  startLoadingTimers(page, o)
  return generateTextCached(userPrompt, systemPrompt, cacheMeta, skipCacheRead)
    .then((res) => {
      stopLoading(page)
      page.setData({ aiBusy: false })
      return res
    })
    .catch((err) => {
      stopLoading(page)
      page.setData({ aiBusy: false })
      throw err
    })
}

/**
 * @param {object} page
 * @param {object} opts
 * @param {string} [opts.system] 覆盖默认系统提示
 * @param {boolean} [opts.regenerate] 绕过缓存读取
 * @param {string} [opts.resultTitle] 设置则弹窗展示，并支持换一个
 * @param {boolean} [opts.allowRegenerate] 默认随 resultTitle 开启
 * @param {object} [opts.postProcess] { maxLen }
 */
function runAi(page, opts) {
  const o = opts || {}
  if (!page) {
    return
  }
  const { ensureAiUnlock, LEVEL } = require('./aiUnlock')
  const tier = o.aiUnlockTier != null ? o.aiUnlockTier | 0 : LEVEL.GEN
  if (!ensureAiUnlock(tier, o.aiUnlockName, page)) {
    return
  }
  const skipCacheRead = !!(o.regenerate || o.skipCache)
  if (!skipCacheRead) {
    const now = Date.now()
    if (page.data.aiBusy) {
      return
    }
    const lastTap = page._aiLastTapAt || 0
    if (now - lastTap < DEBOUNCE_MS) {
      return
    }
    page._aiLastTapAt = now
  } else if (page.data.aiBusy) {
    return
  }

  if (!wx.cloud) {
    showAiModal('AI 不可用', '请先开通云开发并选择环境 cloud1-d9g01no7m292bc511')
    return
  }

  const userPrompt = o.buildPrompt ? o.buildPrompt() : ''
  const systemPrompt = o.system || PROMPTS.SYSTEM_PARTY
  const cacheMeta = resolveCacheMeta(page, o)
  const cacheKey = buildAiCacheKey(
    Object.assign({}, cacheMeta, { prompt: userPrompt, system: systemPrompt })
  )

  const finish = (text, fromCache) => {
    const processed = postProcessText(text, o.postProcess)
    if (fromCache && o.toastOnCache !== false && !o.regenerate) {
      wx.showToast({ title: '已使用近期结果', icon: 'none', duration: 1200 })
    }
    if (o.onOk) {
      o.onOk(processed)
    }
    const title = o.resultTitle
    const canRegen = o.allowRegenerate !== false && title
    if (title) {
      const regenFn = canRegen
        ? () => {
            page._lastAiOpts = o
            runAi(page, Object.assign({}, o, { regenerate: true, skipCache: true }))
          }
        : null
      showAiResult(title, processed, { maxLen: (o.postProcess && o.postProcess.maxLen) || 500, onRegenerate: regenFn })
    }
  }

  if (!skipCacheRead) {
    const cached = getCacheEntry(cacheKey)
    if (cached != null) {
      finish(cached, true)
      return
    }
  }

  page.setData({ aiBusy: true })
  page._lastAiOpts = o
  wx.showLoading({ title: o.loadingTitle || 'AI 思考中…', mask: true })
  runAiRequest(page, o, userPrompt, systemPrompt, cacheMeta, skipCacheRead)
    .then((res) => {
      finish(res.text, res.fromCache)
    })
    .catch((err) => {
      showAiModal('AI 调用失败', formatAiErr(err))
    })
}

/**
 * 战报海报生图（需部署 imageService）
 */
function runAiPoster(page, opts) {
  const o = opts || {}
  if (!page || page.data.aiBusy) {
    return
  }
  const { ensureAiUnlock, LEVEL } = require('./aiUnlock')
  if (!ensureAiUnlock(LEVEL.RECAP, 'AI 战报海报', page)) {
    return
  }
  if (!wx.cloud) {
    showAiModal('生图不可用', '请先开通云开发')
    return
  }
  const prompt = o.buildPrompt ? o.buildPrompt() : ''
  if (!prompt) {
    return
  }
  page.setData({ aiBusy: true })
  wx.showLoading({ title: o.loadingTitle || '生成海报中…', mask: true })
  startLoadingTimers(page, {
    loadingSlowTitle: '海报生成较慢，请稍候…'
  })
  const call = () =>
    new Promise((resolve, reject) => {
      wx.cloud.callFunction({
        name: 'imageService',
        config: getCallFunctionConfig(),
        data: { action: 'poster', prompt: prompt },
        success: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            reject(new Error(String(r.errMsg)))
            return
          }
          if (r.success === false) {
            reject(new Error(String(r.message || r.code || '生图失败')))
            return
          }
          const url = r.imageUrl || r.url
          if (!url) {
            reject(new Error('未返回图片'))
            return
          }
          resolve({ url: String(url), revisedPrompt: r.revised_prompt || '' })
        },
        fail: (err) => {
          reject(err || new Error('imageService 调用失败'))
        }
      })
    })
  withTimeout(call(), IMAGE_TIMEOUT_MS)
    .then((img) => {
      stopLoading(page)
      page.setData({ aiBusy: false })
      if (o.onOk) {
        o.onOk(img.url, img)
      }
      wx.previewImage({ urls: [String(img.url)] })
    })
    .catch((err) => {
      stopLoading(page)
      page.setData({ aiBusy: false })
      showAiModal('海报生成失败', formatAiErr(err))
    })
}

module.exports = Object.assign({}, PROMPTS, {
  DEFAULT_MODEL,
  CACHE_TTL_MS,
  DEBOUNCE_MS,
  REQUEST_TIMEOUT_MS,
  LOADING_SLOW_MS,
  ensureCloud,
  hasClientAi,
  generateText,
  generateTextCached,
  buildAiCacheKey,
  clearAiCache,
  parseJsonObject,
  validateUndercoverPair,
  validateDrawWord,
  postProcessText,
  sanitizeDisplayText,
  showAiModal,
  showAiResult,
  showAiConfirm,
  runAi,
  runAiPoster,
  testAiConnectivity,
  formatAiErr,
  getCloudEnvId
})
