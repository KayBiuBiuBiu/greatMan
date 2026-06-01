const { isDrawGuessEnabled, isHomeGameEnabled, isWerewolfEnabled } = require('../../data/feature-flags')
const { callRoomService } = require('../../utils/roomCloud')
const { withJoinProfile } = require('../../utils/userProfile')
const { callWerewolfService } = require('../../utils/werewolfCloud')
const { callUndercoverService } = require('../../utils/undercoverRoomCloud')
const { callMusic } = require('../../utils/musicRoomCloud')
const { callDraw } = require('../../utils/drawRoomCloud')
const { callDrink } = require('../../utils/drinkRoomCloud')
const { callHeadband } = require('../../utils/headbandCloud')
const { callDontdoit } = require('../../utils/dontdoitCloud')
const { callMysteryReason } = require('../../utils/mysteryReasonCloud')

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
    if (title && !isHomeGameEnabled(title)) {
      wx.showToast({ title: '正在开发中', icon: 'none' })
      setTimeout(function () {
        wx.navigateBack({ delta: 1 })
      }, 400)
      return
    }
    if (screen === 'drawGuess' && !isDrawGuessEnabled()) {
      wx.showToast({ title: '你画我猜暂未开放', icon: 'none' })
      setTimeout(function () {
        wx.navigateBack({ delta: 1 })
      }, 400)
      return
    }
    if (screen === 'werewolf' && !isWerewolfEnabled()) {
      wx.showToast({ title: '身份推理暂未开放', icon: 'none' })
      setTimeout(function () {
        wx.navigateBack({ delta: 1 })
      }, 400)
      return
    }
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
            : screen === 'songGuess' ||
                screen === 'drawGuess' ||
                screen === 'drinkParty' ||
                screen === 'headband' ||
                screen === 'dontdoit'
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
        content: '请创建聚会组并把 6 位数字口令发给每人；至少 2 人可开始。组长负责开始与下一轮。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'headband') {
      wx.showModal({
        title: '贴头猜词需多机同场',
        content: '请创建聚会组并把 6 位数字口令发给每人；至少 2 人可开始。每人看自己头上是？？？，猜对自己获胜。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'dontdoit') {
      wx.showModal({
        title: '不要做挑战需多机同场',
        content: '请创建聚会组并把 6 位口令发给每人；至少 2 人可开始。自己禁止动作保密，别犯规坚持到最后。',
        showCancel: false
      })
      return
    }
    if (this.data.screen === 'mysteryReason') {
      wx.showModal({
        title: 'AI迷雾推理局需多机同场',
        content: '请创建聚会组并把 6 位口令发给同座；至少 3 人可开局。全程面对面口头推理，无打字聊天。',
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
    if (this.data.screen === 'headband') {
      this.createHeadbandRoom()
      return
    }
    if (this.data.screen === 'dontdoit') {
      this.createDontdoitRoom()
      return
    }
    if (this.data.screen === 'mysteryReason') {
      this.createMysteryReasonRoom()
      return
    }
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }

    const game = this.buildGame()
    wx.showLoading({ title: '生成口令' })
    callRoomService(
      withJoinProfile({
        action: 'create',
        selectedGame: game,
        status: 'started'
      }),
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
    callWerewolfService(
      withJoinProfile({ action: 'create' }),
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
            content: '把 6 位数字口令告诉身边亲友，他们输入后进同一聚会组。至少 6 人即可开局，进多少人就多少人。',
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
    const u = `/packageGames/werewolf/werewolf?title=${encodeURIComponent(
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
      withJoinProfile({ action: 'create' }),
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
            content: '把 6 位数字口令告诉身边亲友，他们输入后进同一聚会组。至少 3 人即可开局，进多少人就多少人。',
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
    wx.showLoading({ title: '建房' })
    callMusic(
      withJoinProfile({ action: 'create' }),
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
      '/packageGames/song-guess/song-guess?roomId=' +
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
    wx.showLoading({ title: '建房' })
    callDraw(
      withJoinProfile({ action: 'create' }),
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
    const u = '/packageGames/draw-guess/draw-guess?roomId=' +
      encodeURIComponent(String((cfg && cfg.roomId) || '')) +
      '&roomCode=' + encodeURIComponent(String((cfg && cfg.roomCode) || ''))
    wx.navigateTo({ url: u, fail: (e) => { wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' }) } })
  },

  createDrinkRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    callDrink(
      withJoinProfile({ action: 'create' }),
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
            content: '把 6 位数字口令给同桌；至少 2 人可开始。倒计时后随机一人响铃，显示喝 1～10 口。',
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
    const u = '/packageGames/drink-party/drink-party?roomId=' +
      encodeURIComponent(String((cfg && cfg.roomId) || '')) +
      '&roomCode=' + encodeURIComponent(String((cfg && cfg.roomCode) || ''))
    wx.navigateTo({ url: u, fail: (e) => { wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' }) } })
  },

  createMysteryReasonRoom() {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    callMysteryReason(
      withJoinProfile({ action: 'create', difficulty: '新手' }),
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg || !r.roomId) {
            wx.showToast({
              title: r.errMsg || '创建聚会组失败，请重试',
              icon: 'none'
            })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content:
              '把 6 位数字口令发给同座；至少 3 人才能开始。全程面对面口头推理，本机仅查看剧本与线索。',
            confirmText: '进入',
            showCancel: false,
            success: (m) => {
              if (m.confirm) this.goMysteryReason(cfg)
            }
          })
        },
        onError: () => wx.hideLoading()
      }
    )
  },

  goMysteryReason(cfg) {
    if (!((cfg && cfg.roomId) || '')) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const u =
      '/packageGames/mystery-reason/mystery-reason?config=' +
      encodeURIComponent(JSON.stringify(cfg || {}))
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进组失败', icon: 'none' })
      }
    })
  },

  createHeadbandRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    callHeadband(
      withJoinProfile({ action: 'create' }),
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (!r.roomId) {
            wx.showToast({ title: '未返回组号，请检查 headbandRoomService 是否已部署', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位数字口令给同桌；至少 2 人可开始。组长开局后每人头上显示词语（自己为？？？）。',
            confirmText: '进入',
            showCancel: false,
            success: (m) => {
              if (m.confirm) {
                this.goHeadband(cfg)
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

  goHeadband (cfg) {
    if (!((cfg && cfg.roomId) || '')) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const c = Object.assign({}, cfg || {})
    const u =
      '/packageGames/headband/headband?config=' + encodeURIComponent(JSON.stringify(c))
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' })
      }
    })
  },

  createDontdoitRoom () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showLoading({ title: '建房' })
    callDontdoit(
      withJoinProfile({ action: 'create' }),
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (!r.roomId) {
            wx.showToast({ title: '请部署 dontdoitRoomService', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          const cfg = { roomId: String(r.roomId), roomCode: code }
          wx.showModal({
            title: '聚会组口令：' + (code || '—'),
            content: '把 6 位口令给同桌；至少 2 人。开局后每人一个禁止动作（自己保密）。',
            confirmText: '进入',
            showCancel: false,
            success: (m) => {
              if (m.confirm) {
                this.goDontdoit(cfg)
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

  goDontdoit (cfg) {
    if (!((cfg && cfg.roomId) || '')) {
      wx.showToast({ title: '组号无效', icon: 'none' })
      return
    }
    const u =
      '/packageGames/dontdoit/dontdoit?config=' + encodeURIComponent(JSON.stringify(cfg || {}))
    wx.navigateTo({
      url: u,
      fail: (e) => {
        wx.showToast({ title: (e && e.errMsg) || '进房失败', icon: 'none' })
      }
    })
  },

  goUcV2(cfg) {
    const c = Object.assign(this.getConfig(), { mode: 'v2' }, cfg || {})
    const u = `/packageGames/undercover/undercover?title=${encodeURIComponent(
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
    if (this.data.screen === 'headband') {
      this.goHeadband(extra || {})
      return
    }
    if (this.data.screen === 'dontdoit') {
      this.goDontdoit(extra || {})
      return
    }
    if (this.data.screen === 'mysteryReason') {
      this.goMysteryReason(extra || {})
      return
    }
    const page = 'play'
    const config = Object.assign({}, this.getConfig(), extra || {})
    wx.navigateTo({
      url: `/packageGames/${page}/${page}?title=${encodeURIComponent(this.data.title)}&config=${encodeURIComponent(JSON.stringify(config))}`
    })
  }
})
