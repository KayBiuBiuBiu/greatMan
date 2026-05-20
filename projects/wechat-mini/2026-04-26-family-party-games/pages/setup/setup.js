const { callRoomService } = require('../../utils/roomCloud')
const { callWerewolfService } = require('../../utils/werewolfCloud')
const { callUndercoverService } = require('../../utils/undercoverRoomCloud')
const { callMusic } = require('../../utils/musicRoomCloud')
const { callDraw } = require('../../utils/drawRoomCloud')
const { callDrink } = require('../../utils/drinkRoomCloud')

const {
  SIZES: WOLF_SIZES,
  HINT: WOLF_SIZE_HINT,
  indexOfSize,
  stepSizeIndex,
  vibrateBoundary,
  loadStoredSize,
  saveStoredSize
} = require('../../utils/wolfBoardSize')
const { stepIndex } = require('../../utils/listStepper')

const UC_SIZES = [4, 5, 6, 7, 8, 9, 10, 11, 12]
const UC_SIZE_HINT = '人数 4～12，需凑满开局'
Page({
  data: {
    title: '',
    screen: 'play',
    playerCount: 4,
    undercoverCount: 1,
    wolfSizeHint: WOLF_SIZE_HINT,
    wolfSizeIndex: 0,
    ucSizeHint: UC_SIZE_HINT,
    ucSizeIndex: 2
  },

  onLoad(query) {
    const title = decodeURIComponent(query.title || '')
    const screen = query.screen || 'play'
    const wolfInit = screen === 'werewolf' ? loadStoredSize() : 6
    const ucInit = 6
    const ucIdx = UC_SIZES.indexOf(ucInit) >= 0 ? UC_SIZES.indexOf(ucInit) : 2
    this.setData({
      title,
      screen,
      playerCount:
        screen === 'werewolf'
          ? wolfInit
          : screen === 'undercover'
            ? ucInit
            : screen === 'songGuess' || screen === 'drawGuess' || screen === 'drinkParty'
              ? 6
              : 4,
      undercoverCount: 1,
      wolfSizeIndex: screen === 'werewolf' ? indexOfSize(wolfInit) : 0,
      ucSizeIndex: screen === 'undercover' ? ucIdx : 0
    })
  },

  onWolfDecrease() {
    const r = stepSizeIndex(this.data.wolfSizeIndex, -1)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._setWolfBoardSize(r.index)
  },

  onWolfIncrease() {
    const r = stepSizeIndex(this.data.wolfSizeIndex, 1)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._setWolfBoardSize(r.index)
  },

  _setWolfBoardSize(index) {
    const n = WOLF_SIZES[index] || 6
    saveStoredSize(n)
    this.setData({ wolfSizeIndex: index, playerCount: n })
  },

  onUcDecrease() {
    const r = stepIndex(this.data.ucSizeIndex, -1, UC_SIZES.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._setUcBoardSize(r.index)
  },

  onUcIncrease() {
    const r = stepIndex(this.data.ucSizeIndex, 1, UC_SIZES.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._setUcBoardSize(r.index)
  },

  _setUcBoardSize(index) {
    const n = UC_SIZES[index] || 6
    const maxUndercover = this.maxUndercover(n)
    this.setData({
      ucSizeIndex: index,
      playerCount: n,
      undercoverCount: Math.min(this.data.undercoverCount, maxUndercover)
    })
  },

  onGenericDecrease() {
    const min = 1
    const maxG = 20
    const next = Math.max(min, (this.data.playerCount | 0) - 1)
    if (next === this.data.playerCount) {
      vibrateBoundary()
      return
    }
    this.setData({ playerCount: next })
  },

  onGenericIncrease() {
    const maxG = 20
    const next = Math.min(maxG, (this.data.playerCount | 0) + 1)
    if (next === this.data.playerCount) {
      vibrateBoundary()
      return
    }
    this.setData({ playerCount: next })
  },

  changeUndercover(event) {
    const delta = Number(event.currentTarget.dataset.delta)
    const undercoverCount = Math.max(1, Math.min(this.maxUndercover(this.data.playerCount), this.data.undercoverCount + delta))
    this.setData({ undercoverCount })
  },

  maxUndercover(playerCount) {
    if (playerCount >= 10) return 3
    if (playerCount >= 8) return 2
    return 1
  },

  startLocal () {
    if (this.data.screen === 'songGuess') {
      wx.showModal({
        title: '猜歌需多机同场',
        content: '请创建聚会组（会得到 6 位数字口令，不是人数），把口令发给亲友，或从首页输入加入。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'drinkParty') {
      wx.showModal({
        title: '趣味抽签需多机同场',
        content: '请创建聚会组并把 6 位数字口令发给每人；至少 2 人可开始。组长负责响铃与投票。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'drawGuess') {
      wx.showModal({
        title: '你画我猜需多机同场',
        content: '请创建聚会组并把数字口令发给每人；至少 2 人可开始。绘画与猜词在同场进行。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'werewolf') {
      wx.showModal({
        title: '身份推理需多机同场',
        content: '主持创建组后把 6 位数字口令发给大家进组。人齐后选板子人数（6/8/10/12）。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'undercover') {
      wx.showModal({
        title: '谁是卧底需同场同步',
        content: '每人用各自手机通过口令进聚会组，本机只显示自己的词。无线上匹配。',
        showCancel: false
      })
      return
    }
    this.goGame({})
  },

  createRoom () {
    if (this.data.screen === 'werewolf') {
      this.createWerewolfRoom()
      return
    }
    if (this.data.screen === 'undercover') {
      this.createUndercoverV2()
      return
    }
    if (this.data.screen === 'songGuess') {
      this.createMusicRoom()
      return
    }
    if (this.data.screen === 'drawGuess') {
      this.createDrawRoom()
      return
    }
    if (this.data.screen === 'drinkParty') {
      this.createDrinkRoom()
      return
    }
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }

    const game = this.buildGame()
    wx.showLoading({ title: '生成口令' })
    callRoomService(
      {
        action: 'create',
        nickName: '参与者',
        selectedGame: game,
        status: 'started'
      },
      {
        onOk: (result) => {
          wx.hideLoading()
          const r = result.result || {}
          if (!r.roomCode) {
            wx.showToast({ title: '生成失败', icon: 'none' })
            return
          }
          wx.showModal({
            title: '聚会组口令：' + r.roomCode,
            content: '把口令告诉身边的亲友，他们输入后会进入同一场互动。无陌生匹配。',
            confirmText: '开始互动',
            showCancel: false,
            success: () => this.goGame({ roomCode: r.roomCode })
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  buildGame() {
    return {
      title: this.data.title,
      screen: this.data.screen,
      config: this.getConfig()
    }
  },

  getConfig() {
    return {
      playerCount: this.data.playerCount,
      undercoverCount: this.data.undercoverCount,
      wolfDefaultSize: this.data.screen === 'werewolf' ? this.data.playerCount : 0,
      mode: this.data.screen === 'undercover' ? 'v2' : ''
    }
  },

  createWerewolfRoom() {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    const maxPlayers = this.data.playerCount | 0
    saveStoredSize(maxPlayers)
    callWerewolfService(
      { action: 'create', maxPlayers },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({
              title: '未返回组号，请检查身份推理云是否已部署',
              icon: 'none'
            })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = Object.assign(this.getConfig(), {
            roomId: r.roomId,
            roomCode: code
          })
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令告诉身边亲友，他们输入后进同一聚会组。人齐后选 6/8/10/12 人局。',
            confirmText: '开始互动',
            showCancel: false,
            success: (res) => {
              if (res.confirm) {
                this.goWerewolf(cfg)
              }
            }
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  goWerewolf(cfg) {
    const config = Object.assign(this.getConfig(), cfg || {})
    const u = `/pages/werewolf/werewolf?title=${encodeURIComponent(
      this.data.title
    )}&config=${encodeURIComponent(JSON.stringify(config))}`
    if (u.length > 2000) {
      wx.showToast({ title: '配置过长，请重试', icon: 'none' })
      return
    }
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进入身份推理组失败', icon: 'none' })
      }
    })
  },

  createUndercoverV2() {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    callUndercoverService(
      { action: 'create' },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({
              title: '未返回组号，请检查卧底云函数是否已部署',
              icon: 'none'
            })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = Object.assign(this.getConfig(), { mode: 'v2' }, {
            roomId: r.roomId,
            roomCode: code
          })
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令告诉身边亲友，他们输入后进同一聚会组。至少 3 人且需凑满设定人数。',
            confirmText: '开始互动',
            showCancel: false,
            success: (res) => {
              if (res.confirm) {
                this.goUcV2(cfg)
              }
            }
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  createMusicRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    const nick = (wx.getStorageSync('music_nick') || '房主').toString()
      .trim()
      .slice(0, 12) || '房主'
    wx.setStorageSync('music_nick', nick)
    wx.showLoading({ title: '建房' })
    callMusic(
      { action: 'create', nickName: nick },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '未返回组号，请检查云函数 musicRoomService', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令告诉朋友。建议至少 2 人；组长开题，主持本机外放抢答。',
            confirmText: '进入',
            showCancel: false,
            success: (res2) => {
              if (res2.confirm) {
                this.goSongGuess(cfg)
              }
            }
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  goSongGuess (cfg) {
    const c = Object.assign({ roomId: (cfg && cfg.roomId) || '' }, cfg || {})
    if (!c.roomId) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const u =
      '/pages/song-guess/song-guess?roomId=' +
      encodeURIComponent(String(c.roomId)) +
      '&roomCode=' +
      encodeURIComponent(String(c.roomCode || ''))
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进组失败', icon: 'none' })
      }
    })
  },

  createDrawRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    const nick = (wx.getStorageSync('draw_nick') || '房主').toString()
      .trim()
      .slice(0, 12) || '房主'
    wx.setStorageSync('draw_nick', nick)
    wx.showLoading({ title: '建房' })
    callDraw(
      { action: 'create', nickName: nick },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '未返回组号，请稍后再试', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令告诉朋友。至少 2 人可开始；组长设轮数/词类后开画。',
            confirmText: '进入',
            showCancel: false,
            success: (m) => {
              if (m.confirm) {
                this.goDrawGuess(cfg)
              }
            }
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  goDrawGuess (cfg) {
    if (!((cfg && cfg.roomId) || '')) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const u = '/pages/draw-guess/draw-guess?roomId=' +
      encodeURIComponent(String((cfg && cfg.roomId) || '')) +
      '&roomCode=' + encodeURIComponent(String((cfg && cfg.roomCode) || ''))
    wx.navigateTo({ url: u, fail: (e) => { wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' }) } })
  },

  createDrinkRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    const nick = (wx.getStorageSync('drink_nick') || '房主')
      .toString()
      .trim()
      .slice(0, 12) || '房主'
    wx.setStorageSync('drink_nick', nick)
    wx.showLoading({ title: '建房' })
    callDrink(
      { action: 'create', nickName: nick },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '未返回组号，请检查 drinkRoomService 是否已部署', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令给同桌；至少 2 人可开始。组长负责开始、投票与趣味小任务。',
            confirmText: '进入',
            showCancel: false,
            success: (m) => {
              if (m.confirm) {
                this.goDrinkParty(cfg)
              }
            }
          })
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },
  goDrinkParty (cfg) {
    if (!((cfg && cfg.roomId) || '')) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const u = '/pages/drink-party/drink-party?roomId=' +
      encodeURIComponent(String((cfg && cfg.roomId) || '')) +
      '&roomCode=' + encodeURIComponent(String((cfg && cfg.roomCode) || ''))
    wx.navigateTo({ url: u, fail: (e) => { wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' }) } })
  },

  goUcV2(cfg) {
    const c = Object.assign(this.getConfig(), { mode: 'v2' }, cfg || {})
    const u = `/pages/undercover/undercover?title=${encodeURIComponent(
      this.data.title
    )}&config=${encodeURIComponent(JSON.stringify(c))}`
    if (u.length > 2000) {
      wx.showToast({ title: '进组地址过长，请重试', icon: 'none' })
      return
    }
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进聚会组失败', icon: 'none' })
      }
    })
  },

  goGame (extra) {
    if (this.data.screen === 'werewolf') {
      this.goWerewolf(extra || {})
      return
    }
    if (this.data.screen === 'undercover') {
      this.goUcV2(extra || {})
      return
    }
    if (this.data.screen === 'songGuess') {
      this.goSongGuess(extra || {})
      return
    }
    if (this.data.screen === 'drawGuess') {
      this.goDrawGuess(extra || {})
      return
    }
    if (this.data.screen === 'drinkParty') {
      this.goDrinkParty(extra || {})
      return
    }
    const page = 'play'
    const config = Object.assign({}, this.getConfig(), extra || {})
    wx.navigateTo({
      url: `/pages/${page}/${page}?title=${encodeURIComponent(this.data.title)}&config=${encodeURIComponent(JSON.stringify(config))}`
    })
  }
})
