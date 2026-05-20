const { callDraw, ensure } = require('../../utils/drawRoomCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../../utils/roomUi')
const { patchMemberDisplay } = require('../../utils/roomMemberUi')
const { onRoomEntered, onRoomLeft } = require('../../utils/partyAiRoomHooks')
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
const {
  watchDocument,
  stopDevtoolsPoll
} = require('../../utils/cloudRealtime')
const {
  runAi,
  validateDrawWord,
  showAiModal,
  SYSTEM_DRAW_WORD
} = require('../../utils/aiHelper')
const { CATS: CW_CATS } = require('../../data/draw-words')
const ROUNDS = [5, 6, 8, 9, 10, 12]
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
    roundIdx: 1,
    catNames: CAT_ARR.map((c) => c.name),
    catIdx: 0,
    guessInput: '',
    lineW: 4,
    remoteCanvasSrc: '',
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    playerProgressPct: 0,
    wordSource: 'system',
    aiPanelOpen: false,
    aiBusy: false,
    aiPendingWord: '',
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {}
  },
  _cvs: null,
  _ctx: null,
  _last: null,
  _color: '#111111',
  _uploadTimer: null,
  _ticker: null,
  _cseq: 0,
  _shareCtx () {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.state && this.data.state.roomCode)
    }
  },
  onLoad (q) {
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    const ridx = ROUNDS.indexOf(6)
    this.setData({ roundIdx: ridx >= 0 ? ridx : 0 })
    const roomId = (q && q.roomId) ? String(q.roomId) : ''
    const code = (q && q.roomCode) ? decodeURIComponent(String(q.roomCode)) : ''
    this.setData({
      nick: (q && q.nick) ? decodeURIComponent(String(q.nick)).slice(0, 12) : defNick(),
      roomId,
      roomCode: code,
      joinCode: code ? code.replace(/\D/g, '').slice(0, 6) : ''
    })
    if (roomId) {
      this.afterHasRoomId(roomId)
    }
  },
  onHide () {
    onPageHideUnlock(this)
    this.clearTimers()
  },
  onUnload () {
    onRoomLeft(this)
    this.clearTimers()
    this.stopWatchG()
    this.stopWatchC()
  },
  onShow () {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.roomId) {
      this._refreshRoomState()
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
    refreshCloudDoc('draw_gameState', id).then((d) => {
      if (d) {
        this.applyG(d)
      }
      this.loadView()
      this.scheduleInitCanvas()
    })
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
  onRoundPick (e) {
    this.setData({ roundIdx: Number((e.detail && e.detail.value) | 0) || 0 }, () => {
      this._saveConfig(true)
    })
  },
  onCatPick (e) {
    this.setData({ catIdx: Number((e.detail && e.detail.value) | 0) || 0 }, () => {
      this._saveConfig(true)
    })
  },
  onWordSourceTap (e) {
    const src = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src) || 'system'
    const patch = { wordSource: src }
    if (src === 'system') {
      patch.aiPendingWord = ''
    }
    this.setData(patch)
  },
  toggleAiPanel () {
    this.setData({ aiPanelOpen: !this.data.aiPanelOpen })
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
      { action: 'create', nickName: nick },
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
    wx.setStorageSync('draw_nick', nick)
    wx.showLoading({ title: '进房' })
    callDraw(
      { action: 'join', roomCode: code, nickName: nick },
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
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
  _saveConfig (silent) {
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
          if (!silent) {
            wx.showToast({ title: '已保存', icon: 'none' })
          }
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
    const page = this
    runAi(this, {
      cacheTag: 'draw-word',
      roomId: this.data.roomId,
      round: (this.data.state && this.data.state.currentRound) | 0,
      loadingTitle: 'AI 生成题目',
      system: SYSTEM_DRAW_WORD,
      buildPrompt: () => '你画我猜，词库风格：' + cat + '。',
      onOk: (text) => {
        const v = validateDrawWord(text)
        if (!v.ok) {
          showAiModal('失败', v.err)
          return
        }
        const w = v.word
        page.setData({
          wordSource: 'ai',
          aiPendingWord: w,
          aiPanelOpen: true
        })
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
          page.loadView()
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
      wx.showToast({ title: '先输入', icon: 'none' })
      return
    }
    callDraw(
      { action: 'submitGuess', roomId: this.data.roomId, answer: guess },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.drawerNoGuess) {
            wx.showToast({ title: '绘画者不能猜', icon: 'none' })
          } else if (r.wrong) {
            wx.showToast({ title: '不对', icon: 'none' })
          } else if (r.already) {
            wx.showToast({ title: '已答过', icon: 'none' })
          } else if (r.late) {
            wx.showToast({ title: '已超时', icon: 'none' })
          } else if (r.ok) {
            wx.showToast({ title: '中 +' + (r.points | 0), icon: 'none' })
            this.setData({ guessInput: '' })
          }
          this.loadView()
        }
      }
    )
  },
  afterHasRoomId (roomId) {
    this.setData({ roomId: String(roomId) })
    onRoomEntered(this, String(roomId), 'draw')
    this.startWatchG(String(roomId))
    this.startWatchC(String(roomId))
    if (wx.cloud && ensure()) {
      const db = wx.cloud.database()
      db
        .collection('draw_gameState')
        .doc(String(roomId))
        .get()
        .then((d) => {
          if (d && d.data) {
            this.applyG(d.data)
          }
        })
    }
    this.loadView()
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
      if (d) {
        this.applyG(d)
        this.onCanvasResetBySeq()
        this.loadView()
        this.setupTicker()
        this.setupUploadLoop()
        this.tryAutoReveal()
        this.scheduleInitCanvas()
      }
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
      }
    })
  },
  onCanvasResetBySeq () {
    const st = this.data.state
    if (!st) {
      return
    }
    const seq = st.canvasSeq | 0
    if (this._cseq !== seq) {
      this._cseq = seq
      this.setData({ remoteCanvasSrc: '' })
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
        const w = this._w || 280
        const h = this._h || 400
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
      onChange: (s) => {
        const d = s && (s.data != null ? s.data : s.doc)
        if (d) {
          const im = d.image
          if (im && im.length > 20) {
            this.setData({
              remoteCanvasSrc: im.indexOf('data:') === 0 ? im : 'data:image/jpeg;base64,' + im
            })
          } else {
            this.setData({ remoteCanvasSrc: '' })
          }
        }
      },
      pollTimerKey: '_devtoolsPollC',
      pollFn: () => {
        if (!this.data.roomId || !wx.cloud) {
          return
        }
        wx.cloud
          .database()
          .collection('draw_canvas')
          .doc(rid)
          .get()
          .then((res) => {
            const d = res && res.data
            if (!d) {
              return
            }
            const im = d.image
            if (im && im.length > 20) {
              this.setData({
                remoteCanvasSrc: im.indexOf('data:') === 0 ? im : 'data:image/jpeg;base64,' + im
              })
            }
          })
          .catch(() => {})
      }
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
    const n = (d.publicPlayers && d.publicPlayers.length) || 0
    const patch = {
      state: d,
      roomCode: d.roomCode || this.data.roomCode,
      memberCountLine: memberCountLine(n, 0, '至少 2 人可开始')
    }
    const v = this.data.view || {}
    patchMemberDisplay(patch, {
      players: d.publicPlayers || [],
      phase: d.status === 'waiting' ? 'waiting' : 'playing',
      maxPlayers: 0,
      isHost: v.isHost,
      fallbackNeed: 2
    })
    this.setData(patch)
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
          const st = this.data.state || {}
          const patch = { view: v }
          const stStatus = st.status || v.roomStatus
          patchMemberDisplay(patch, {
            players: (st.publicPlayers || v.publicPlayers) || [],
            phase: stStatus === 'waiting' ? 'waiting' : 'playing',
            maxPlayers: 0,
            isHost: v.isHost,
            fallbackNeed: 2
          })
          this.setData(patch, () => {
            this.tryAutoReveal()
            this.scheduleInitCanvas()
            this.setupUploadLoop()
            this.setupTicker()
          })
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
    const v = this.data.view
    const s = this.data.state
    if (v && v.isDrawer && s && s.phase === 'drawing' && s.status === 'playing') {
      if (!this._cvs) {
        setTimeout(() => this.initCanvas2d(), 200)
      }
    }
  },
  initCanvas2d () {
    if (!wx.createSelectorQuery) {
      return
    }
    const q = wx.createSelectorQuery()
    q
      .select('#cvs2')
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0] || !res[0].node) {
          return
        }
        const canvas = res[0].node
        const ctx = canvas.getContext('2d')
        const w = 280
        const h = 400
        const dpr = (wx.getSystemInfoSync() && wx.getSystemInfoSync().pixelRatio) || 2
        canvas.width = w * dpr
        canvas.height = h * dpr
        if (ctx && ctx.scale) {
          ctx.scale(dpr, dpr)
        }
        this._cvs = canvas
        this._ctx = ctx
        this._w = w
        this._h = h
        this._last = null
        this.clearLocalCanvas()
      })
  },
  onTouchS (e) {
    this.touchCommon(e, true)
  },
  onTouchM (e) {
    this.touchCommon(e, false)
  },
  onTouchE () {
    this._last = null
  },
  touchCommon (e, isStart) {
    const v = this.data.view
    const s = this.data.state
    if (!v || !v.isDrawer || !s || s.phase !== 'drawing' || s.status !== 'playing') {
      return
    }
    const t0 = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0])
    if (!t0 || t0.x == null) {
      return
    }
    const x = t0.x
    const y = t0.y
    const ctx = this._ctx
    if (!ctx) {
      this.initCanvas2d()
      return
    }
    if (isStart) {
      this._last = { x, y }
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
  },
  onClear () {
    this._last = null
    this.clearLocalCanvas()
  },
  setupUploadLoop () {
    if (this._uploadTimer) {
      clearInterval(this._uploadTimer)
      this._uploadTimer = null
    }
    const v = this.data.view
    const s = this.data.state
    if (!v || !v.isDrawer || !s || s.phase !== 'drawing' || s.status !== 'playing') {
      return
    }
    const p = this
    this._uploadTimer = setInterval(function () { p.uploadFrame() }, 500)
  },
  uploadFrame () {
    if (!this._cvs) {
      return
    }
    if (!this.data.view || !this.data.view.isDrawer) {
      return
    }
    if (!this.data.state || this.data.state.phase !== 'drawing') {
      return
    }
    const roomId = this.data.roomId
    wx.canvasToTempFilePath({
      canvas: this._cvs,
      fileType: 'jpg',
      quality: 0.45,
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
              {
                action: 'updateCanvas',
                roomId: roomId,
                image: String(raw)
              },
              { silent: true }
            )
          }
        })
      },
      fail: () => {}
    })
  }
})
