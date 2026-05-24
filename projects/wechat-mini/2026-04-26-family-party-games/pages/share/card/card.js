const { generateShareCard } = require('../../../utils/shareCard')

function readNick() {
  try {
    const p = wx.getStorageSync('party_user_profile')
    if (p && p.nickName) {
      return String(p.nickName).trim()
    }
  } catch (e) {}
  try {
    return String(wx.getStorageSync('hb_nick') || wx.getStorageSync('uc_nick') || '玩家').trim()
  } catch (e2) {
    return '玩家'
  }
}

Page({
  data: {
    loading: true,
    error: '',
    cardSvg: '',
    previewImage: '',
    qrCode: '',
    shareUrl: '',
    roomCode: '',
    type: 'invite',
    gameKind: 'undercover',
    canShare: false
  },

  onLoad(options) {
    const o = options || {}
    let detail = ''
    try {
      detail = o.detail ? decodeURIComponent(o.detail) : ''
    } catch (e) {
      detail = o.detail || ''
    }
    this.setData({
      type: o.type || 'invite',
      gameKind: o.gameKind || 'undercover',
      roomId: o.roomId || '',
      roomCode: o.roomCode || '',
      gameId: o.gameId || '',
      detail: detail
    })
    this.generateCard()
  },

  async generateCard() {
    const type = this.data.type
    const playerName = readNick()
    const payload = {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode,
      gameKind: this.data.gameKind,
      playerName: playerName,
      title: type === 'achievement' ? '本局战绩' : undefined,
      detail: this.data.detail || ''
    }
    if (type === 'achievement' && this.data.gameId) {
      payload.gameId = this.data.gameId
    }
    this.setData({ loading: true, error: '' })
    try {
      const cardType = type === 'achievement' ? 'achievement' : type === 'unlock' ? 'unlock' : 'invite'
      const data = await generateShareCard(cardType, payload)
      const preview =
        data.localImage ||
        (data.qrCode && /^https?:\/\//.test(data.qrCode) ? data.qrCode : '') ||
        (data.qrCode && data.qrCode.indexOf('wxfile://') === 0 ? data.qrCode : '') ||
        ''
      this.setData({
        loading: false,
        cardSvg: data.svg || '',
        qrCode: data.qrCode || '',
        shareUrl: data.shareUrl || '',
        roomCode: data.roomCode || payload.roomCode || '',
        previewImage: preview,
        canShare: !!preview || !!(data.roomCode || payload.roomCode)
      })
      this._sharePayload = Object.assign({}, payload, data)
    } catch (e) {
      this.setData({
        loading: false,
        error: (e && e.message) || '生成失败，请确认已部署 shareCardGenerator'
      })
    }
  },

  onSaveImage() {
    const url = this.data.previewImage || this.data.qrCode
    if (!url) {
      wx.showToast({ title: '暂无图片', icon: 'none' })
      return
    }
    if (/^https?:\/\//.test(url)) {
      wx.previewImage({ urls: [url] })
      return
    }
    wx.previewImage({ urls: [url] })
  },

  onShareAppMessage() {
    const p = this._sharePayload || {}
    const code = p.roomCode || this.data.roomCode || ''
    return {
      title: code ? '一起来玩！口令 ' + code : '家庭聚会助手',
      path: p.shareUrl || '/pages/index/index',
      imageUrl: this.data.previewImage || ''
    }
  }
})
