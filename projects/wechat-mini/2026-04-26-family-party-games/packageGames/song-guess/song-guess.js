const { callMusic, ensure } = require('../../utils/musicRoomCloud')
const { withJoinProfile } = require('../../utils/userProfile')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../utils/roomUi')
const { patchLobbyUi } = require('../utils/roomMemberUi')
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
  showShareGuide,
  openAiShareModal
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { runAi, SYSTEM_MUSIC_HOST } = require('../utils/aiHelper')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const { stepIndex, vibrateBoundary } = require('../../utils/listStepper')
const { joinRoomWithUi, enterCloudRoomOnLoad } = require('../utils/roomJoin')
const {
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const lobbyReady = require('../utils/roomLobbyReady')
const { mergePublicPlayers, stopLobbyPoll } = require('../utils/roomSync')
const { watchDocument, stopDevtoolsPoll, markRoomDbWatch } = require('../../utils/cloudRealtime')

const ROUND_STEP_HINT = '可选 5 / 10 / 15 题'

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
    roundNum: 0,
    hasRoundHits: false,
    showLog: false,
    inputAnswer: '',
    roundLabels: ['5 题', '10 题', '15 题'],
    roundIndex: 0,
    roundStepHint: ROUND_STEP_HINT,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    playerProgressPct: 0,
    canStart: false,
    aiBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {},
    showUserInfoModal: false,
    lobbySelfReady: false,
    inWaiting: false
  },

  _w: null,
  _roomPollTimer: null,

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
    if (roomId && this.data.joinCode.length === 6) {
      enterCloudRoomOnLoad(this, {
        roomId,
        roomCode: this.data.joinCode,
        callService: callMusic,
        silentJoinToast: true,
        onReady: (id, jr) => {
          if (jr && jr.myOpenId) {
            this._storeMyOpenId(jr.myOpenId)
          }
          this.afterHasRoomId(id, { skipProfileSync: true })
        }
      })
    } else if (roomId) {
      this.afterHasRoomId(roomId)
    }
  },

  onUnload () {
    onRoomLeft(this)
    this.stopWatch()
    stopInRoomPoll(this)
    stopLobbyPoll(this)
  },

  onHide () {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
  },

  onShow () {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.roomId) {
      resumeInRoomPollOnShow(this, this._refreshRoomState)
      this._refreshRoomState()
    }
  },
  onShareAppMessage () {
    return handleShareAppMessage(this, 'music', this._shareCtx())
  },
  onShareTimeline () {
    return handleShareTimeline(this, 'music', this._shareCtx())
  },
  _lobbyReadyCtx () {
    return {
      callService: callMusic,
      roomId: this.data.roomId,
      roomCode: (this.data.state && this.data.state.roomCode) || this.data.roomCode,
      onSynced: () => this._refreshRoomState()
    }
  },
  onLobbyReadyTap () {
    lobbyReady.bindLobbyReadyTap(this, this._lobbyReadyCtx())
  },
  onLobbyUserInfoSuccess () {
    lobbyReady.onLobbyUserInfoSuccess(this)
  },
  onLobbyUserInfoCancel () {
    lobbyReady.onLobbyUserInfoCancel(this)
  },
  onCloseAiShareModal () {
    closeAiShareModal(this)
  },
  onAiShareTimeline () {
    closeAiShareModal(this)
    showShareGuide()
  },
  onCopyRoomCode () {
    const c = this.data.roomCode || (this.data.state && this.data.state.roomCode)
    copyRoomCodeToClipboard(c)
  },
  _storeMyOpenId (oid) {
    const o = String(oid || '').trim()
    if (!o) {
      return
    }
    try {
      wx.setStorageSync('music_my_open_id', o)
    } catch (e) {}
  },
  _loadStoredOpenId () {
    try {
      return String(wx.getStorageSync('music_my_open_id') || '').trim()
    } catch (e) {
      return ''
    }
  },
  _patchView (raw, stateSnap) {
    const v = Object.assign({}, raw || {})
    const a = v.hostPlayAliases
    v.hostPlayAliasesString = a && a.length ? a.join('、') : ''
    const st = stateSnap || this.data.state || {}
    const patch = { view: v }
    patchLobbyUi(
      patch,
      {
        state: st,
        view: v,
        players: mergePublicPlayers(st.publicPlayers, v.publicPlayers),
        phase: st.status || v.roomStatus || 'waiting',
        minPlayers: 2,
        maxPlayers: 0,
        isHost: v.isHost,
        myOpenId: v.myOpenId || ''
      },
      this
    )
    this.setData(patch)
  },
  _applySyncResult (r) {
    const res = r || {}
    if (res.errMsg) {
      console.warn('[music syncState]', res.errMsg)
      return
    }
    if (
      !retrySyncIfNotInRoom(this, res, this._refreshRoomState, {
        callService: callMusic
      })
    ) {
      return
    }
    if (res.myOpenId) {
      this._storeMyOpenId(res.myOpenId)
    }
    if (res.state) {
      this.applyState(res.state)
      if (res.view) {
        this._patchView(res.view, res.state)
      }
    } else if (res.view) {
      this._patchView(res.view)
    }
  },
  _refreshRoomState () {
    const id = this.data.roomId
    if (!id || !wx.cloud || !ensure()) {
      return
    }
    if (!this._w) {
      this.startWatch(String(id))
    }
    callMusic(
      { action: 'syncState', roomId: id },
      {
        silent: true,
        onOk: (res) => {
          this._applySyncResult((res && res.result) || {})
        },
        onError: () => {
          refreshCloudDoc('music_gameState', id).then((d) => {
            if (d) {
              this.applyState(d)
            }
            this.loadView()
          })
        }
      }
    )
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

  onRoundDecrease () {
    const r = stepIndex(this.data.roundIndex, -1, ROUNDS.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData({ roundIndex: r.index }, () => {
      this._saveRounds()
    })
  },
  onRoundIncrease () {
    const r = stepIndex(this.data.roundIndex, 1, ROUNDS.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData({ roundIndex: r.index }, () => {
      this._saveRounds()
    })
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
      withJoinProfile({ action: 'create', nickName: nick }),
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
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
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
    joinRoomWithUi(
      callMusic,
      { roomCode: code, nickName: nick },
      {
        onOk: (r) => {
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          this.setData({ roomId: String(r.roomId), roomCode: code, joinCode: code })
          this.afterHasRoomId(String(r.roomId), { skipProfileSync: true })
        }
      }
    )
  },

  onAiUnlockTap () {
    openAiShareModal(this)
  },
  _saveRounds () {
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
    callMusic(
      { action: 'setRounds', roomId: this.data.roomId, totalRounds: n },
      {
        onOk: () => {
          wx.showToast({ title: '已保存', icon: 'none' })
          this.loadView()
        },
        onError: () => {
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
      players: st.publicPlayers || [],
      hostOpenId: st.hostOpenId || v.hostOpenId || '',
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
        this._refreshRoomState()
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
          this._refreshRoomState()
        },
        onError: () => {
          wx.showToast({ title: '操作失败', icon: 'none' })
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
    if (!this.data.roomId) {
      return
    }
    callMusic(
      { action: 'submitAnswer', roomId: this.data.roomId, answer: ans },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            this._refreshRoomState()
            return
          }
          if (r.hostNoGuess) {
            wx.showToast({ title: '主持本轮不可抢答', icon: 'none' })
          } else if (r.wrong) {
            wx.showToast({ title: '再想想', icon: 'none' })
          } else if (r.already) {
            wx.showToast({ title: '本首已答过', icon: 'none' })
          } else if (r.ok) {
            const pts = r.points | 0
            wx.showToast({ title: '对 +' + pts, icon: 'none' })
            this.setData({ inputAnswer: '' })
          }
          this._refreshRoomState()
        },
        onError: () => {
          wx.showToast({ title: '提交失败，请重试', icon: 'none' })
        }
      }
    )
  },

  afterHasRoomId (roomId, opts) {
    this.setData({ roomId: String(roomId) })
    onRoomEntered(this, String(roomId), 'music')
    this.startWatch(String(roomId))
    ensureInRoomPoll(this, this._refreshRoomState)
    this._refreshRoomState()
    if (!(opts && opts.skipProfileSync)) {
      this._syncMyProfileToRoom()
    }
  },

  /** 进房后补同步头像（静默，不阻塞 UI） */
  _syncMyProfileToRoom () {
    const code = String(this.data.roomCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (!code || !this.data.roomId) {
      return
    }
    callMusic(
      withJoinProfile({ action: 'join', roomCode: code }),
      {
        silent: true,
        onOk: () => {
          this._refreshRoomState()
        },
        onError: () => {}
      }
    )
  },

  startWatch (roomId) {
    this.stopWatch()
    if (!wx.cloud || !ensure()) {
      return
    }
    const db = wx.cloud.database()
    const rid = String(roomId)
    const onCh = (s) => {
      const d = s && (s.data != null ? s.data : s.doc)
      if (d) {
        this.applyState(d)
      }
    }
    this._w = watchDocument(this, {
      db,
      collection: 'music_gameState',
      docId: rid,
      onChange: onCh,
      onError: (e) => {
        console.error('music watch', e)
      },
      pollTimerKey: '_devtoolsPollMusic',
      pollFn: () => {
        if (this.data.roomId) {
          this._refreshRoomState()
        }
      },
      intervalMs: 2500
    })
  },

  stopWatch () {
    stopDevtoolsPoll(this, '_devtoolsPollMusic')
    if (this._w) {
      this._w.close()
      this._w = null
    }
    markRoomDbWatch(this, false)
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
    const prev = this.data.state || {}
    const patch = {
      state: d,
      roomCode: d.roomCode || this.data.roomCode,
      roundIndex,
      roundNum,
      hasRoundHits: rh.length > 0,
      showLog: !!(d.publicLog && d.publicLog.length)
    }
    if ((d.playToken | 0) !== (prev.playToken | 0) || d.currentIndex !== prev.currentIndex) {
      patch.inputAnswer = ''
    }
    patchLobbyUi(patch, {
      state: d,
      view: v,
      players: d.publicPlayers || [],
      phase: d.status || 'waiting',
      minPlayers: 2,
      maxPlayers: 0,
      isHost: v.isHost,
      myOpenId: (v && v.myOpenId) || '',
      hostOpenId: d.hostOpenId || ''
    }, this)
    const roundHostOid = d.roundHostOpenId || ''
    if (
      roundHostOid &&
      d.status === 'playing' &&
      d.phase === 'round_playing' &&
      patch.displayPlayers &&
      patch.displayPlayers.length
    ) {
      patch.displayPlayers = patch.displayPlayers.map((p) => {
        if (p.openId !== roundHostOid) {
          return p
        }
        const scorePart = p.score != null ? p.score + ' 分 · ' : ''
        return Object.assign({}, p, {
          readyLabel: scorePart + '组长主持'
        })
      })
    }
    this.setData(patch)
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
    this._refreshRoomState()
  }
})
