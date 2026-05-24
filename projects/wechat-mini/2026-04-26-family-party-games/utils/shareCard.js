/**
 * shareCardGenerator 云函数封装
 */
const { getCallFunctionConfig, ensureCloudInit } = require('./cloudInit')
const { renderShareInviteCard } = require('./shareInviteCard')

let useCloudCard = true
try {
  const cfg = require('../cloud-env.js')
  if (cfg && cfg.useShareCardGenerator === false) {
    useCloudCard = false
  }
} catch (e) {
  useCloudCard = true
}

const ACTION_MAP = {
  invite: 'generateInviteCard',
  achievement: 'generateAchievementCard',
  unlock: 'generateUnlockCard',
  generic: 'generateGenericCard'
}

function callShareCard(action, data) {
  return new Promise((resolve, reject) => {
    if (!wx.cloud || !ensureCloudInit()) {
      reject(new Error('云开发未初始化'))
      return
    }
    wx.cloud.callFunction({
      name: 'shareCardGenerator',
      config: getCallFunctionConfig(),
      data: { action: action, data: data || {} },
      success: (res) => {
        const r = (res && res.result) || {}
        if (r.errMsg && r.ok === false) {
          reject(new Error(String(r.errMsg)))
          return
        }
        if (r.ok === false) {
          reject(new Error(String(r.errMsg || '生成失败')))
          return
        }
        resolve(r.data != null ? r.data : r)
      },
      fail: reject
    })
  })
}

function localInviteFallback(data) {
  const code = String(data.roomCode || '').replace(/\D/g, '').slice(0, 6)
  return renderShareInviteCard({
    title: data.title || '家庭聚会助手',
    code: code,
    tagline: data.subtitle || '口令进组，马上开玩'
  }).then((path) => ({
    svg: '',
    qrCode: path,
    shareUrl: '',
    roomCode: code,
    localImage: path
  }))
}

/**
 * @param {'invite'|'achievement'|'unlock'|'generic'} type
 * @param {object} data
 */
async function generateShareCard(type, data) {
  const action = ACTION_MAP[type] || ACTION_MAP.invite
  if (!useCloudCard) {
    if (type === 'invite' || type === 'generic') {
      return localInviteFallback(data || {})
    }
    return { svg: '', qrCode: '', shareUrl: '' }
  }
  try {
    return await callShareCard(action, data || {})
  } catch (e) {
    if (type === 'invite' || type === 'generic') {
      return localInviteFallback(data || {})
    }
    throw e
  }
}

function buildShareCardPageUrl(type, params) {
  const q = Object.assign({ type: type || 'invite' }, params || {})
  const parts = []
  Object.keys(q).forEach((k) => {
    if (q[k] != null && q[k] !== '') {
      parts.push(k + '=' + encodeURIComponent(String(q[k])))
    }
  })
  return '/pages/share/card/card?' + parts.join('&')
}

module.exports = {
  generateShareCard,
  buildShareCardPageUrl,
  callShareCard
}
