const { callMusic, ensure } = require('../../utils/musicRoomCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../../utils/roomUi')
const { patchMemberDisplay } = require('../../utils/roomMemberUi')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const {
  refreshAiUnlockPage,
  tryRedeemShareFromQuery,
  onPageShowUnlock,
  onPageHideUnlock,
  closeAiShareModal,
  showShareGuide
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6 } = require('../../utils/roomCopy')
const { runAi, SYSTEM_MUSIC_HOST } = require('../../utils/aiHelper')
const { onRoomEntered, onRoomLeft } = require('../../utils/partyAiRoomHooks')

const ROUNDS = [5, 10, 15]

function defaultNick () {
  return (wx.getStorageSync('music_nick') || '参与者').toString()
}

Page({
  data: {
    roomId: '',
    roomCode: '',
    nick: defaultNick(),
    joinCode: '',
    state: null,
    view: null,
    timeLeft: 0,
    roundNum: 0,
    hasRoundHits: false,
    showLog: false,
    inputAnswer: '',
    roundLabels: ['5 题', '10 题', '15 题'],
    roundIndex: 0,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    playerProgressPct: 0,
    aiPanelOpen: false,
    aiBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {}
  },

  _shareCtx () {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.state && this.data.state.roomCode)
    }
  },
  onLoad (q) {
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    const roomId = (q && q.roomId) ? String(q.roomId) : ''
    const roomCode = q && q.roomCode
      ? decodeURIComponent(String(q.roomCode))
      : ''
    const nick0 = (q && q.nick) ? decodeURIComponent(String(q.nick)) : defaultNick()
    this.setData({
      nick: nick0.slice(0, 12) || '参与者',
      roomId,
      roomCode: roomCode || '',
      joinCode: roomCode ? String(roomCode).replace(/\D/g, '').slice(0, 6) : ''
    })
    if (roomId) {
      this.afterHasRoomId(roomId)
    }
  },

  onUnload () {
    onRoomLeft(this)
    this.stopTick()
    this.stopWatch()
  },

  onHide () {
    onPageHideUnlock(this)
  },

  onShow () {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.roomId) {
      this._refreshRoomState()
    }
  },
  onShareAppMessage () {
    return handleShareAppMessage(this, 'music', this._shareCtx())
  },
  onShareTimeline () {
    return handleShareTimeline(this, 'music', this._shareCtx())
  },
  onCloseAiShareModal () {
    closeAiShareModal(this)
  },
  onAiShareTimeline () {
    closeAiShareModal(this)
    showShareGuide()
  },
  _refreshRoomState () {
    const id = this.data.roomId
    if (!id || !wx.cloud || !ensure()) {
      this.loadView()
      return
    }
    refreshCloudDoc('music_gameState', id).then((d) => {
      if (d) {
        this.applyState(d)
      }
      this.loadView()
    })
  },

  onHide () {
    this.stopTick()
  },

  onNick (e) {
    const v = (e.detail && e.detail.value) || ''
    this.setData({ nick: String(v).slice(0, 12) })
  },

  onCode (e) {
    const d = String((e.detail && e.detail.value) || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    this.setData({ joinCode: d })
  },

  onRoundChange (e) {
    const i = Number((e.detail && e.detail.value) | 0)
    this.setData({ roundIndex: i >= 0 && i < ROUNDS.length ? i : 0 }, () => {
      this._saveRounds(false)
    })
  },
  onRoundStep (e) {
    const delta = Number((e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.delta) | 0)
    const cur = this.data.roundIndex | 0
    const next = Math.max(0, Math.min(ROUNDS.length - 1, cur + delta))
    if (next === cur) {
      return
    }
    this.setData({ roundIndex: next }, () => {
      this._saveRounds(false)
    })
  },
  toggleAiPanel () {
    this.setData({ aiPanelOpen: !this.data.aiPanelOpen })
  },

  onInputAns (e) {
    this.setData({ inputAnswer: (e.detail && e.detail.value) || '' })
  },

  doCreate () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    if (!ensure()) {
      return
    }
    const nick = (this.data.nick || '参与者').trim().slice(0, 12) || '参与者'
    wx.setStorageSync('music_nick', nick)
    wx.showLoading({ title: '创建中' })
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
            wx.showToast({ title: '未返回房号', icon: 'none' })
            return
          }
          const code = (r.roomCode || '').toString()
          this.setData({
            roomId: String(r.roomId),
            roomCode: code,
            joinCode: code
          })
          this.afterHasRoomId(String(r.roomId))
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  doJoin () {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    if (!ensure()) {
      return
    }
    const code = String(this.data.joinCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (code.length !== 6) {
      wx.showToast({ title: TOAST_ROOM_CODE_6, icon: 'none' })
      return
    }
    const nick = (this.data.nick || '参与者').trim().slice(0, 12) || '参与者'
    wx.setStorageSync('music_nick', nick)
    wx.showLoading({ title: '进组' })
    callMusic(
      { action: 'join', roomCode: code, nickName: nick },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          this.setData({ roomId: String(r.roomId), roomCode: code })
          this.afterHasRoomId(String(r.roomId))
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  _saveRounds (silent) {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const st = this.data.state || {}
    if (st.status !== 'waiting') {
      return
    }
    const n = ROUNDS[this.data.roundIndex | 0] || 5
    if (this._lastSavedRounds === n) {
      return
    }
    this._lastSavedRounds = n
    if (!silent) {
      wx.showLoading({ title: '保存题数', mask: true })
    }
    callMusic(
      { action: 'setRounds', roomId: this.data.roomId, totalRounds: n },
      {
        onOk: () => {
          if (!silent) {
            wx.hideLoading()
          }
          this.loadView()
        },
        onError: () => {
          if (!silent) {
            wx.hideLoading()
          }
          this._lastSavedRounds = null
        }
      }
    )
  },

  doStart () {
    const st = this.data.state || {}
    const n = (st.publicPlayers && st.publicPlayers.length) || 0
    const v = this.data.view || {}
    const ctx = { playerCount: n }
    const checks = buildStartChecks({
      isHost: v.isHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'music',
      ctx,
      startVerb: '开始互动'
    })
    runStartAction({
      kind: 'music',
      ctx,
      localChecks: checks,
      callService: callMusic,
      payload: { action: 'startGame', roomId: this.data.roomId },
      loadingTitle: '开始互动',
      onSuccess: () => {
        this.loadView()
      }
    })
  },

  doNext () {
    callMusic(
      { action: 'nextSong', roomId: this.data.roomId },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.over) {
            wx.showToast({ title: '已全部结束', icon: 'none' })
          }
          this.loadView()
        }
      }
    )
  },

  doSubmit () {
    const ans = (this.data.inputAnswer || '').trim()
    if (!ans) {
      wx.showToast({ title: '请填写歌名', icon: 'none' })
      return
    }
    callMusic(
      { action: 'submitAnswer', roomId: this.data.roomId, answer: ans },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.hostNoGuess) {
            wx.showToast({ title: '主持本轮不可抢答', icon: 'none' })
          } else if (r.late) {
            wx.showToast({ title: '已超时', icon: 'none' })
          } else if (r.wrong) {
            wx.showToast({ title: '再想想', icon: 'none' })
          } else if (r.already) {
            wx.showToast({ title: '本首已答过', icon: 'none' })
          } else if (r.ok) {
            const pts = r.points | 0
            wx.showToast({ title: '对 +' + pts, icon: 'none' })
            this.setData({ inputAnswer: '' })
          }
          this.loadView()
        }
      }
    )
  },

  afterHasRoomId (roomId) {
    this.setData({ roomId: String(roomId) })
    onRoomEntered(this, String(roomId), 'music')
    this.startWatch(String(roomId))
    if (wx.cloud && ensure()) {
      const db = wx.cloud.database()
      db
        .collection('music_gameState')
        .doc(String(roomId))
        .get()
        .then((g) => {
          if (g.data) {
            this.applyState(g.data)
          }
        })
        .catch(() => {})
    }
    this.loadView()
  },

  startWatch (roomId) {
    this.stopWatch()
    if (!wx.cloud || !ensure()) {
      return
    }
    const db = wx.cloud.database()
    this._w = db
      .collection('music_gameState')
      .doc(String(roomId))
      .watch({
        onChange: (s) => {
          const d = s && (s.data != null ? s.data : s.doc)
          if (d) {
            this.applyState(d)
            this.loadView()
          }
        },
        onError: (e) => {
          console.error('music watch', e)
        }
      })
  },

  stopWatch () {
    if (this._w) {
      this._w.close()
      this._w = null
    }
  },

  applyState (d) {
    const total = d.totalRounds | 0
    const tr = ROUNDS.indexOf(total)
    const roundIndex = tr >= 0 ? tr : 0
    const cix = typeof d.currentIndex === 'number' ? d.currentIndex : -1
    const roundNum = cix >= 0 ? cix + 1 : 0
    const rh = d.roundHits || []
    const pn = (d.publicPlayers && d.publicPlayers.length) || 0
    const v = this.data.view || {}
    const patch = {
      state: d,
      roomCode: d.roomCode || this.data.roomCode,
      roundIndex,
      roundNum,
      hasRoundHits: rh.length > 0,
      showLog: !!(d.publicLog && d.publicLog.length),
      memberCountLine: memberCountLine(pn, 0, '建议至少 2 人')
    }
    patchMemberDisplay(patch, {
      players: d.publicPlayers || [],
      phase: d.status === 'waiting' ? 'waiting' : 'playing',
      maxPlayers: 0,
      isHost: v.isHost,
      fallbackNeed: 2
    })
    this.setData(patch)
    this.syncTimeLeft(d)
    this.maybeStartTick(d)
  },

  syncTimeLeft (d) {
    if (!d || d.status !== 'playing' || d.phase !== 'round_playing' || !d.roundStartTime) {
      this.setData({ timeLeft: 0 })
      return
    }
    const dur = (d.roundDuration | 0) || 30
    const left = Math.max(0, dur * 1000 - (Date.now() - (d.roundStartTime | 0)))
    this.setData({ timeLeft: Math.ceil(left / 1000) })
  },

  /** 前端倒计时，与云 roundStartTime 对齐 */
  maybeStartTick (d) {
    this.stopTick()
    if (!d || d.status !== 'playing' || d.phase !== 'round_playing' || !d.roundStartTime) {
      return
    }
    this._tick = setInterval(() => {
      const st = this.data.state
      if (!st || st.status !== 'playing' || st.phase !== 'round_playing' || !st.roundStartTime) {
        this.stopTick()
        return
      }
      this.syncTimeLeft(st)
    }, 400)
  },

  stopTick () {
    if (this._tick) {
      clearInterval(this._tick)
      this._tick = null
    }
  },

  doAiHostTip () {
    const st = this.data.state || {}
    const host = st.roundHostNickName || '本轮主持'
    runAi(this, {
      cacheTag: 'music-host',
      roomId: this.data.roomId,
      round: (this.data.state && this.data.state.currentIndex) | 0,
      system: SYSTEM_MUSIC_HOST,
      resultTitle: 'AI 主持词',
      postProcess: { maxLen: 40 },
      buildPrompt: () => '疯狂猜歌聚会，本轮主持：' + host + '，本机外放。'
    })
  },
  loadView () {
    const { roomId } = this.data
    if (!roomId) {
      return
    }
    callMusic(
      { action: 'getView', roomId },
      {
        silent: true,
        onOk: (res) => {
          const raw = (res && res.result) || {}
          const v = Object.assign({}, raw)
          const a = v.hostPlayAliases
          v.hostPlayAliasesString =
            a && a.length ? a.join('、') : ''
          const st = this.data.state || {}
          const patch = { view: v }
          const stStatus = st.status || v.roomStatus
          patchMemberDisplay(patch, {
            players: st.publicPlayers || v.publicPlayers || [],
            phase: stStatus === 'waiting' ? 'waiting' : 'playing',
            maxPlayers: 0,
            isHost: v.isHost,
            fallbackNeed: 2
          })
          this.setData(patch)
        },
        onError: () => {}
      }
    )
  }
})
