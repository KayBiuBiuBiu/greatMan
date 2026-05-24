/**
 * 聚会 Agent：云开发 Agent Bot（优先）或 hostAgent 云函数（兜底）
 */
const { getCallFunctionConfig, getCloudEnvId, debugCloudLog } = require('./cloudInit')
const { callHostAgent } = require('./hostAgentCloud')
const { agentSpeak, playHostVoice } = require('./agentTts')

let agentBotId = ''
let agentEnabled = true
let featureAiButtonsOn = true
try {
  const cfg = require('../cloud-env.js')
  agentBotId = (cfg && cfg.agentBotId) || ''
  if (cfg && typeof cfg.agentEnabled === 'boolean') {
    agentEnabled = cfg.agentEnabled
  }
} catch (e) {
  agentBotId = ''
}
try {
  featureAiButtonsOn = require('../data/feature-flags').isAiButtonsEnabled()
} catch (e) {
  featureAiButtonsOn = true
}

const _threads = Object.create(null)

function hasBotApi() {
  return !!(
    wx.cloud &&
    wx.cloud.extend &&
    wx.cloud.extend.AI &&
    wx.cloud.extend.AI.bot &&
    typeof wx.cloud.extend.AI.bot.sendMessage === 'function'
  )
}

function threadKey(gameKind, roomId) {
  return String(gameKind || 'g') + ':' + String(roomId || '0')
}

function getOrCreateThreadId(gameKind, roomId) {
  const k = threadKey(gameKind, roomId)
  if (!_threads[k]) {
    _threads[k] =
      't_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10)
  }
  return _threads[k]
}

async function collectBotStream(res) {
  let text = ''
  if (res && res.textStream) {
    for await (const str of res.textStream) {
      text += str
    }
  }
  if (!text && res && res.eventStream) {
    for await (const event of res.eventStream) {
      if (event.data === '[DONE]') {
        break
      }
      try {
        const data = JSON.parse(event.data)
        if (data && data.content) {
          text += data.content
        }
        const delta =
          data &&
          data.choices &&
          data.choices[0] &&
          data.choices[0].delta &&
          data.choices[0].delta.content
        if (delta) {
          text += delta
        }
      } catch (e) {
        /* ignore */
      }
    }
  }
  return String(text || '').trim()
}

function sendBotMessage(prompt, opts) {
  const o = opts || {}
  if (!agentBotId) {
    return Promise.reject(new Error('未配置 agentBotId'))
  }
  const threadId = o.threadId || getOrCreateThreadId(o.gameKind, o.roomId)
  const bot = wx.cloud.extend.AI.bot
  return bot
    .sendMessage({
      data: {
        botId: agentBotId,
        threadId: threadId,
        runId: o.runId || 'run_' + Date.now(),
        messages: [
          {
            id: 'msg_' + Date.now(),
            role: 'user',
            content: String(prompt || '')
          }
        ],
        tools: o.tools || [],
        context: o.context || [],
        state: o.state || {},
        forwardedProps: o.forwardedProps || {}
      }
    })
    .then((res) => collectBotStream(res))
}

function callHostAgentPromise(data) {
  return new Promise((resolve, reject) => {
    callHostAgent(data, {
      silent: true,
      onOk: (res) => resolve((res && res.result) || {}),
      onError: (err) => reject(err)
    })
  })
}

/**
 * 统一 Agent 文本请求
 */
function runAgentText(opts) {
  const o = opts || {}
  const prompt = o.prompt || ''
  if (!agentEnabled) {
    return Promise.reject(new Error('Agent 未启用'))
  }
  if (agentBotId && hasBotApi()) {
    return sendBotMessage(prompt, o).catch((err) => {
      if (debugCloudLog) {
        console.warn('[agent] bot 失败，fallback hostAgent', err)
      }
      return callHostAgentPromise({
        action: o.hostAction || 'chat',
        system: o.system,
        prompt: prompt,
        gameKind: o.gameKind,
        roomId: o.roomId
      }).then((r) => r.text || '')
    })
  }
  return callHostAgentPromise({
    action: o.hostAction || 'chat',
    system: o.system,
    prompt: prompt,
    gameKind: o.gameKind,
    roomId: o.roomId,
    publicLog: o.publicLog,
    playerHint: o.playerHint
  }).then((r) => r.text || r.article || '')
}

/**
 * 玩家辅助：弹窗展示建议
 */
function runPlayerAssist(page, opts) {
  if (!featureAiButtonsOn) {
    return
  }
  const o = opts || {}
  if (!page) {
    return
  }
  const { ensureAiUnlock, LEVEL } = require('./aiUnlock')
  if (!ensureAiUnlock(LEVEL.ASSIST, 'AI 策略建议', page)) {
    return
  }
  if (page.data.agentBusy) {
    return
  }
  page.setData({ agentBusy: true })
  wx.showLoading({ title: 'AI 分析中…', mask: true })
  const action = agentBotId && hasBotApi() ? null : 'playerAssist'
  const chain = agentBotId && hasBotApi()
    ? sendBotMessage(
        '请根据局面给当前玩家一条策略建议：\n' + (o.playerHint || ''),
        o
      )
    : callHostAgentPromise({
        action: 'playerAssist',
        gameKind: o.gameKind,
        roomId: o.roomId,
        playerHint: o.playerHint
      }).then((r) => r.text || '')

  chain
    .then((text) => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      wx.showModal({
        title: o.title || 'AI 助手',
        content: String(text).slice(0, 500),
        showCancel: false
      })
      if (o.onOk) {
        o.onOk(text)
      }
    })
    .catch((err) => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      wx.showModal({
        title: 'AI 助手',
        content: (err && err.message) || '调用失败，请部署 hostAgent',
        showCancel: false
      })
    })
}

/**
 * 副主持 tick：自动推进 + 可选语音播报
 */
function runHostTick(page, opts) {
  const o = opts || {}
  if (!o.roomId || !o.gameKind) {
    return
  }
  const storageKey = 'agent_host_' + o.roomId
  if (!o.force && page && page._agentTickBusy) {
    return
  }
  if (page) {
    page._agentTickBusy = true
  }
  callHostAgent(
    {
      action: 'tick',
      gameKind: o.gameKind,
      roomId: o.roomId,
      autoExecute: o.autoExecute !== false,
      narrate: true
    },
    {
      silent: true,
      onOk: (res) => {
        if (page) {
          page._agentTickBusy = false
        }
        const r = (res && res.result) || {}
        if (o.speak !== false && (r.speakText || r.narrate || r.voiceUrl)) {
          playHostVoice(r)
        }
        if (o.onOk) {
          o.onOk(r)
        }
      },
      onError: () => {
        if (page) {
          page._agentTickBusy = false
        }
      }
    }
  )
}

/**
 * 战报
 */
function runGameRecap(page, opts) {
  if (!featureAiButtonsOn) {
    return
  }
  const o = opts || {}
  const { ensureAiUnlock, LEVEL } = require('./aiUnlock')
  if (!ensureAiUnlock(LEVEL.RECAP, '智能战报', page)) {
    return
  }
  page.setData({ agentBusy: true })
  wx.showLoading({ title: '生成战报…', mask: true })
  callHostAgentPromise({
    action: 'recap',
    gameKind: o.gameKind,
    gameName: o.gameName,
    publicLog: o.publicLog || []
  })
    .then((r) => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      const text = r.text || r.article || ''
      wx.showModal({
        title: '智能战报',
        content: text.slice(0, 500),
        confirmText: '知道了',
        cancelText: '复制',
        success: (m) => {
          if (m.cancel && text) {
            wx.setClipboardData({ data: text })
          }
          if (o.onOk) {
            o.onOk(text)
          }
        }
      })
    })
    .catch((err) => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      wx.showToast({ title: (err && err.message) || '战报失败', icon: 'none' })
    })
}

/**
 * 首页推荐
 */
function runPartyRecommend(page) {
  if (!page) {
    return
  }
  const { ensureAiUnlock, LEVEL } = require('./aiUnlock')
  if (!ensureAiUnlock(LEVEL.RECAP, 'AI 聚会建议', page)) {
    return
  }
  page.setData({ agentBusy: true })
  wx.showLoading({ title: 'AI 建议中…', mask: true })
  const ranks = (page.data && page.data.clickRanks) || {}
  callHostAgentPromise({ action: 'recommend', stats: { clickRanks: ranks } })
    .then((r) => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      wx.showModal({
        title: '聚会 AI 建议',
        content: String(r.text || '').slice(0, 500),
        showCancel: false
      })
    })
    .catch(() => {
      wx.hideLoading()
      page.setData({ agentBusy: false })
      wx.showToast({ title: '请先部署 hostAgent', icon: 'none' })
    })
}

/**
 * 副主持播报（支持 scene / customVars / 语音）
 */
function runHostNarrate(page, opts) {
  const o = opts || {}
  if (!featureAiButtonsOn) {
    return
  }
  if (!o.roomId || !o.gameKind) {
    return
  }
  const silent = !!o.silent
  if (page && !silent) {
    page.setData({ agentBusy: true })
  }
  if (!silent) {
    wx.showLoading({ title: '副主持播报…', mask: true })
  }
  callHostAgentPromise({
    action: 'hostNarrate',
    gameKind: o.gameKind,
    roomId: o.roomId,
    scene: o.scene || 'midgame',
    customVars: o.customVars || {},
    voiceSpeed: o.voiceSpeed
  })
    .then((r) => {
      if (!silent) {
        wx.hideLoading()
      }
      if (page) {
        page.setData({ agentBusy: false })
      }
      if (o.speak !== false) {
        playHostVoice(r)
      }
      if (o.onOk) {
        o.onOk(r)
      }
    })
    .catch((err) => {
      if (!silent) {
        wx.hideLoading()
      }
      if (page) {
        page.setData({ agentBusy: false })
      }
      if (!silent) {
        wx.showToast({ title: (err && err.message) || '播报失败', icon: 'none' })
      }
    })
}

function testAgentPing() {
  callHostAgent(
    { action: 'ping' },
    {
      onOk: (res) => {
        const r = (res && res.result) || {}
        wx.showModal({
          title: 'Agent 状态',
          content:
            'env: ' +
            (getCloudEnvId() || '-') +
            '\nbotId: ' +
            (agentBotId || '未配置') +
            '\nhasBotApi: ' +
            hasBotApi() +
            '\ncloud hasAi: ' +
            !!r.hasAi,
          showCancel: false
        })
      }
    }
  )
}

module.exports = {
  runAgentText,
  runPlayerAssist,
  runHostTick,
  runHostNarrate,
  runGameRecap,
  runPartyRecommend,
  testAgentPing,
  agentSpeak,
  playHostVoice,
  hasBotApi,
  getOrCreateThreadId
}
