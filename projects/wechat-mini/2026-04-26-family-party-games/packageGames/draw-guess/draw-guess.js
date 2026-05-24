const { isDrawGuessEnabled } = require('../../data/feature-flags')
const { callDraw, ensure } = require('../../utils/drawRoomCloud')
const { withJoinProfile } = require('../../utils/userProfile')
const { joinRoomWithUi, enterCloudRoomOnLoad } = require('../utils/roomJoin')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../utils/roomUi')
const { patchLobbyUi } = require('../utils/roomMemberUi')
const { stepIndex, vibrateBoundary } = require('../../utils/listStepper')
const AI_DIFF_LABELS = ['简单', '中等', '困难']
const WORD_SOURCE_OPTIONS = ['系统词库', 'AI 题目']
const WORD_SOURCE_VALUES = ['system', 'ai']

function settingsDisplayFromPage(data) {
  const d = data || {}
  const roundIdx = d.roundIdx | 0
  const catIdx = d.catIdx | 0
  const ws = d.wordSource || 'system'
  let wordSourceIdx = WORD_SOURCE_VALUES.indexOf(ws)
  if (wordSourceIdx < 0) {
    wordSourceIdx = 0
  }
  return {
    rounds: ROUNDS[roundIdx] || 6,
    wordSourceIdx,
    wordSourceLabel: WORD_SOURCE_OPTIONS[wordSourceIdx] || WORD_SOURCE_OPTIONS[0],
    currentCategoryName:
      (CAT_ARR[catIdx] && CAT_ARR[catIdx].name) || CAT_ARR[0].name
  }
}
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const {
  storeMyOpenId,
  loadStoredOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const lobbyReady = require('../utils/roomLobbyReady')
const DRAW_OPENID_KEY = 'draw_my_open_id'
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
const {
  watchDocument,
  stopDevtoolsPoll,
  markRoomDbWatch
} = require('../../utils/cloudRealtime')
const {
  mergePublicPlayers,
  syncLobbyPollByPhase,
  stopLobbyPoll
} = require('../utils/roomSync')
const {
  drawStrokeOnCtx,
  clampPt,
  parseCanvasData,
  DRAW_CANVAS_W,
  DRAW_CANVAS_H
} = require('../utils/drawCanvasSync')

function drawLog (tag, extra) {
  try {
    const cfg = require('../../cloud-env.js')
    if (cfg && cfg.debugCloudLog) {
      console.log('[draw-guess]', tag, extra || '')
    }
  } catch (e) {
    console.log('[draw-guess]', tag, extra || '')
  }
}
const {
  runAi,
  validateDrawWord,
  showAiModal,
  SYSTEM_DRAW_WORD
} = require('../utils/aiHelper')
const { CATS: CW_CATS } = require('../data/draw-words')
const ROUNDS = [5, 6, 8, 9, 10, 12]
const ROUND_STEP_HINT = '可选 ' + ROUNDS.join(' / ') + ' 轮'
const CAT_ARR = (CW_CATS && CW_CATS.length)
  ? CW_CATS
  : [{ id: 'all', name: '随机（全部分类）' }]

function defNick () {
  return (wx.getStorageSync('draw_nick') || '参与者').toString()
}

Page({
  data: {
    roomId: '',
    roomCode: '',
    nick: defNick(),
    joinCode: '',
    state: null,
    view: null,
    timeLeft: 0,
    roundOptions: ROUNDS,
    roundStepHint: ROUND_STEP_HINT,
    roundIdx: 1,
    rounds: 6,
    catNames: CAT_ARR.map((c) => c.name),
    catIdx: 0,
    currentCategoryName: CAT_ARR[0].name,
    wordSourceOptions: WORD_SOURCE_OPTIONS,
    wordSourceIdx: 0,
    wordSourceLabel: WORD_SOURCE_OPTIONS[0],
    guessInput: '',
    lineW: 4,
    remoteCanvasSrc: '',
    isMeDrawer: false,
    painterWordSafe: '',
    drawRoleHint: '',
    isDrawingMode: false,
    drawFocus: false,
    inDrawingPhase: false,
    showCanvasBoard: false,
    manualExitDraw: false,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    playerProgressPct: 0,
    inWaiting: false,
    canStart: false,
    wordSource: 'system',
    aiDiffIdx: 1,
    aiDiffLabels: AI_DIFF_LABELS,
    aiBusy: false,
    aiPendingWord: '',
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    showUserInfoModal: false,
    lobbySelfReady: false,
    shareCopy: {}
  },
  _cvs: null,
  _ctx: null,
  _last: null,
  _color: '#111111',
  _uploadTimer: null,
  _ticker: null,
  _cseq: 0,
  _myOpenId: '',
  _roomSig: '',
  _viewLoadTimer: null,
  _touching: false,
  _canvasRect: null,
  _allPaths: [],
  _curPath: null,
  _canvasPollTimer: null,
  _canvasDataSig: '',
  _replayedSeq: -1,
  _manualExitDraw: false,
  _autoEnteringDraw: false,
  /** 房间结构变化（不含 canvasDataVer，避免抬笔上传误触发退出绘画） */
  _roomStateSig (d) {
    if (!d) {
      return ''
    }
    return [
      d.status,
      d.phase,
      d.currentRound,
      d.currentDrawerOpenId,
      d.canvasSeq
    ].join('|')
  },
  _computeDrawRole (state, view) {
    const st = state || {}
    const v = view || {}
    const my = String(v.myOpenId || this._myOpenId || '').trim()
    const drawer = String(st.currentDrawerOpenId || '').trim()
    const painting = st.status === 'playing' && st.phase === 'drawing'
    const isMeDrawer = !!(my && drawer && my === drawer)
    const inDrawingPhase = painting
    let painterWordSafe = ''
    if (isMeDrawer && inDrawingPhase && v.painterWord) {
      painterWordSafe = String(v.painterWord)
    }
    let drawRoleHint = ''
    if (inDrawingPhase && drawer) {
      drawRoleHint = isMeDrawer
        ? '本轮由你绘画（仅你可见题目）'
        : '本轮由「' + (st.currentDrawerNick || '他人') + '」绘画，你来猜词'
    }
    const showCanvasBoard = inDrawingPhase && !isMeDrawer
    return {
      isMeDrawer,
      painterWordSafe,
      drawRoleHint,
      inDrawingPhase,
      showCanvasBoard
    }
  },
  _isDrawFocus () {
    return !!(this.data.isMeDrawer && this.data.isDrawingMode)
  },
  _syncDrawFocusFlag () {
    const f = this._isDrawFocus()
    if (this.data.drawFocus !== f) {
      this.setData({ drawFocus: f })
    }
  },
  _shouldInitCanvas () {
    const s = this.data.state
    if (!s) {
      return false
    }
    if (this.data.isMeDrawer) {
      return this._isDrawFocus()
    }
    return !!(this.data.showCanvasBoard && this.data.inDrawingPhase)
  },
  _canvasWrapSelector () {
    return this._isDrawFocus() ? '#drawFocusWrap' : '#drawWrapBox'
  },
  getAllPaths () {
    const list = (this._allPaths || []).slice()
    if (this._curPath && this._curPath.pts && this._curPath.pts.length >= 2) {
      list.push(this._curPath)
    }
    return list
  },
  saveCanvasToCloud () {
    if (!this.data.isMeDrawer || !this.data.roomId) {
      return
    }
    const canvasData = this.getAllPaths()
    drawLog('saveCanvasToCloud', { paths: canvasData.length })
    callDraw(
      {
        action: 'updateCanvas',
        roomId: this.data.roomId,
        canvasData: canvasData
      },
      { silent: true }
    )
  },
  /** 已停用增量 appendStroke；笔画在抬笔时 saveCanvasToCloud 全量同步 */
  _pushStrokeToCloud () {},
  onManualSync () {
    if (!this.data.isMeDrawer || !this.data.isDrawingMode) {
      return
    }
    this.saveCanvasToCloud()
    wx.showToast({ title: '已同步', icon: 'success' })
  },
  _onGameStateCanvas (data) {
    if (!data) {
      return
    }
    const sig = [data.canvasDataVer, data.canvasSeq].join('|')
    this._canvasDataSig = sig
    let strokes = []
    try {
      strokes = parseCanvasData(data.canvasData)
    } catch (e) {
      console.error('[draw-guess] parse canvasData failed', e)
      strokes = []
    }
    const seq = data.canvasSeq | 0
    if (this.data.isMeDrawer && this.data.isDrawingMode) {
      return
    }
    this.redrawCanvas(strokes, seq)
  },
  onCanvasDataChange (paths, seq) {
    if (!paths || !paths.length) {
      if ((seq | 0) !== (this._replayedSeq | 0)) {
        this.redrawCanvas([], seq)
      }
      return
    }
    if (this.data.isMeDrawer && this.data.isDrawingMode) {
      return
    }
    this.redrawCanvas(paths, seq)
  },
  redrawCanvas (paths, seq) {
    const ctx = this._ctx
    if (!ctx) {
      this._pendingCanvasPaths = paths || []
      this._pendingCanvasSeq = seq | 0
      if (this._shouldInitCanvas()) {
        this.scheduleInitCanvas()
      }
      return
    }
    const list = paths || []
    const s = seq | 0
    this.clearLocalCanvas()
    this._replayedSeq = s
    const bounds = { w: this._w || DRAW_CANVAS_W, h: this._h || DRAW_CANVAS_H }
    for (let i = 0; i < list.length; i += 1) {
      drawStrokeOnCtx(ctx, list[i], bounds)
    }
    drawLog('redrawCanvas', { paths: list.length, seq: s })
  },
  startCanvasPoll () {
    this.stopCanvasPoll()
    if (!this.data.roomId) {
      return
    }
    const page = this
    this._canvasPollTimer = setInterval(function () {
      if (!page.data.inDrawingPhase) {
        return
      }
      page._refreshRoomState()
    }, 1000)
  },
  stopCanvasPoll () {
    if (this._canvasPollTimer) {
      clearInterval(this._canvasPollTimer)
      this._canvasPollTimer = null
    }
  },
  _exitDrawingMode (silent) {
    if (this._uploadTimer) {
      clearInterval(this._uploadTimer)
      this._uploadTimer = null
    }
    this._touching = false
    this._last = null
    if (this.data.isDrawingMode) {
      if (!silent) {
        this.saveCanvasToCloud()
      }
      this._cvs = null
      this._ctx = null
      this._canvasReadySeq = -1
      this.setData({ isDrawingMode: false, drawFocus: false })
    }
  },
  onEnterDrawingMode () {
    const s = this.data.state || {}
    const v = this.data.view || {}
    const my = String(v.myOpenId || this._myOpenId || '').trim()
    const drawer = String(s.currentDrawerOpenId || '').trim()
    const isDrawer =
      !!(my && drawer && my === drawer) || !!v.isDrawer || !!this.data.isMeDrawer
    if (!isDrawer || s.phase !== 'drawing' || s.status !== 'playing') {
      wx.showToast({ title: '你不是本轮画家', icon: 'none' })
      return
    }
    this._cvs = null
    this._ctx = null
    this._canvasReadySeq = -1
    this._manualExitDraw = false
    this.setData(
      {
        isDrawingMode: true,
        drawFocus: true,
        isMeDrawer: true,
        manualExitDraw: false
      },
      () => {
      this._syncDrawFocusFlag()
      this.scheduleInitCanvas()
      this.setupUploadLoop()
      this._refreshCanvasRect()
    })
  },
  onExitDrawingMode () {
    this._manualExitDraw = true
    this.setData({ manualExitDraw: true })
    this._exitDrawingMode(false)
    wx.showToast({ title: '已退出绘画模式', icon: 'none' })
  },
  handleTouchMove (e) {
    if (e && typeof e.preventDefault === 'function') {
      e.preventDefault()
    }
    if (!this.data.isDrawingMode) {
      return
    }
    this.touchCommon(e, false)
  },
  _refreshCanvasRect (cb) {
    if (!wx.createSelectorQuery) {
      cb && cb()
      return
    }
    wx.createSelectorQuery()
      .in(this)
      .select('#cvs2')
      .boundingClientRect()
      .exec((res) => {
        if (res && res[0]) {
          this._canvasRect = res[0]
        }
        if (cb) {
          cb()
        }
      })
  },
  _touchXY (t0) {
    const r = this._canvasRect
    if (!t0) {
      return null
    }
    if (r && t0.clientX != null && t0.clientY != null) {
      return {
        x: t0.clientX - r.left,
        y: t0.clientY - r.top
      }
    }
    if (t0.x != null && t0.y != null) {
      return { x: t0.x, y: t0.y }
    }
    return null
  },
  _tryAutoEnterDrawingMode (role, st) {
    const s = st || this.data.state || {}
    const painting = s.status === 'playing' && s.phase === 'drawing'
    const r = role || this._computeDrawRole(s, this.data.view)
    if (
      r.isMeDrawer &&
      painting &&
      !this.data.isDrawingMode &&
      !this._manualExitDraw &&
      !this._autoEnteringDraw
    ) {
      this._autoEnteringDraw = true
      this.onEnterDrawingMode()
      this._autoEnteringDraw = false
    }
  },
  /** 以 state.currentDrawerOpenId + myOpenId 为准；拿到 openId 后触发画板初始化 */
  _syncDrawRole () {
    const st = this.data.state || {}
    const v = this.data.view || {}
    if (v.myOpenId) {
      this._myOpenId = v.myOpenId
    }
    const role = this._computeDrawRole(st, v)
    const patch = role
    if (!role.isMeDrawer && this._uploadTimer) {
      clearInterval(this._uploadTimer)
      this._uploadTimer = null
    }
    const painting = st.status === 'playing' && st.phase === 'drawing'
    if (!role.isMeDrawer || !painting) {
      this._exitDrawingMode(true)
      patch.isDrawingMode = false
      patch.drawFocus = false
    } else {
      this._tryAutoEnterDrawingMode(role, st)
    }
    const changed =
      this.data.isMeDrawer !== role.isMeDrawer ||
      this.data.painterWordSafe !== role.painterWordSafe ||
      this.data.drawRoleHint !== role.drawRoleHint ||
      this.data.inDrawingPhase !== role.inDrawingPhase ||
      this.data.showCanvasBoard !== role.showCanvasBoard
    if (!changed && patch.isDrawingMode === undefined) {
      return
    }
    this.setData(patch, () => {
      this._syncDrawFocusFlag()
      if (role.showCanvasBoard || role.inDrawingPhase && this.data.isMeDrawer) {
        this.scheduleInitCanvas()
      }
    })
  },
  fetchMyOpenId () {
    if (!wx.cloud || !ensure()) {
      return
    }
    callDraw(
      { action: 'getOpenId' },
      {
        silent: true,
        onOk: (res) => {
          const o = (res && res.result && res.result.openId) || ''
          if (o) {
            this._myOpenId = o
            this._syncDrawRole()
          }
        }
      }
    )
  },
  _debouncedLoadView () {
    if (this._viewLoadTimer) {
      clearTimeout(this._viewLoadTimer)
    }
    this._viewLoadTimer = setTimeout(() => {
      this._viewLoadTimer = null
      this.loadView()
    }, 280)
  },
  _shareCtx () {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.state && this.data.state.roomCode)
    }
  },
  onLoad (q) {
    if (!isDrawGuessEnabled()) {
      wx.showToast({ title: '你画我猜暂未开放', icon: 'none' })
      setTimeout(function () {
        wx.reLaunch({ url: '/pages/index/index' })
      }, 400)
      return
    }
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    const ridx = ROUNDS.indexOf(6)
    const roundIdx = ridx >= 0 ? ridx : 0
    this.setData(
      Object.assign({ roundIdx }, settingsDisplayFromPage({ roundIdx, catIdx: 0, wordSource: 'system' }))
    )
    const roomId = (q && q.roomId) ? String(q.roomId) : ''
    const code = (q && q.roomCode) ? decodeURIComponent(String(q.roomCode)) : ''
    this.setData({
      nick: (q && q.nick) ? decodeURIComponent(String(q.nick)).slice(0, 12) : defNick(),
      roomId,
      roomCode: code,
      joinCode: code ? code.replace(/\D/g, '').slice(0, 6) : ''
    })
    if (roomId && this.data.joinCode.length === 6) {
      enterCloudRoomOnLoad(this, {
        roomId,
        roomCode: this.data.joinCode,
        callService: callDraw,
        onReady: (id) => this.afterHasRoomId(id)
      })
    } else if (roomId) {
      this.afterHasRoomId(roomId)
    }
  },
  onHide () {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
    stopLobbyPoll(this)
    this.clearTimers()
    this.stopCanvasPoll()
  },
  onUnload () {
    onRoomLeft(this)
    stopInRoomPoll(this)
    this.clearTimers()
    if (this._viewLoadTimer) {
      clearTimeout(this._viewLoadTimer)
      this._viewLoadTimer = null
    }
    this.stopCanvasPoll()
    stopLobbyPoll(this)
    this.stopWatchG()
    this.stopWatchC()
  },
  onShow () {
    enableShareMenus()
    onPageShowUnlock(this)
    refreshAiUnlockPage(this)
    if (this.data.roomId) {
      resumeInRoomPollOnShow(this, this._refreshRoomState)
      this._refreshRoomState()
      this.startCanvasPoll()
    } else {
      this.scheduleInitCanvas()
    }
  },
  onShareAppMessage () {
    return handleShareAppMessage(this, 'draw', this._shareCtx())
  },
  onShareTimeline () {
    return handleShareTimeline(this, 'draw', this._shareCtx())
  },
  _lobbyReadyCtx () {
    return {
      callService: callDraw,
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
    this._myOpenId = o
    storeMyOpenId(DRAW_OPENID_KEY, o)
  },
  _applySyncResult (r) {
    const res = r || {}
    if (res.errMsg) {
      console.warn('[draw syncState]', res.errMsg)
      return
    }
    if (
      !retrySyncIfNotInRoom(this, res, this._refreshRoomState, {
        callService: callDraw
      })
    ) {
      return
    }
    if (res.myOpenId) {
      this._storeMyOpenId(res.myOpenId)
    }
    if (res.state) {
      const d = res.state
      const roomSig = this._roomStateSig(d)
      const roomChanged = roomSig !== this._roomSig
      if (roomChanged) {
        this._roomSig = roomSig
      }
      this.applyG(d)
      this._onGameStateCanvas(d)
      if (roomChanged) {
        drawLog('roomSigChanged', { sig: roomSig })
        this._onCanvasSeqChange(d)
        this.scheduleInitCanvas()
      }
    }
    if (res.view) {
      this._patchViewFromSync(res.view)
    } else if (!res.state) {
      this._debouncedLoadView()
    }
  },
  _patchViewFromSync (v) {
    const st = this.data.state || {}
    if (v.myOpenId) {
      this._storeMyOpenId(v.myOpenId)
    }
    const patch = { view: v }
    this._patchRoomUi(patch, {
      state: st,
      view: v,
      players: mergePublicPlayers(st.publicPlayers, v.publicPlayers)
    })
    Object.assign(patch, this._computeDrawRole(st, v))
    refreshAiUnlockPage(this)
    this.setData(patch, () => {
      this.tryAutoReveal()
      this.setupTicker()
      this._tryAutoEnterDrawingMode(patch, st)
      if (patch.showCanvasBoard) {
        this.scheduleInitCanvas()
      }
    })
  },
  _refreshRoomState () {
    const id = this.data.roomId
    if (this.data.isDrawingMode && this._touching) {
      return
    }
    if (!id || !wx.cloud || !ensure()) {
      this.loadView()
      return
    }
    if (!this._wg) {
      this.startWatchG(String(id))
    }
    callDraw(
      { action: 'syncState', roomId: id },
      {
        silent: true,
        onOk: (res) => {
          this._applySyncResult((res && res.result) || {})
        },
        onError: () => {
          refreshCloudDoc('draw_gameState', id).then((d) => {
            if (d) {
              const roomSig = this._roomStateSig(d)
              const roomChanged = roomSig !== this._roomSig
              if (roomChanged) {
                this._roomSig = roomSig
              }
              this.applyG(d)
              this._onGameStateCanvas(d)
              if (roomChanged) {
                this._onCanvasSeqChange(d)
                this.scheduleInitCanvas()
              }
            }
            this._debouncedLoadView()
          })
        }
      }
    )
  },
  clearTimers () {
    if (this._ticker) {
      clearInterval(this._ticker)
      this._ticker = null
    }
    if (this._uploadTimer) {
      clearInterval(this._uploadTimer)
      this._uploadTimer = null
    }
  },
  onNick (e) {
    this.setData({ nick: String((e.detail && e.detail.value) || '').slice(0, 12) })
  },
  onCode (e) {
    this.setData({
      joinCode: String((e.detail && e.detail.value) || '')
        .replace(/\D/g, '')
        .slice(0, 6)
    })
  },
  _applySettingsDisplay (patch) {
    return Object.assign(patch || {}, settingsDisplayFromPage(Object.assign({}, this.data, patch)))
  },
  onRoundsMinus () {
    const r = stepIndex(this.data.roundIdx, -1, ROUNDS.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData(this._applySettingsDisplay({ roundIdx: r.index }), () => this._saveConfig())
  },
  onRoundsPlus () {
    const r = stepIndex(this.data.roundIdx, 1, ROUNDS.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData(this._applySettingsDisplay({ roundIdx: r.index }), () => this._saveConfig())
  },
  onWordSourceChange (e) {
    const i = Number((e.detail && e.detail.value) | 0) || 0
    const wordSource = WORD_SOURCE_VALUES[i] || 'system'
    const patch = {
      wordSourceIdx: i,
      wordSource,
      wordSourceLabel: WORD_SOURCE_OPTIONS[i] || WORD_SOURCE_OPTIONS[0]
    }
    if (wordSource === 'system') {
      patch.aiPendingWord = ''
    }
    this.setData(patch)
  },
  onCategoryChange (e) {
    const catIdx = Number((e.detail && e.detail.value) | 0) || 0
    this.setData(this._applySettingsDisplay({ catIdx }), () => this._saveConfig())
  },
  onAiGenerateWord () {
    this.doAiWord()
  },
  onAiUnlockTap () {
    openAiShareModal(this)
  },
  onGuessI (e) {
    this.setData({ guessInput: (e.detail && e.detail.value) || '' })
  },
  onLineW (e) {
    this.setData({ lineW: (e.detail && e.detail.value) | 0 || 4 })
  },
  onPickColor (e) {
    this._color = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.c) || '#111'
  },
  doCreate () {
    if (!wx.cloud) {
      wx.showToast({ title: '需开通云', icon: 'none' })
      return
    }
    if (!ensure()) {
      return
    }
    const nick = (this.data.nick || '参与者').trim().slice(0, 12) || '参与者'
    wx.setStorageSync('draw_nick', nick)
    wx.showLoading({ title: '…' })
    callDraw(
      withJoinProfile({ action: 'create', nickName: nick }),
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!r.roomId) {
            return
          }
          const c = (r.roomCode || '').toString()
          this.setData({ roomId: String(r.roomId), roomCode: c, joinCode: c })
          this.afterHasRoomId(String(r.roomId), r)
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
      wx.showToast({ title: '云环境未就绪', icon: 'none' })
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
    wx.setStorageSync('draw_nick', nick)
    joinRoomWithUi(
      callDraw,
      { roomCode: code, nickName: nick },
      {
        onOk: (r) => {
          this.setData({ roomId: String(r.roomId), roomCode: code, joinCode: code })
          this.afterHasRoomId(String(r.roomId), r)
        }
      }
    )
  },
  _patchRoomUi (patch, opts) {
    const o = opts || {}
    const st = o.state || this.data.state || {}
    const v = o.view || this.data.view || {}
    return patchLobbyUi(patch, {
      state: st,
      view: v,
      players: o.players || st.publicPlayers || [],
      phase: st.status || (v && v.roomStatus) || 'waiting',
      minPlayers: 2,
      maxPlayers: 0,
      hostOpenId: st.hostOpenId || (v && v.hostOpenId) || ''
    }, this)
  },
  _saveConfig () {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const st = this.data.state || {}
    if (st.status !== 'waiting') {
      return
    }
    const c = (CAT_ARR[this.data.catIdx | 0] && CAT_ARR[this.data.catIdx | 0].id) || 'all'
    const rounds = ROUNDS[this.data.roundIdx | 0] || 6
    const sig = rounds + '|' + c
    if (this._configSig === sig) {
      return
    }
    this._configSig = sig
    callDraw(
      {
        action: 'setConfig',
        roomId: this.data.roomId,
        totalRounds: rounds,
        wordCategory: c
      },
      {
        onOk: () => {
          wx.showToast({ title: '已保存', icon: 'none' })
        },
        onError: () => {
          this._configSig = null
        }
      }
    )
  },
  doAiWord () {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const cat = (CAT_ARR[this.data.catIdx | 0] && CAT_ARR[this.data.catIdx | 0].name) || '随机'
    const diff = AI_DIFF_LABELS[this.data.aiDiffIdx | 0] || '中等'
    const page = this
    runAi(this, {
      cacheTag: 'draw-word',
      roomId: this.data.roomId,
      round: (this.data.state && this.data.state.currentRound) | 0,
      loadingTitle: 'AI 生成题目',
      aiUnlockName: 'AI 出题',
      system: SYSTEM_DRAW_WORD,
      buildPrompt: () => '你画我猜，词库风格：' + cat + '，难度：' + diff + '。',
      onOk: (text) => {
        const v = validateDrawWord(text)
        if (!v.ok) {
          showAiModal('失败', v.err)
          return
        }
        const w = v.word
        page.setData(
          page._applySettingsDisplay({
            wordSource: 'ai',
            wordSourceIdx: 1,
            wordSourceLabel: WORD_SOURCE_OPTIONS[1],
            aiPendingWord: w
          })
        )
        wx.showToast({ title: '题目已生成', icon: 'none' })
      }
    })
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
      kind: 'draw',
      ctx,
      players: st.publicPlayers || [],
      hostOpenId: st.hostOpenId || v.hostOpenId || '',
      startVerb: '开始互动'
    })
    const page = this
    const useAi = this.data.wordSource === 'ai'
    if (useAi && !(this.data.aiPendingWord || '').trim()) {
      wx.showToast({ title: '请先生成 AI 题目', icon: 'none' })
      return
    }
    const runGameStart = () => {
      runStartAction({
        kind: 'draw',
        ctx,
        localChecks: checks,
        callService: callDraw,
        payload: { action: 'startGame', roomId: page.data.roomId },
        loadingTitle: '开始互动',
        onSuccess: () => {
          page.setData({ aiPendingWord: '' })
          page._roomSig = ''
          page._canvasDataSig = ''
          page.loadView()
          page._refreshRoomState()
        }
      })
    }
    if (useAi) {
      const w = (this.data.aiPendingWord || '').trim()
      runStartAction({
        kind: 'draw',
        ctx,
        localChecks: [],
        callService: callDraw,
        payload: { action: 'setPendingWord', roomId: page.data.roomId, word: w },
        loadingTitle: '准备题目',
        onSuccess: runGameStart,
        onFinally: (ok) => {
          if (!ok) {
            return
          }
        }
      })
      return
    }
    runGameStart()
  },
  doReveal () {
    callDraw(
      { action: 'reveal', roomId: this.data.roomId },
      { onOk: () => { this.loadView() } }
    )
  },
  doNextR () {
    callDraw(
      { action: 'nextRound', roomId: this.data.roomId },
      {
        onOk: (res) => {
          const o = (res && res.result) || {}
          if (o.over) {
            wx.showToast({ title: '本环节已结束', icon: 'none' })
          }
          this.loadView()
        }
      }
    )
  },
  doSkip () {
    callDraw(
      { action: 'skipWord', roomId: this.data.roomId },
      { onOk: () => { this.onCanvasReset(); this.loadView() } }
    )
  },
  doEndG () {
    callDraw(
      { action: 'endGame', roomId: this.data.roomId },
      { onOk: () => { this.loadView() } }
    )
  },
  doSubmitGuess () {
    const guess = (this.data.guessInput || '').trim()
    if (!guess) {
      wx.showToast({ title: '先输入答案', icon: 'none' })
      return
    }
    if (!this.data.roomId) {
      wx.showToast({ title: '未进组', icon: 'none' })
      return
    }
    const st = this.data.state || {}
    if (st.phase !== 'drawing' || st.status !== 'playing') {
      wx.showToast({ title: '当前不可猜词', icon: 'none' })
      return
    }
    if (this.data.isMeDrawer) {
      wx.showToast({ title: '绘画者不能猜', icon: 'none' })
      return
    }
    wx.showLoading({ title: '提交中', mask: true })
    callDraw(
      { action: 'submitGuess', roomId: this.data.roomId, answer: guess },
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.ok) {
            wx.showToast({ title: '猜对了 +' + (r.points | 0), icon: 'none' })
            this.setData({ guessInput: '' })
            this._refreshRoomState()
            this.loadView()
            return
          }
          if (r.drawerNoGuess) {
            wx.showToast({ title: '绘画者不能猜', icon: 'none' })
          } else if (r.wrong) {
            wx.showToast({ title: '答案不对', icon: 'none' })
          } else if (r.already) {
            wx.showToast({ title: '本轮已答过', icon: 'none' })
          } else if (r.late) {
            wx.showToast({ title: '已超时', icon: 'none' })
          } else if (r.done) {
            wx.showToast({ title: '已揭晓', icon: 'none' })
          } else if (r.err || r.errHint) {
            wx.showToast({ title: r.errHint || '题目无效', icon: 'none' })
          } else if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg).slice(0, 20), icon: 'none' })
          } else {
            wx.showToast({ title: '提交失败', icon: 'none' })
          }
          drawLog('submitGuess', r)
          this.loadView()
        },
        onError: () => {
          wx.hideLoading()
          wx.showToast({ title: '提交失败，请重试', icon: 'none' })
        }
      }
    )
  },
  afterHasRoomId (roomId, joinResult) {
    this.setData({ roomId: String(roomId) })
    onRoomEntered(this, String(roomId), 'draw')
    refreshAiUnlockPage(this)
    const stored = loadStoredOpenId(DRAW_OPENID_KEY)
    if (stored) {
      this._myOpenId = stored
    }
    const r = joinResult || {}
    if (r.myOpenId) {
      this._storeMyOpenId(r.myOpenId)
    }
    this.fetchMyOpenId()
    setTimeout(() => this.fetchMyOpenId(), 300)
    this.startWatchG(String(roomId))
    this.startWatchC(String(roomId))
    ensureInRoomPoll(this, this._refreshRoomState)
    this._refreshRoomState()
  },
  startWatchG (id) {
    this.stopWatchG()
    if (!wx.cloud || !ensure()) {
      return
    }
    const db = wx.cloud.database()
    const rid = String(id)
    const onG = (s) => {
      const d = s && (s.data != null ? s.data : s.doc)
      if (!d) {
        return
      }
      const roomSig = this._roomStateSig(d)
      const roomChanged = roomSig !== this._roomSig
      if (roomChanged) {
        this._roomSig = roomSig
        const prev = this.data.state
        if (
          this.data.isDrawingMode &&
          prev &&
          (prev.phase !== d.phase ||
            prev.status !== d.status ||
            (prev.canvasSeq | 0) !== (d.canvasSeq | 0) ||
            prev.currentDrawerOpenId !== d.currentDrawerOpenId)
        ) {
          this._exitDrawingMode(true)
        }
      }
      this.applyG(d)
      this._onGameStateCanvas(d)
      if (roomChanged) {
        this._onCanvasSeqChange(d)
        this.loadView()
        this._syncDrawRole()
        this.tryAutoReveal()
        this.scheduleInitCanvas()
      }
      this.setupTicker()
    }
    this._wg = watchDocument(this, {
      db,
      collection: 'draw_gameState',
      docId: rid,
      onChange: onG,
      pollTimerKey: '_devtoolsPollG',
      pollFn: () => {
        if (this.data.roomId) {
          this._refreshRoomState()
        }
      },
      intervalMs: 2500
    })
  },
  _onCanvasSeqChange (st) {
    if (!st) {
      return
    }
    const seq = st.canvasSeq | 0
    if (this._cseq !== seq) {
      this._cseq = seq
      this._canvasReadySeq = -1
      this._canvasDataSig = ''
      this._allPaths = []
      this._curPath = null
      this._pendingCanvasPaths = null
      this._manualExitDraw = false
      if (this.data.manualExitDraw) {
        this.setData({ manualExitDraw: false })
      }
      this.clearLocalCanvas()
    }
  },
  onCanvasReset () {
    this.clearLocalCanvas()
    this.setData({ remoteCanvasSrc: '' })
  },
  clearLocalCanvas () {
    const ctx = this._ctx
    const c = this._cvs
    if (ctx && c) {
      try {
        const w = this._w || DRAW_CANVAS_W
        const h = this._h || DRAW_CANVAS_H
        ctx.clearRect(0, 0, w, h)
      } catch (e) {}
    }
  },
  stopWatchG () {
    stopDevtoolsPoll(this, '_devtoolsPollG')
    if (this._wg) {
      this._wg.close()
      this._wg = null
    }
    markRoomDbWatch(this, false)
  },
  startWatchC (id) {
    this.stopWatchC()
    if (!wx.cloud || !ensure()) {
      return
    }
    const db = wx.cloud.database()
    const rid = String(id)
    this._wc = watchDocument(this, {
      db,
      collection: 'draw_canvas',
      docId: rid,
      onChange: () => {},
      pollTimerKey: '_devtoolsPollC',
      pollFn: () => {},
      markActive: false
    })
  },
  stopWatchC () {
    stopDevtoolsPoll(this, '_devtoolsPollC')
    if (this._wc) {
      this._wc.close()
      this._wc = null
    }
  },
  applyG (d) {
    if (this._isDrawFocus()) {
      const roomSig = this._roomStateSig(d)
      const roomChanged = roomSig !== this._roomSig
      if (roomChanged) {
        this._roomSig = roomSig
        this.setData({
          state: d,
          roomCode: d.roomCode || this.data.roomCode,
          inDrawingPhase: true,
          isMeDrawer: true,
          isDrawingMode: true,
          drawFocus: true
        })
      }
      return
    }
    const patch = this._applySettingsDisplay({
      state: d,
      roomCode: d.roomCode || this.data.roomCode
    })
    const prev = (this.data.state && this.data.state.publicPlayers) || []
    const role = this._computeDrawRole(d, this.data.view)
    this._patchRoomUi(patch, {
      state: d,
      players: mergePublicPlayers(d.publicPlayers, prev)
    })
    Object.assign(patch, role)
    if (!role.isMeDrawer || d.status !== 'playing' || d.phase !== 'drawing') {
      if (this.data.isDrawingMode) {
        patch.isDrawingMode = false
        patch.drawFocus = false
        this._exitDrawingMode(true)
      }
    }
    this.setData(patch, () => {
      this._syncDrawFocusFlag()
      this._onGameStateCanvas(d)
      if (!this.data.isMeDrawer && this.data.showCanvasBoard && d.canvasData) {
        const strokes = parseCanvasData(d.canvasData)
        this.redrawCanvas(strokes, d.canvasSeq | 0)
      }
      if (patch.inDrawingPhase) {
        this.startCanvasPoll()
        this._tryAutoEnterDrawingMode(role, d)
        if (patch.showCanvasBoard || patch.isMeDrawer) {
          this.scheduleInitCanvas()
        }
      } else {
        this.stopCanvasPoll()
      }
      syncLobbyPollByPhase(this, d.status || d.phase, this._refreshRoomState)
    })
  },
  loadView () {
    const { roomId } = this.data
    if (!roomId) {
      return
    }
    callDraw(
      { action: 'getView', roomId },
      {
        silent: true,
        onOk: (res) => {
          const v = (res && res.result) || {}
          drawLog('loadView', {
            isDrawer: v.isDrawer,
            phase: v.phase,
            myOpenId: v.myOpenId
          })
          this._patchViewFromSync(v)
        }
      }
    )
  },
  tryAutoReveal () {
    const st = this.data.state
    if (!st || st.status !== 'playing' || st.phase !== 'drawing' || !st.roundStartTime) {
      return
    }
    const d = (st.roundDuration | 0) * 1000
    if (Date.now() < (st.roundStartTime | 0) + d - 300) {
      return
    }
    callDraw(
      { action: 'reveal', roomId: this.data.roomId },
      { silent: true, onOk: () => { this.loadView() } }
    )
  },
  setupTicker () {
    this.clearTimers()
    const st = this.data.state
    if (!st || st.status !== 'playing' || st.phase !== 'drawing' || !st.roundStartTime) {
      this.setData({ timeLeft: 0 })
      if (st && st.status === 'playing' && st.phase === 'revealed') {
        this.setData({ timeLeft: 0 })
      }
      return
    }
    const d = this
    const tick = function () {
      const s = d.data.state
      if (!s || s.status !== 'playing' || s.phase !== 'drawing' || !s.roundStartTime) {
        d.setData({ timeLeft: 0 })
        return
      }
      const dur = (s.roundDuration | 0) || 60
      const el = (Date.now() - (s.roundStartTime | 0)) / 1000
      d.setData({ timeLeft: Math.max(0, Math.ceil(dur - el)) })
    }
    tick()
    this._ticker = setInterval(tick, 800)
  },
  scheduleInitCanvas () {
    const s = this.data.state
    if (!this._shouldInitCanvas() || !s) {
      return
    }
    const seq = s.canvasSeq | 0
    if (this._canvasReadySeq === seq && this._cvs) {
      const st = this.data.state
      if (st) {
        this._onGameStateCanvas(st)
      }
      return
    }
    setTimeout(() => this.initCanvas2d(0), 200)
  },
  initCanvas2d (retry) {
    if (!wx.createSelectorQuery) {
      return
    }
    const n = retry | 0
    const page = this
    const q = wx.createSelectorQuery().in(this)
    q.select('#cvs2')
      .fields({ node: true, size: true })
      .exec((res) => {
        const nodeRes = res && res[0]
        if (!nodeRes || !nodeRes.node) {
          if (n < 12 && page._shouldInitCanvas()) {
            setTimeout(() => page.initCanvas2d(n + 1), 120 + n * 60)
          }
          return
        }
        const canvas = nodeRes.node
        const ctx = canvas.getContext('2d')
        const w = DRAW_CANVAS_W
        const h = DRAW_CANVAS_H
        const dpr = (wx.getSystemInfoSync() && wx.getSystemInfoSync().pixelRatio) || 2
        canvas.width = w * dpr
        canvas.height = h * dpr
        if (ctx && ctx.scale) {
          ctx.scale(dpr, dpr)
        }
        page._cvs = canvas
        page._ctx = ctx
        page._w = w
        page._h = h
        page._last = null
        const st = page.data.state
        page._canvasReadySeq = st ? (st.canvasSeq | 0) : 0
        page.clearLocalCanvas()
        page._refreshCanvasRect()
        const st2 = page.data.state
        if (st2) {
          page._onGameStateCanvas(st2)
        }
        if (page._allPaths && page._allPaths.length) {
          page.redrawCanvas(page._allPaths, page._canvasReadySeq)
        }
        if (page._pendingCanvasPaths) {
          page.redrawCanvas(page._pendingCanvasPaths, page._pendingCanvasSeq)
          page._pendingCanvasPaths = null
        } else if (st2) {
          page._onGameStateCanvas(st2)
        }
      })
  },
  onTouchS (e) {
    if (e && typeof e.preventDefault === 'function') {
      e.preventDefault()
    }
    if (!this.data.isDrawingMode) {
      return
    }
    this._touching = true
    this._refreshCanvasRect(() => {
      this.touchCommon(e, true)
    })
  },
  onTouchE () {
    this._touching = false
    this._last = null
    if (this._curPath && this._curPath.pts && this._curPath.pts.length >= 2) {
      this._allPaths.push(this._curPath)
    }
    this._curPath = null
    this.saveCanvasToCloud()
  },
  touchCommon (e, isStart) {
    const s = this.data.state
    if (
      !this.data.isDrawingMode ||
      !this.data.isMeDrawer ||
      !s ||
      s.phase !== 'drawing' ||
      s.status !== 'playing'
    ) {
      return
    }
    const t0 = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0])
    const pt = this._touchXY(t0)
    if (!pt) {
      return
    }
    const w = this._w || DRAW_CANVAS_W
    const h = this._h || DRAW_CANVAS_H
    const xy = clampPt(pt.x, pt.y, w, h)
    const x = xy[0]
    const y = xy[1]
    const ctx = this._ctx
    if (!ctx) {
      this.initCanvas2d()
      return
    }
    if (isStart) {
      this._last = { x, y }
      this._curPath = {
        c: this._color,
        w: this.data.lineW | 0 || 4,
        pts: [[x, y]]
      }
      return
    }
    if (!this._last) {
      this._last = { x, y }
      return
    }
    if (ctx.strokeStyle !== undefined) {
      ctx.strokeStyle = this._color
    } else {
      if (ctx.setStrokeStyle) {
        ctx.setStrokeStyle(this._color)
      }
    }
    if (ctx.lineWidth !== undefined) {
      ctx.lineWidth = this.data.lineW | 0 || 4
    } else if (ctx.setLineWidth) {
      ctx.setLineWidth(this.data.lineW | 0 || 4)
    }
    if (ctx.setLineCap) {
      ctx.setLineCap('round')
    }
    if (ctx.setLineJoin) {
      ctx.setLineJoin('round')
    }
    if (ctx.beginPath) {
      ctx.beginPath()
    }
    if (ctx.moveTo) {
      ctx.moveTo(this._last.x, this._last.y)
    }
    if (ctx.lineTo) {
      ctx.lineTo(x, y)
    }
    if (ctx.stroke) {
      ctx.stroke()
    }
    this._last = { x, y }
    if (this._curPath && this._curPath.pts) {
      this._curPath.pts.push([x, y])
    }
  },
  onClear () {
    this._last = null
    this._curPath = null
    this._allPaths = []
    this.clearLocalCanvas()
    if (this.data.roomId) {
      callDraw(
        { action: 'updateCanvas', roomId: this.data.roomId, clear: true },
        { silent: true }
      )
    }
  },
  setupUploadLoop () {
    /* 笔画同步见 _queueStrokeUpload；不再每 500ms 传整图，减轻延迟与体积 */
  },
  uploadFrame () {
    /* 保留供退出绘画模式时可选调用 */
    if (!this._cvs || !this.data.isMeDrawer) {
      return
    }
    const roomId = this.data.roomId
    wx.canvasToTempFilePath({
      canvas: this._cvs,
      fileType: 'jpg',
      quality: 0.4,
      success: (r) => {
        const fs = wx.getFileSystemManager()
        if (!fs || !fs.readFile) {
          return
        }
        fs.readFile({
          filePath: r.tempFilePath,
          encoding: 'base64',
          success: (b) => {
            const raw = b.data
            if (!raw || String(raw).length < 20) {
              return
            }
            callDraw(
              { action: 'updateCanvas', roomId: roomId, image: String(raw) },
              { silent: true }
            )
          }
        })
      },
      fail: () => {}
    })
  }
})
