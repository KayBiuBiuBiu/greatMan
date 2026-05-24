/**
 * hostAgentEnhanced 云函数封装（失败时回退 hostAgent）
 */
const { getCallFunctionConfig, ensureCloudInit } = require('../../utils/cloudInit')

let useEnhanced = true
try {
  const cfg = require('../../cloud-env.js')
  if (cfg && cfg.useHostAgentEnhanced === false) {
    useEnhanced = false
  }
} catch (e) {
  useEnhanced = true
}

function callFunction(name, payload) {
  return new Promise((resolve, reject) => {
    if (!wx.cloud || !ensureCloudInit()) {
      reject(new Error('云开发未初始化'))
      return
    }
    wx.cloud.callFunction({
      name: name,
      config: getCallFunctionConfig(),
      data: payload,
      success: (res) => {
        const r = (res && res.result) || {}
        if (r.errMsg && r.ok === false) {
          reject(new Error(String(r.errMsg)))
          return
        }
        if (r.ok === false) {
          reject(new Error(String(r.errMsg || '调用失败')))
          return
        }
        resolve(r.data != null ? r.data : r)
      },
      fail: (err) => reject(err)
    })
  })
}

function callHostAgentLegacy(action, data) {
  const { callHostAgent } = require('../../utils/hostAgentCloud')
  const legacyAction =
    action === 'getHint'
      ? 'playerAssist'
      : action === 'recap'
        ? 'recap'
        : 'chat'
  const payload = Object.assign({ action: legacyAction }, data || {})
  return new Promise((resolve, reject) => {
    callHostAgent(payload, {
      silent: true,
      onOk: (res) => {
        const r = (res && res.result) || {}
        if (r.errMsg) {
          reject(new Error(r.errMsg))
          return
        }
        if (action === 'getHint') {
          resolve({ hint: r.text || '', summary: r.summary })
        } else if (action === 'recap') {
          resolve({ recap: r.text || r.article || '', text: r.text || r.article })
        } else {
          resolve({
            phase: 'unknown',
            summary: r.summary || '',
            analysis: r.text || ''
          })
        }
      },
      onError: reject
    })
  })
}

/**
 * @param {'analyze'|'getHint'|'recap'|'ping'} action
 * @param {object} data
 */
async function callAIHost(action, data) {
  if (!useEnhanced) {
    return callHostAgentLegacy(action, data)
  }
  try {
    return await callFunction('hostAgentEnhanced', { action: action, data: data || {} })
  } catch (e) {
    return callHostAgentLegacy(action, data)
  }
}

async function analyzeGame(roomId, gameKind, extra) {
  return callAIHost('analyze', Object.assign({ roomId: roomId, gameKind: gameKind }, extra || {}))
}

async function getHint(roomId, gameKind, playerHint) {
  return callAIHost('getHint', {
    roomId: roomId,
    gameKind: gameKind,
    playerHint: playerHint || ''
  })
}

async function generateRecap(gameData) {
  return callAIHost('recap', gameData || {})
}

async function pingEnhanced() {
  return callAIHost('ping', {})
}

/**
 * 房间页 AI 增强菜单（策略 / 分析 / 战报）
 */
function runEnhancedAgentMenu(page, opts) {
  const o = opts || {}
  if (!page) {
    return
  }
  const { ensureAiUnlock, LEVEL } = require('../../utils/aiUnlock')
  wx.showActionSheet({
    itemList: ['获取策略建议', '查看游戏分析', '生成战报'],
    success: (res) => {
      const idx = res.tapIndex
      if (idx === 0) {
        if (!ensureAiUnlock(LEVEL.ASSIST, 'AI 策略建议', page)) {
          return
        }
        page.setData({ agentBusy: true })
        wx.showLoading({ title: 'AI 分析中…', mask: true })
        getHint(o.roomId, o.gameKind, o.playerHint)
          .then((data) => {
            wx.hideLoading()
            page.setData({ agentBusy: false })
            wx.showModal({
              title: '策略建议',
              content: String((data && data.hint) || '').slice(0, 500),
              showCancel: false
            })
          })
          .catch((err) => {
            wx.hideLoading()
            page.setData({ agentBusy: false })
            wx.showToast({ title: (err && err.message) || '获取失败', icon: 'none' })
          })
        return
      }
      if (idx === 1) {
        if (!ensureAiUnlock(LEVEL.ASSIST, '游戏分析', page)) {
          return
        }
        page.setData({ agentBusy: true })
        wx.showLoading({ title: '分析局面…', mask: true })
        analyzeGame(o.roomId, o.gameKind, o.extra)
          .then((data) => {
            wx.hideLoading()
            page.setData({ agentBusy: false })
            const text = (data && (data.analysis || data.summary)) || ''
            wx.showModal({
              title: '游戏分析 · ' + ((data && data.phase) || ''),
              content: String(text).slice(0, 500),
              showCancel: false
            })
            if (o.onAnalysis) {
              o.onAnalysis(data)
            }
          })
          .catch((err) => {
            wx.hideLoading()
            page.setData({ agentBusy: false })
            wx.showToast({ title: (err && err.message) || '分析失败', icon: 'none' })
          })
        return
      }
      if (idx === 2) {
        if (!ensureAiUnlock(LEVEL.RECAP, '智能战报', page)) {
          return
        }
        page.setData({ agentBusy: true })
        wx.showLoading({ title: '生成战报…', mask: true })
        generateRecap({
          gameKind: o.gameKind,
          gameName: o.gameName,
          publicLog: o.publicLog || []
        })
          .then((data) => {
            wx.hideLoading()
            page.setData({ agentBusy: false })
            const text = (data && (data.recap || data.text)) || ''
            wx.showModal({
              title: '智能战报',
              content: text.slice(0, 500),
              confirmText: '知道了',
              cancelText: '复制',
              success: (m) => {
                if (m.cancel && text) {
                  wx.setClipboardData({ data: text })
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
    }
  })
}

module.exports = {
  callAIHost,
  analyzeGame,
  getHint,
  generateRecap,
  pingEnhanced,
  runEnhancedAgentMenu
}
