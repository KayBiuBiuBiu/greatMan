const {
  truthQuestions,
  dareQuestions,
  drawWords,
  storyStarts,
  gardens,
  helperGames,
  getTurtleSoupRiddles,
  getTurtleSoupRiddleByIndex
} = require('../../data/game-data')
const { pickOne } = require('../utils/random')
const { callRoomService } = require('../../utils/roomCloud')
const { withJoinProfile } = require('../../utils/userProfile')
const {
  storeMyOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow
} = require('../utils/inRoomCloudSync')
const TD_OPENID_KEY = 'td_my_open_id'
const {
  memberCountLine,
  runStartAction,
  buildStartChecks
} = require('../utils/roomUi')
const { patchMemberDisplay } = require('../utils/roomMemberUi')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const { getShareTokenForShare } = require('../../utils/aiUnlock')
const { callRiddleShare } = require('../utils/riddleShareCloud')
const {
  refreshAiUnlockPage,
  tryRedeemShareFromQuery,
  onPageShowUnlock,
  onPageHideUnlock,
  closeAiShareModal,
  showShareGuide
} = require('../../utils/aiUnlock')
const { runAi, SYSTEM_TRUTH_DARE, SYSTEM_STORY } = require('../utils/aiHelper')
const { copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const lobbyReady = require('../utils/roomLobbyReady')
const { lobbyGuestReadyStats, overlayLobbyProfileReady } = lobbyReady

Page({
  data: {
    title: '',
    mode: 'random',
    roomCode: '',
    prompt: null,
    showAnswer: false,
    scoreA: 0,
    scoreB: 0,
    count: 0,
    seconds: 30,
    timerRunning: false,
    numberTarget: 0,
    numberLow: 1,
    numberHigh: 100,
    numberMessage: '',
    questionType: 'truth',
    storyLines: [],
    // 同场同步·真心话大冒险
    tdIsHost: false,
    tdIsTarget: false,
    tdTargetName: '',
    tdPhase: 'none',
    tdTruth: 0,
    tdDare: 0,
    tdMyChoice: '',
    tdLastTally: null,
    tdShowQuestion: false,
    tdHasQuestion: false,
    tdQuestionTitle: '',
    tdQuestionDetail: '',
    tdRound: 0,
    tdVoteCast: 0,
    tdVoteNeed: 0,
    tdRoomPlayers: [],
    tdMyOpenId: '',
    displayPlayers: [],
    statusHint: '',
    canStart: false,
    statusBannerWarn: false,
    memberCountLine: '',
    aiBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {},
    showUserInfoModal: false,
    lobbySelfReady: false
  },

  timer: null,
  _tdJoining: false,
  _tdSyncBusy: false,
  _riddleIndex: -1,
  _riddleShareToken: '',

  onLoad(query) {
    const q = query || {}
    tryRedeemShareFromQuery(q)
    const title = decodeURIComponent(q.title || '')
    let config = {}
    try {
      config = q.config ? JSON.parse(decodeURIComponent(q.config)) : {}
    } catch (e) {
      config = {}
    }
    enableShareMenus()
    if (q.mode === 'riddle' || title === '海龟汤') {
      this._bootRiddleFromQuery(q, title)
      return
    }
    this.setData({ title })
    const rc = (config.roomCode && String(config.roomCode).replace(/\D/g, '')) || ''
    if (title === '真心话大冒险' && rc.length === 4) {
      this.setData({ mode: 'truthDareRoom', roomCode: rc })
      onRoomEntered(this, 'td_' + rc, 'truthDare')
      this._bootTruthDareRoom()
      return
    }
    this.initGame(title)
  },

  onHide() {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
  },

  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.mode === 'truthDareRoom' && this.data.roomCode) {
      resumeInRoomPollOnShow(this, this._refreshTdSync, 3000)
      this._refreshTdSync()
    }
    if (this.data.mode === 'riddle' && this.data.prompt && this.data.prompt.detail) {
      this._refreshRiddleShareToken()
    }
  },

  _shareCtx() {
    return { roomCode: this.data.roomCode }
  },

  onCopyRoomCode() {
    copyRoomCodeToClipboard(this.data.roomCode)
  },
  onShareAppMessage() {
    if (this.data.mode === 'riddle') {
      return this._buildRiddleShareMessage()
    }
    if (this.data.mode === 'truthDareRoom') {
      return handleShareAppMessage(this, 'truthDare', this._shareCtx())
    }
    return handleShareAppMessage(this, 'index', {})
  },

  onShareTimeline() {
    if (this.data.mode === 'riddle') {
      return this._buildRiddleTimeline()
    }
    if (this.data.mode === 'truthDareRoom') {
      return handleShareTimeline(this, 'truthDare', this._shareCtx())
    }
    return handleShareTimeline(this, 'index', {})
  },

  _bootRiddleFromQuery(query, titleFromPath) {
    this.config = helperGames['海龟汤'] || { mode: 'riddle', prompts: [] }
    this.setData({ title: titleFromPath || '海龟汤' })
    const rt = String(query.rt || query.riddleToken || '')
      .trim()
      .replace(/[^a-zA-Z0-9]/g, '')
    if (rt) {
      wx.showLoading({ title: '加载汤面' })
      callRiddleShare(
        { action: 'get', token: rt },
        {
          onOk: (res) => {
            wx.hideLoading()
            const r = (res && res.result) || {}
            const data = r.riddleData
            if (!data || !data.detail) {
              wx.showToast({ title: '分享内容无效', icon: 'none' })
              this._bootRiddleRandom()
              return
            }
            this._riddleIndex = r.riddleId != null ? (r.riddleId | 0) : -1
            this._applyRiddlePrompt(data)
          },
          onError: () => {
            wx.hideLoading()
            const idx = parseInt(query.riddleIndex, 10)
            if (!isNaN(idx)) {
              this._bootRiddleByIndex(idx)
            } else {
              wx.showToast({ title: '加载失败，已换成本地题目', icon: 'none' })
              this._bootRiddleRandom()
            }
          }
        }
      )
      return
    }
    const idx = parseInt(query.riddleIndex, 10)
    if (!isNaN(idx) && idx >= 0) {
      this._bootRiddleByIndex(idx)
      return
    }
    this._bootRiddleRandom()
  },

  _bootRiddleRandom() {
    const list = getTurtleSoupRiddles()
    const idx = list.length ? Math.floor(Math.random() * list.length) : 0
    this._bootRiddleByIndex(idx)
  },

  _bootRiddleByIndex(index) {
    const p = getTurtleSoupRiddleByIndex(index)
    this._riddleIndex = index | 0
    this._applyRiddlePrompt(p)
  },

  _applyRiddlePrompt(prompt) {
    this.setData({
      mode: 'riddle',
      prompt: prompt,
      showAnswer: false
    })
    this._refreshRiddleShareToken()
  },

  _refreshRiddleShareToken() {
    const p = this.data.prompt
    if (!p || !p.detail || !wx.cloud) {
      return
    }
    callRiddleShare(
      {
        action: 'create',
        riddleId: this._riddleIndex != null ? this._riddleIndex : -1,
        riddleData: {
          title: p.title,
          detail: p.detail,
          answer: p.answer || '',
          hint: p.hint || ''
        }
      },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.token) {
            this._riddleShareToken = r.token
          }
        },
        onError: () => {}
      }
    )
  },

  _buildRiddleShareQuery() {
    const p = this.data.prompt || {}
    let q =
      'mode=riddle&title=' + encodeURIComponent('海龟汤')
    if (this._riddleShareToken) {
      q += '&rt=' + encodeURIComponent(this._riddleShareToken)
    } else if (this._riddleIndex != null && this._riddleIndex >= 0) {
      q += '&riddleIndex=' + this._riddleIndex
    }
    if (p.title) {
      q += '&riddleTitle=' + encodeURIComponent(p.title)
    }
    const st = getShareTokenForShare(this)
    if (st) {
      q += '&st=' + encodeURIComponent(st)
    }
    return q
  },

  _buildRiddleShareMessage() {
    const p = this.data.prompt || {}
    const name = p.title || '海龟汤'
    return {
      title: '和你一起玩海龟汤：' + name,
      path: '/packageGames/play/play?' + this._buildRiddleShareQuery()
    }
  },

  _buildRiddleTimeline() {
    const msg = this._buildRiddleShareMessage()
    return {
      title: msg.title,
      query: msg.path.split('?')[1] || ''
    }
  },

  onRiddleShareTap() {
    if (this.data.mode !== 'riddle') {
      return
    }
    if (!this._riddleShareToken) {
      this._refreshRiddleShareToken()
    }
  },

  _lobbyReadyCtx() {
    return {
      callService: callRoomService,
      roomCode: this.data.roomCode,
      onSynced: () => this._refreshTdSync(true)
    }
  },
  onLobbyReadyTap() {
    lobbyReady.bindLobbyReadyTap(this, this._lobbyReadyCtx())
  },
  onLobbyUserInfoSuccess() {
    lobbyReady.onLobbyUserInfoSuccess(this)
  },
  onLobbyUserInfoCancel() {
    lobbyReady.onLobbyUserInfoCancel(this)
  },
  onCloseAiShareModal() {
    closeAiShareModal(this)
  },

  onAiShareTimeline() {
    closeAiShareModal(this)
    showShareGuide()
  },

  onUnload() {
    onPageHideUnlock(this)
    this.stopTimer()
    stopInRoomPoll(this)
    this._tdSyncBusy = false
  },

  _storeMyOpenId(oid) {
    storeMyOpenId(TD_OPENID_KEY, oid)
  },

  _bootTruthDareRoom() {
    if (!this.data.roomCode) {
      return
    }
    this._tdEnsureJoin(() => {
      ensureInRoomPoll(this, this._refreshTdSync, 3000)
      this._refreshTdSync()
    })
  },

  _tdEnsureJoin(done) {
    if (!this.data.roomCode || this._tdJoining) {
      if (typeof done === 'function') {
        done()
      }
      return
    }
    this._tdJoining = true
    callRoomService(
      withJoinProfile({ action: 'join', roomCode: this.data.roomCode }),
      {
        silent: true,
        onOk: (res) => {
          this._tdJoining = false
          const r = (res && res.result) || {}
          if (r.myOpenId || r.currentOpenId) {
            this._storeMyOpenId(r.myOpenId || r.currentOpenId)
          }
          if (r.players) {
            this._applyRoomPlayers(r, r.myOpenId || r.currentOpenId)
          }
          if (typeof done === 'function') {
            done()
          }
        },
        onError: (err, hint) => {
          this._tdJoining = false
          wx.showToast({
            title: (hint && hint.text) || (err && err.message) || '进组失败',
            icon: 'none'
          })
          if (typeof done === 'function') {
            done()
          }
        }
      }
    )
  },

  _refreshTdSync(force) {
    if (!this.data.roomCode || !wx.cloud) {
      return
    }
    if (!force && this._tdSyncBusy) {
      return
    }
    this._tdSyncBusy = true
    callRoomService(
      { action: 'syncState', roomCode: this.data.roomCode },
      {
        silent: true,
        onOk: (res) => {
          this._tdSyncBusy = false
          const r = (res && res.result) || {}
          if (r.errMsg) {
            console.warn('[td syncState]', r.errMsg)
            return
          }
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          if (r.inRoom === false) {
            this._tdEnsureJoin(() => this._refreshTdSync())
            return
          }
          if (r.td) {
            this.applyTdState(r.td)
          }
          if (r.room) {
            this._applyRoomPlayers(r.room, r.myOpenId || (r.td && r.td.currentOpenId))
          }
        },
        onError: () => {
          this._tdSyncBusy = false
        }
      }
    )
  },

  refreshTdState() {
    if (!this.data.roomCode) {
      return
    }
    callRoomService(
      { action: 'tdGetState', roomCode: this.data.roomCode },
      { silent: true, onOk: (res) => this.applyTdState(res.result || {}), onError: () => {} }
    )
  },

  applyTdState(s) {
    if (!s || typeof s !== 'object') {
      return
    }
    const cur = s.currentOpenId
    const target = s.targetOpenId
    const isTarget = !!cur && !!target && cur === target
    const patch = {
      tdIsHost: !!s.isHost,
      tdIsTarget: isTarget,
      tdTargetName: s.targetNickName || '',
      tdPhase: s.phase || 'none',
      tdTruth: s.truthCount != null ? s.truthCount : 0,
      tdDare: s.dareCount != null ? s.dareCount : 0,
      tdMyChoice: s.myChoice || '',
      tdLastTally: s.lastTally,
      tdRound: s.round || 0,
      tdMyOpenId: cur || '',
      tdVoteCast: (s.voteProgress && s.voteProgress.cast) | 0,
      tdVoteNeed: (s.voteProgress && s.voteProgress.need) | 0
    }
    if (s.phase === 'voting' || s.phase === 'none') {
      patch.tdShowQuestion = false
      patch.tdHasQuestion = false
      patch.tdQuestionTitle = ''
      patch.tdQuestionDetail = ''
      patch.prompt = null
      this.setData(patch)
      this._ensureTdPollInterval('waiting')
      return
    }
    if (s.phase === 'resolved' && s.lastTally && s.lastTally.tie) {
      patch.tdShowQuestion = false
      patch.tdHasQuestion = false
      patch.tdQuestionTitle = ''
      patch.tdQuestionDetail = ''
      patch.prompt = null
      this.setData(patch)
      this._ensureTdPollInterval('waiting')
      return
    }
    this._patchTdQuestion(patch, s)
    this.setData(patch)
    if (s.phase === 'resolved') {
      this._ensureTdPollInterval('resolved')
    }
  },

  _patchTdQuestion(patch, s) {
    const q = s && s.currentQuestion
    const show =
      s &&
      s.phase === 'resolved' &&
      s.lastTally &&
      !s.lastTally.tie &&
      q &&
      String(q.detail || '').trim()
    if (!show) {
      patch.tdShowQuestion = false
      patch.tdHasQuestion = false
      patch.tdQuestionTitle = ''
      patch.tdQuestionDetail = ''
      return
    }
    const kind = q.kind === 'dare' ? 'dare' : 'truth'
    const title = q.title || (kind === 'dare' ? '大冒险' : '真心话')
    const detail = String(q.detail).trim()
    patch.tdShowQuestion = true
    patch.tdHasQuestion = true
    patch.tdQuestionTitle = title
    patch.tdQuestionDetail = detail
    patch.questionType = kind
    patch.prompt = { title: title, detail: detail }
  },

  _ensureTdPollInterval(mode) {
    const want = mode === 'resolved' ? 2000 : 3000
    if (this._tdPollMs === want) {
      return
    }
    this._tdPollMs = want
    stopInRoomPoll(this)
    ensureInRoomPoll(this, this._refreshTdSync, want)
  },

  _tdPublishQuestion(title, detail, kind) {
    if (!this.data.roomCode) {
      return
    }
    const k = kind || this.data.questionType || 'truth'
    callRoomService(
      {
        action: 'tdSetQuestion',
        roomCode: this.data.roomCode,
        kind: k,
        title: title,
        detail: detail
      },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.currentQuestion) {
            const patch = {}
            this._patchTdQuestion(patch, {
              phase: 'resolved',
              lastTally: this.data.tdLastTally,
              currentQuestion: r.currentQuestion
            })
            this.setData(patch)
          }
          this._refreshTdSync(true)
        },
        onError: (err, hint) => {
          wx.showToast({
            title: (hint && hint.text) || (err && err.message) || '同步题目失败',
            icon: 'none'
          })
        }
      }
    )
  },

  _applyRoomPlayers(r, myOpenId) {
    if (!r || this.data.mode !== 'truthDareRoom') {
      return
    }
    const pl = r.players || []
    const hostOid = String(r.hostOpenId || '').trim()
    const myOid = String(
      myOpenId || r.currentOpenId || this.data.tdMyOpenId || ''
    ).trim()
    const plReady = overlayLobbyProfileReady(pl, myOid, this)
    const isHost =
      !!this.data.tdIsHost || !!(hostOid && myOid && hostOid === myOid)
    const patch = {
      tdRoomPlayers: pl,
      memberCountLine: memberCountLine(pl.length, 0, '至少 2 人可开始')
    }
    const ph = this.data.tdPhase === 'none' ? 'waiting' : 'playing'
    patchMemberDisplay(patch, {
      players: plReady.map((p) => ({
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl || '',
        profileReady: !!p.profileReady,
        isHost: !!p.isHost || !!(hostOid && p.openId === hostOid)
      })),
      phase: ph,
      maxPlayers: 0,
      isHost: isHost,
      hostOpenId: hostOid,
      myOpenId: myOid,
      fallbackNeed: 2,
      hostWaiting: '⏳ 点击「开始本轮」',
      guestWaiting: '👥 请点「准备」，等待主持人开始',
      page: this
    })
    patch.tdIsHost = isHost
    const gr = lobbyGuestReadyStats(plReady, hostOid, this, myOid)
    patch.canStart = isHost && pl.length >= 2 && gr.allReady
    if (ph === 'waiting' && pl.length < 2) {
      patch.statusHint = '⚠️ 至少需要 2 人，当前 ' + pl.length + ' 人'
      patch.statusBannerWarn = true
    } else if (ph === 'waiting' && pl.length >= 2) {
      if (isHost && gr.guestCount > 0 && !gr.allReady) {
        const not = Math.max(0, gr.guestCount - gr.readyCount)
        patch.statusHint = '⚠️ 还有 ' + not + ' 人未点「准备」'
        patch.statusBannerWarn = true
      } else {
        patch.statusHint = isHost
          ? '✅ 人齐且已准备，可开始本轮'
          : '👥 请点「准备」，等待主持人开始'
        patch.statusBannerWarn = false
      }
    }
    if (ph === 'waiting') {
      lobbyReady.patchLobbySelfReady(patch, plReady, myOid, true, this)
    }
    this.setData(patch)
  },

  refreshRoomPlayers() {
    if (!this.data.roomCode || this.data.mode !== 'truthDareRoom') {
      return
    }
    callRoomService(
      { action: 'get', roomCode: this.data.roomCode },
      {
        silent: true,
        onOk: (res) => {
          const r = res.result || {}
          this._applyRoomPlayers(r, r.currentOpenId || r.myOpenId)
        },
        onError: () => {}
      }
    )
  },

  tdAbdicateHost() {
    if (!this.data.tdIsHost) {
      return
    }
    wx.showModal({
      title: '移交主持',
      content: '将把主持移交给进组最早的一位其他成员，确定吗？',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        wx.showLoading({ title: '…' })
        callRoomService(
          { action: 'abdicateHost', roomCode: this.data.roomCode },
          {
            onOk: () => {
              wx.hideLoading()
              wx.showToast({ title: '已移交', icon: 'success' })
              this._refreshTdSync()
            },
            onError: (err, hint) => {
              wx.hideLoading()
              wx.showToast({ title: (hint && hint.text) || '失败', icon: 'none' })
            }
          }
        )
      }
    })
  },

  tdShowTransferSheet() {
    if (!this.data.tdIsHost) {
      return
    }
    if (!this.data.tdMyOpenId) {
      wx.showToast({ title: '正在同步身份，请稍候', icon: 'none' })
      this._refreshTdSync()
      return
    }
    const my = this.data.tdMyOpenId
    const ps = (this.data.tdRoomPlayers || []).filter(function (p) {
      return p.openId && p.openId !== my
    })
    if (!ps.length) {
      wx.showToast({ title: '暂无其他成员', icon: 'none' })
      return
    }
    wx.showActionSheet({
      itemList: ps.map(function (p) {
        return p.nickName || '参与者'
      }),
      success: (res) => {
        const i = res.tapIndex
        if (i < 0 || i >= ps.length) {
          return
        }
        const targetOpenId = ps[i].openId
        wx.showLoading({ title: '…' })
        callRoomService(
          {
            action: 'transferHost',
            roomCode: this.data.roomCode,
            targetOpenId: targetOpenId
          },
          {
            onOk: () => {
              wx.hideLoading()
              wx.showToast({ title: '已移交主持', icon: 'success' })
              this._refreshTdSync()
            },
            onError: (err, hint) => {
              wx.hideLoading()
              wx.showToast({ title: (hint && hint.text) || '移交失败', icon: 'none' })
            }
          }
        )
      }
    })
  },

  tdStartRound() {
    const n = (this.data.tdRoomPlayers || []).length
    const ctx = { playerCount: n }
    const checks = buildStartChecks({
      isHost: this.data.tdIsHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'truthDare',
      ctx,
      players: this.data.tdRoomPlayers || [],
      hostOpenId: (() => {
        const hp = (this.data.tdRoomPlayers || []).find((p) => p && p.isHost)
        return hp ? hp.openId : ''
      })(),
      hostLabel: '主持人',
      startVerb: '开始新轮'
    })
    const callTd = (payload, opts) => callRoomService(payload, opts)
    runStartAction({
      kind: 'truthDare',
      ctx,
      localChecks: checks,
      callService: callTd,
      payload: { action: 'tdStart', roomCode: this.data.roomCode },
      loadingTitle: '开始',
      onSuccess: () => {
        wx.showToast({ title: '已随机选人', icon: 'success' })
        this._refreshTdSync()
      }
    })
  },

  tdCastVote(e) {
    const choice = e.currentTarget.dataset.choice
    if (choice !== 'truth' && choice !== 'dare') {
      return
    }
    callRoomService(
      { action: 'tdVote', roomCode: this.data.roomCode, choice: choice },
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          this._refreshTdSync()
          if (r.autoTally) {
            wx.showToast({ title: '全员已投，已出结果', icon: 'success' })
          } else {
            wx.showToast({ title: '已投票', icon: 'success' })
          }
        }
      }
    )
  },

  tdFinish() {
    if (!this.data.tdIsHost) {
      return
    }
    wx.showLoading({ title: '…' })
    callRoomService(
      { action: 'tdTally', roomCode: this.data.roomCode },
      {
        onOk: (res) => {
          wx.hideLoading()
          this._refreshTdSync()
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  tdDrawQuestion() {
    if (this.data.mode === 'truthDareRoom' && !this.data.tdIsTarget) {
      wx.showToast({ title: '请被选中的人在自己手机上抽题', icon: 'none' })
      return
    }
    const lt = this.data.tdLastTally
    if (!lt || lt.tie || !lt.winner) {
      return
    }
    const list = lt.winner === 'truth' ? truthQuestions : dareQuestions
    const title = lt.winner === 'truth' ? '真心话' : '大冒险'
    const detail = pickOne(list)
    if (this.data.mode === 'truthDareRoom') {
      this._tdPublishQuestion(title, detail, lt.winner)
      return
    }
    this.setData({
      tdShowQuestion: true,
      questionType: lt.winner,
      prompt: { title: title, detail: detail }
    })
  },

  tdNextRound() {
    this.tdStartRound()
  },

  initGame(title) {
    if (title === '真心话大冒险') {
      this.setData({ mode: 'truthDare', prompt: { title: '真心话', detail: '点下面标签选真心话/大冒险，再点「换一题」抽题。' } })
      return
    }
    if (title.indexOf('你画我猜') >= 0) {
      this.setData({ mode: 'draw', prompt: { title: pickOne(drawWords), detail: '给表演者看词，其他人猜。' } })
      return
    }
    if (title === '故事接龙') {
      this.setData({ mode: 'story', prompt: { title: pickOne(storyStarts), detail: '每人轮流接一句。' } })
      return
    }
    if (title === '逛三园') {
      const garden = pickOne(gardens)
      this.setData({ mode: 'garden', prompt: { title: garden.name, detail: '示例：' + garden.examples.join('、') }, seconds: 5 })
      return
    }
    if (title === '猜数字') {
      this.resetNumber()
      return
    }
    if (title === '海龟汤') {
      this.config = helperGames['海龟汤'] || { mode: 'riddle', prompts: [] }
      this._bootRiddleRandom()
      return
    }

    const config = helperGames[title] || { mode: 'random', prompts: [{ title, detail: '主持人持机，亲友口头互动。' }] }
    this.config = config
    this.setData({
      mode: config.mode,
      prompt: pickOne(config.prompts),
      seconds: config.mode === 'traffic' || config.mode === 'reverse' ? 5 : 30
    })
  },

  nextPrompt() {
    if (this.data.mode === 'truthDare') {
      const list = this.data.questionType === 'truth' ? truthQuestions : dareQuestions
      this.setData({ prompt: { title: this.data.questionType === 'truth' ? '真心话' : '大冒险', detail: pickOne(list) } })
      return
    }
    if (this.data.mode === 'draw') {
      this.setData({ prompt: { title: pickOne(drawWords), detail: '给表演者看词，其他人猜。' } })
      return
    }
    if (this.data.mode === 'story') {
      this.setData({ prompt: { title: pickOne(storyStarts), detail: '每人轮流接一句。' }, storyLines: [] })
      return
    }
    if (this.data.mode === 'garden') {
      const garden = pickOne(gardens)
      this.setData({ prompt: { title: garden.name, detail: '示例：' + garden.examples.join('、') }, seconds: 5 })
      return
    }
    if (this.data.mode === 'riddle') {
      const list = getTurtleSoupRiddles()
      let idx = list.length ? Math.floor(Math.random() * list.length) : 0
      if (list.length > 1 && idx === this._riddleIndex) {
        idx = (idx + 1) % list.length
      }
      this._bootRiddleByIndex(idx)
      return
    }
    const prompts = this.config ? this.config.prompts : []
    this.setData({ prompt: pickOne(prompts), showAnswer: false })
  },

  switchQuestionType(event) {
    this.setData({ questionType: event.currentTarget.dataset.type })
    this.nextPrompt()
  },

  toggleAnswer() {
    this.setData({ showAnswer: !this.data.showAnswer })
  },

  addScore(event) {
    const key = event.currentTarget.dataset.key
    this.setData({ [key]: this.data[key] + 1 })
  },

  clearScore() {
    this.setData({ scoreA: 0, scoreB: 0, count: 0, storyLines: [] })
  },

  addStoryLine() {
    const lines = this.data.storyLines.concat(['第 ' + (this.data.storyLines.length + 1) + ' 句'])
    this.setData({ storyLines: lines })
  },

  toggleTimer() {
    if (this.timer) {
      this.stopTimer()
      return
    }
    this.setData({ timerRunning: true })
    this.timer = setInterval(() => {
      const seconds = this.data.seconds - 1
      if (seconds <= 0) {
        this.stopTimer()
        this.setData({ seconds: 0 })
        wx.vibrateShort()
        wx.showToast({ title: '时间到', icon: 'none' })
        return
      }
      this.setData({ seconds })
    }, 1000)
  },

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    this.setData({ timerRunning: false })
  },

  resetTimer() {
    this.stopTimer()
    this.setData({ seconds: this.data.mode === 'garden' || this.data.mode === 'traffic' || this.data.mode === 'reverse' ? 5 : 30 })
  },

  resetNumber() {
    this.setData({
      mode: 'number',
      numberTarget: Math.floor(1 + Math.random() * 100),
      numberLow: 1,
      numberHigh: 100,
      count: 0,
      numberMessage: '数字已生成，请输入参与者猜测。'
    })
  },

  askNumber() {
    wx.showModal({
      title: '输入猜测数字',
      editable: true,
      placeholderText: this.data.numberLow + '-' + this.data.numberHigh,
      success: (result) => {
        if (!result.confirm) {
          return
        }
        this.checkNumber(Number(result.content))
      }
    })
  },

  onAiSpicePrompt() {
    if (this.data.mode === 'truthDareRoom' && !this.data.tdIsTarget) {
      return
    }
    const p = this.data.prompt
    if (!p || !p.detail) {
      return
    }
    const kind = this.data.questionType === 'dare' ? '大冒险' : '真心话'
    runAi(this, {
      cacheTag: 'play-spice-' + this.data.questionType,
      system: SYSTEM_TRUTH_DARE,
      postProcess: { maxLen: 50 },
      buildPrompt: () => '原' + kind + '题：「' + p.detail + '」。请改写成更幽默的版本。',
      onOk: (text) => {
        const title = p.title || kind
        if (this.data.mode === 'truthDareRoom') {
          this._tdPublishQuestion(title, text, this.data.questionType)
          return
        }
        if (this.data.mode === 'riddle') {
          this._riddleIndex = -1
          this.setData({
            prompt: { title: p.title || '海龟汤', detail: text, answer: p.answer || '', hint: p.hint || '' }
          })
          this._refreshRiddleShareToken()
          return
        }
        this.setData({
          tdShowQuestion: true,
          prompt: { title: title, detail: text }
        })
      }
    })
  },
  onAiGenTruthDare() {
    const kind = this.data.questionType === 'dare' ? '大冒险' : '真心话'
    runAi(this, {
      cacheTag: 'play-gen-' + this.data.questionType,
      system: SYSTEM_TRUTH_DARE,
      postProcess: { maxLen: 50 },
      buildPrompt: () => '生成1条' + kind + '。',
      onOk: (text) => {
        const patch = { prompt: { title: kind, detail: text } }
        if (this.data.mode === 'truthDareRoom') {
          patch.tdShowQuestion = true
        }
        this.setData(patch)
      }
    })
  },
  onAiStoryLine() {
    const lines = this.data.storyLines || []
    runAi(this, {
      cacheTag: 'play-story',
      round: lines.length,
      system: SYSTEM_STORY,
      postProcess: { maxLen: 80 },
      buildPrompt: () => {
        const prev = lines.length ? lines.join('') : this.data.prompt.title || ''
        return '故事接龙，已有：「' + prev + '」。'
      },
      onOk: (text) => {
        const lines2 = this.data.storyLines.concat([text])
        this.setData({ storyLines: lines2 })
      }
    })
  },
  checkNumber(guess) {
    if (!guess || guess < this.data.numberLow || guess > this.data.numberHigh) {
      this.setData({ numberMessage: '请输入当前范围内的数字。' })
      return
    }
    const count = this.data.count + 1
    if (guess === this.data.numberTarget) {
      this.setData({ count, numberMessage: '猜中了！答案就是 ' + guess })
    } else if (guess > this.data.numberTarget) {
      this.setData({ count, numberHigh: guess - 1, numberMessage: guess + ' 大了。' })
    } else {
      this.setData({ count, numberLow: guess + 1, numberMessage: guess + ' 小了。' })
    }
  }
})
