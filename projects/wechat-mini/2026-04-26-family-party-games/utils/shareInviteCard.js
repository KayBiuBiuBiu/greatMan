/**
 * 聚会分享卡片图（离屏 canvas → 临时路径，供 onShareAppMessage imageUrl）
 */
const W = 500
const H = 400
const TAGLINES = [
  '亲友同屏，今晚更精彩',
  '口令进组，马上开玩',
  '聚会必备，一起来嗨',
  '叫上好友，同场互动'
]

const _cache = {}

function pickTagline(code) {
  const n = (code && String(code).length) || 0
  return TAGLINES[n % TAGLINES.length]
}

function canOffscreen() {
  return typeof wx !== 'undefined' && typeof wx.createOffscreenCanvas === 'function'
}

function drawCard(ctx, opts) {
  const title = (opts && opts.title) || '家庭聚会助手'
  const code = (opts && opts.code) ? String(opts.code) : ''
  const tagline = (opts && opts.tagline) || pickTagline(code)

  const g = ctx.createLinearGradient(0, 0, W, H)
  g.addColorStop(0, '#fff4e8')
  g.addColorStop(1, '#ffe0c2')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, W, H)

  ctx.fillStyle = '#8a3a0a'
  ctx.font = 'bold 28px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(title.slice(0, 14), W / 2, 72)

  ctx.fillStyle = '#166534'
  ctx.font = '22px sans-serif'
  ctx.fillText(tagline, W / 2, 118)

  if (code) {
    ctx.fillStyle = '#ffffff'
    ctx.strokeStyle = '#07c160'
    ctx.lineWidth = 4
    const bw = 320
    const bh = 88
    const bx = (W - bw) / 2
    const by = 160
    ctx.fillRect(bx, by, bw, bh)
    ctx.strokeRect(bx, by, bw, bh)
    ctx.fillStyle = '#111'
    ctx.font = 'bold 40px monospace'
    ctx.fillText(code, W / 2, by + 58)
    ctx.fillStyle = '#6b5a4a'
    ctx.font = '18px sans-serif'
    ctx.fillText('输入口令进组', W / 2, 280)
  }

  ctx.fillStyle = '#9ca3af'
  ctx.font = '16px sans-serif'
  ctx.fillText('家庭聚会助手', W / 2, H - 28)
}

function exportTempPath(canvas) {
  return new Promise((resolve, reject) => {
    wx.canvasToTempFilePath({
      canvas,
      fileType: 'jpg',
      quality: 0.92,
      success: (res) => resolve(res.tempFilePath),
      fail: reject
    })
  })
}

/**
 * @param {{ title?: string, code?: string, tagline?: string }} opts
 * @returns {Promise<string>} tempFilePath
 */
function generateShareInviteImage(opts) {
  const o = opts || {}
  const key =
    (o.title || '') +
    '|' +
    (o.code || '') +
    '|' +
    (o.tagline || '')
  if (_cache[key]) {
    return Promise.resolve(_cache[key])
  }
  if (!canOffscreen()) {
    return Promise.resolve('')
  }
  return new Promise((resolve) => {
    try {
      const canvas = wx.createOffscreenCanvas({ type: '2d', width: W, height: H })
      const ctx = canvas.getContext('2d')
      drawCard(ctx, o)
      exportTempPath(canvas)
        .then((path) => {
          if (path) {
            _cache[key] = path
          }
          resolve(path || '')
        })
        .catch(() => resolve(''))
    } catch (e) {
      resolve('')
    }
  })
}

/**
 * 预生成并挂到 page._shareCardImageUrl
 * @param {object} page
 * @param {{ title: string, code?: string, roomCode?: string }} opts
 */
function warmShareCard(page, opts) {
  if (!page) {
    return
  }
  const code = (opts && (opts.code || opts.roomCode)) || ''
  const title = (opts && opts.title) || '家庭聚会助手'
  generateShareInviteImage({
    title,
    code: String(code).replace(/\D/g, '').slice(0, 8) || '',
    tagline: opts.tagline
  }).then((path) => {
    if (path) {
      page._shareCardImageUrl = path
    }
  })
}

function getShareCardUrl(page, ctx) {
  if (ctx && ctx.imageUrl) {
    return ctx.imageUrl
  }
  if (page && page._shareCardImageUrl) {
    return page._shareCardImageUrl
  }
  return ''
}

module.exports = {
  generateShareInviteImage,
  warmShareCard,
  getShareCardUrl,
  pickTagline
}
