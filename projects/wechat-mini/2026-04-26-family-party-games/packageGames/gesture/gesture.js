const { callGesture } = require('../../utils/gestureRoomCloud')
const { enterCloudRoomOnLoad, withJoinProfile } = require('../utils/roomJoin')
const { memberCountLine, buildStartChecks, runStartAction } = require('../utils/roomUi')
const { resumeInRoomPollOnShow, ensureInRoomPoll, stopInRoomPoll } = require('../utils/inRoomCloudSync')
const { enableShareMenus, handleShareAppMessage, handleShareTimeline } = require('../../utils/shareHelper')

Page({
  data: {
    roomId: '',
    roomCode: '',
    playerCount: 0,
    isHost: false,
    displayPlayers: [],
    memberCountLine: '',
    canStart: false,

    state: null,
    view: null,
    isMePerformer: false,
    performerWord: '',
    phase: 'waiting',
    currentRound: 0,
    totalRounds: 6,
    roundDuration: 60,
    roundStartTime: 0,
    timeLeft: 0,

    guessInput: '',
    status: 'waiting',
    publicLog: [],
    publicPlayers: [],
    roundHits: [],
    revealedWord: '',

    roundIdx: 1,
    totalRoundsOptions: [5, 6, 8, 9, 10, 12],
    durationOptions: [30, 60, 90],
    durationIdx: 1,

    myScore: 0,
    opBusy: false
  },

  onLoad(opts) {
    enableShareMenus()

    // 处理来自 setup.js 的 config 参数
    if (opts.config) {
      try {
        const cfg = JSON.parse(decodeURIComponent(opts.config))
        opts.roomCode = cfg.roomCode
        opts.roomId = cfg.roomId
      } catch (e) {
        console.warn('Parse config failed:', e)
      }
    }

    enterCloudRoomOnLoad(this, {
      roomCode: opts.roomCode || '',
      roomId: opts.roomId || '',
      callService: callGesture,
      onReady: (roomId, joinRes) => {
        this.setData({ roomId })
        this._refreshRoomState()
      }
    })
  },

  onShow() {
    enableShareMenus()
    resumeInRoomPollOnShow(this, () => this._refreshRoomState(), 3000)
  },

  onHide() {
    stopInRoomPoll(this)
  },

  onUnload() {
    stopInRoomPoll(this)
  },

  onShareAppMessage() {
    return handleShareAppMessage(this, 'gesture', {
      roomCode: this.data.roomCode,
      roomId: this.data.roomId
    })
  },

  onShareTimeline() {
    return handleShareTimeline(this, 'gesture', {
      roomCode: this.data.roomCode
    })
  },

  doCreate() {
    const nick = this.data.nickInput || '玩家'
    if (!nick.trim()) {
      wx.showToast({ title: '请输入昵称', icon: 'none' })
      return
    }

    wx.showLoading({ title: '创建聚会组', mask: true })
    callGesture({
      action: 'create',
      nickName: nick,
      totalRounds: 6,
      roundDuration: 60,
      wordCategory: 'all'
    }, {
      onOk: (res) => {
        wx.hideLoading()
        const r = res.result || {}
        this.setData({
          roomId: r.roomId,
          roomCode: r.roomCode,
          isHost: true
        })
        this._refreshRoomState()
      },
      onError: () => {
        wx.hideLoading()
      }
    })
  },

  doJoin() {
    const code = this.data.joinCode || ''
    const nick = this.data.nickInput || '玩家'

    if (!code.trim()) {
      wx.showToast({ title: '请输入房间码', icon: 'none' })
      return
    }
    if (!nick.trim()) {
      wx.showToast({ title: '请输入昵称', icon: 'none' })
      return
    }

    wx.showLoading({ title: '加入聚会组', mask: true })
    callGesture({
      action: 'join',
      roomCode: code,
      nickName: nick
    }, {
      onOk: (res) => {
        wx.hideLoading()
        const r = res.result || {}
        this.setData({
          roomId: r.roomId,
          roomCode: r.roomCode,
          isHost: false
        })
        this._refreshRoomState()
      },
      onError: () => {
        wx.hideLoading()
      }
    })
  },

  doStart() {
    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: this.data.playerCount,
      minPlayers: 2,
      kind: 'gesture',
      players: this.data.displayPlayers
    })

    runStartAction({
      kind: 'gesture',
      localChecks: checks,
      callService: callGesture,
      payload: {
        action: 'startGame',
        roomId: this.data.roomId
      },
      onSuccess: (res) => {
        this.loadView(res.result)
      },
      onFinally: (success) => {
        this.setData({ opBusy: !success })
      }
    })
  },

  doSkipWord() {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })

    callGesture({
      action: 'skipWord',
      roomId: this.data.roomId
    }, {
      onOk: () => {
        this._refreshRoomState()
      },
      onError: () => {
        this.setData({ opBusy: false })
      }
    })
  },

  doReveal() {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })

    callGesture({
      action: 'reveal',
      roomId: this.data.roomId
    }, {
      onOk: () => {
        this._refreshRoomState()
      },
      onError: () => {
        this.setData({ opBusy: false })
      }
    })
  },

  doNextRound() {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })

    callGesture({
      action: 'nextRound',
      roomId: this.data.roomId
    }, {
      onOk: (res) => {
        this._refreshRoomState()
      },
      onError: () => {
        this.setData({ opBusy: false })
      }
    })
  },

  doSubmitGuess() {
    const answer = this.data.guessInput.trim()
    if (!answer) {
      wx.showToast({ title: '请输入答案', icon: 'none' })
      return
    }

    if (this.data.opBusy) return
    this.setData({ opBusy: true, guessInput: '' })

    callGesture({
      action: 'submitGuess',
      roomId: this.data.roomId,
      answer
    }, {
      onOk: (res) => {
        const r = res.result || {}
        if (r.ok) {
          wx.showToast({ title: `恭喜！+${r.points}分`, icon: 'success' })
          setTimeout(() => this._refreshRoomState(), 500)
        } else if (r.wrong) {
          wx.showToast({ title: '答错了', icon: 'none' })
          this.setData({ opBusy: false })
        } else {
          wx.showToast({ title: r.errMsg || '提交失败', icon: 'none' })
          this.setData({ opBusy: false })
        }
      },
      onError: () => {
        this.setData({ opBusy: false })
      }
    })
  },

  onRoundsChange(e) {
    const idx = parseInt(e.detail.value) || 0
    this.setData({ roundIdx: idx })
    const totalRounds = this.data.totalRoundsOptions[idx]

    callGesture({
      action: 'setConfig',
      roomId: this.data.roomId,
      totalRounds: totalRounds
    }, {
      silent: true,
      onOk: () => {
        this.setData({ totalRounds })
      }
    })
  },

  onDurationChange(e) {
    const idx = parseInt(e.detail.value) || 0
    this.setData({ durationIdx: idx })
    const roundDuration = this.data.durationOptions[idx]

    callGesture({
      action: 'setConfig',
      roomId: this.data.roomId,
      roundDuration: roundDuration
    }, {
      silent: true,
      onOk: () => {
        this.setData({ roundDuration })
      }
    })
  },

  _refreshRoomState() {
    ensureInRoomPoll(this, () => this._doRefresh(), 3000)
  },

  _doRefresh() {
    callGesture({
      action: 'syncState',
      roomId: this.data.roomId
    }, {
      silent: true,
      onOk: (res) => {
        const r = res.result || {}
        const state = r.state || {}
        const view = r.view || {}

        const newSig = [state.status, state.phase, state.currentRound].join('|')
        if (newSig !== this._roomSig) {
          this._roomSig = newSig
          this.applyState(state, view)
        }
      }
    })
  },

  applyState(state, view) {
    const players = state.publicPlayers || []
    const isMePerformer = view.isPerformer || false

    this.setData({
      state: state,
      view: view,
      status: state.status,
      phase: state.phase,
      currentRound: state.currentRound || 0,
      totalRounds: state.totalRounds || 6,
      roundDuration: state.roundDuration || 60,
      roundStartTime: state.roundStartTime || 0,
      isMePerformer: isMePerformer,
      performerWord: view.performerWord || '',
      displayPlayers: players,
      playerCount: players.length,
      memberCountLine: memberCountLine(players.length, 0, '至少 2 人'),
      canStart: this.data.isHost && players.length >= 2,
      publicLog: state.publicLog || [],
      publicPlayers: players,
      roundHits: state.roundHits || [],
      revealedWord: state.revealedWord || '',
      myScore: view.myScore || 0,
      roomCode: state.roomCode || this.data.roomCode
    })

    if (state.phase === 'performing') {
      this._startCountdown()
    } else {
      this._stopCountdown()
    }
  },

  _countdownTimer: null,
  _startCountdown() {
    if (this._countdownTimer) clearInterval(this._countdownTimer)

    this._countdownTimer = setInterval(() => {
      const start = this.data.roundStartTime || 0
      const duration = (this.data.roundDuration || 60) * 1000
      const elapsed = Date.now() - start
      const timeLeft = Math.max(0, Math.ceil((duration - elapsed) / 1000))

      this.setData({ timeLeft })

      if (timeLeft === 0) {
        clearInterval(this._countdownTimer)
        this._countdownTimer = null
        if (this.data.isHost) {
          this.doReveal()
        }
      }
    }, 100)
  },

  _stopCountdown() {
    if (this._countdownTimer) {
      clearInterval(this._countdownTimer)
      this._countdownTimer = null
    }
  },

  onNickInput(e) {
    this.setData({ nickInput: e.detail.value })
  },

  onCodeInput(e) {
    this.setData({ joinCode: e.detail.value })
  },

  onGuessInput(e) {
    this.setData({ guessInput: e.detail.value })
  },

  doReplay() {
    this.setData({
      roomId: '',
      roomCode: '',
      phase: 'waiting',
      currentRound: 0,
      guessInput: '',
      publicLog: [],
      roundHits: [],
      revealedWord: ''
    })
  }
})
