const {
  callWerewolfService,
  ensureWerewolfCloud
} = require('../../utils/werewolfCloud')
const { enterCloudRoomOnLoad } = require('../utils/roomJoin')
const { withJoinProfile, getFallbackNickName } = require('../../utils/userProfile')
const { markRoomDbWatch } = require('../../utils/cloudRealtime')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks,
  showStartBlockTip
} = require('../utils/roomUi')
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
const { runAi, runAiPoster, SYSTEM_RECAP } = require('../utils/aiHelper')
const { patchLobbyUi, computeProgressPct, buildLobbyStatusHint } = require('../utils/roomMemberUi')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const { copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { markPartyFinishedOnce } = require('../utils/partySession')
const {
  storeMyOpenId,
  loadStoredOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const lobbyReady = require('../utils/roomLobbyReady')
const { lobbyGuestReadyStats } = lobbyReady
const { runHostNarrate } = require('../../utils/agentHelper')
const {
  isWerewolfMockEnabled,
  isWerewolfEnabled,
  isAiButtonsEnabled,
  isWerewolfAIModeEnabled
} = require('../../data/feature-flags')
const { werewolfAiMixin } = require('./werewolfAiMixin')
const WOLF_OPENID_KEY = 'werewolf_my_open_id'
const MOCK_ENABLED = isWerewolfMockEnabled()
const {
  SIZES,
  HINT: WOLF_SIZE_HINT_BASE,
  indexOfSize,
  stepSizeIndex,
  vibrateBoundary,
  loadStoredSize,
  saveStoredSize
} = require('../../utils/wolfBoardSize')
const WOLF_SIZE_HINT = MOCK_ENABLED
  ? WOLF_SIZE_HINT_BASE + '，缺人时可加模拟玩家'
  : WOLF_SIZE_HINT_BASE
const RZH = {
  werewolf: '暗位成员',
  white_wolf: '白狼王',
  seer: '线索员',
  witch: '治愈者',
  hunter: '协定者',
  guard: '守卫',
  villager: '村民',
  '': '—'
}
const PZH = {
  lobby: '大厅',
  night: '夜间',
  day_announce: '天亮了',
  sheriff_signup: '警长竞选',
  sheriff_withdraw: '退水',
  sheriff_speak: '警上发言',
  sheriff_vote: '警徽投票',
  sheriff_transfer: '移交警徽',
  speak: '警下发言',
  vote: '放逐投票',
  hunter: '协定者',
  end: '结束',
  '': '—'
}

function roleZh(r) {
  return RZH[r] || r || '—'
}
function phZh(p) {
  return PZH[p] || p || '—'
}

Page({
  data: {
    opBusy: false,
    title: '秘密身份推理（聚会版）',
    nick: '',
    joinCode: '',
    roomId: '',
    roomCode: '',
    pub: null,
    view: {},
    maxList: SIZES,
    maxIndex: 0,
    wolfSizeHint: WOLF_SIZE_HINT,
    wolfMatesLine: '',
    seerLine: '',
    publicLogText: '',
    lastNightText: '',
    allRolesList: [],
    playerList: [],
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    playerProgressPct: 0,
    canStart: false,
    showMockPlayerTools: MOCK_ENABLED,
    aiBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {},
    showUserInfoModal: false,
    lobbySelfReady: false,
    inWaiting: false,
    pickMode: '',
    pickOptions: [],
    pickSelOid: '',
    pickHint: '',
    pickNeedConfirm: false,
    agentHostOn: false,
    agentSpeakLine: '',
    agentBusy: false,
    showAiModeOption: isWerewolfAIModeEnabled(),
    aiHostLobby: true,
    aiModeOn: false,
    aiPhaseTitle: '',
    aiCountdownPct: 100,
    aiView: {},
    aiActionBusy: false,
    aiAliveTargets: []
  },
  _shareCtx() {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.pub && this.data.pub.roomCode)
    }
  },
  onLoad(q) {
    if (!isWerewolfEnabled()) {
      wx.showToast({ title: '身份推理暂未开放', icon: 'none' })
      setTimeout(() => wx.navigateBack({ delta: 1 }), 400)
      return
    }
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    this._justOpened = true
    const title = decodeURIComponent(q.title || '秘密身份推理（聚会版）')
    const nick0 = (wx.getStorageSync('werewolf_nick') || '').toString() || getFallbackNickName()
    let config = {}
    try {
      if (q.config) {
        config = JSON.parse(decodeURIComponent(q.config))
      }
    } catch (e) {
      config = {}
    }
    const code = (q.code || config.roomCode || '')
      .toString()
      .replace(/\D/g, '')
      .slice(0, 6)
    const roomId0 = (q.roomId || config.roomId || '').toString()
    const prefSize =
      (config.wolfDefaultSize | 0) > 0
        ? config.wolfDefaultSize
        : loadStoredSize()
    const maxIndex = indexOfSize(prefSize)
    this.setData({
      title,
      nick: nick0,
      joinCode: code,
      maxIndex
    })
    if (roomId0) {
      const rc = (config.roomCode || code || '').toString().replace(/\D/g, '').slice(0, 6)
      this.setData({
        roomId: roomId0,
        roomCode: rc,
        joinCode: rc || this.data.joinCode
      })
      if (rc.length === 6) {
        enterCloudRoomOnLoad(this, {
          roomId: roomId0,
          roomCode: rc,
          callService: callWerewolfService,
          silentJoinToast: true,
          onReady: (id, jr) => this.afterHasRoomId(id, jr)
        })
      } else {
        this.afterHasRoomId(roomId0)
      }
    } else if (code.length === 6) {
      this.setData({ roomId: '', roomCode: code })
    }
  },
  onUnload() {
    onRoomLeft(this)
    stopInRoomPoll(this)
    this.stopAiPoll && this.stopAiPoll()
    this.stopWatch()
  },
  onHide() {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
    this.stopAiPoll && this.stopAiPoll()
  },
  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this._justOpened) {
      this._justOpened = false
      return
    }
    if (this.data.roomId) {
      resumeInRoomPollOnShow(this, this._refreshRoomState)
      this._refreshRoomState()
    }
  },
  onShareAppMessage() {
    return handleShareAppMessage(this, 'werewolf', this._shareCtx())
  },
  onShareTimeline() {
    return handleShareTimeline(this, 'werewolf', this._shareCtx())
  },
  _lobbyReadyCtx() {
    return {
      callService: callWerewolfService,
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.pub && this.data.pub.roomCode),
      onSynced: () => {
        this.syncDisplayText()
        this.loadView()
      }
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
  onCopyRoomCode() {
    const c = this.data.roomCode || (this.data.pub && this.data.pub.roomCode)
    copyRoomCodeToClipboard(c)
  },
  onAiShareTimeline() {
    closeAiShareModal(this)
    showShareGuide()
  },
  _storeMyOpenId(oid) {
    storeMyOpenId(WOLF_OPENID_KEY, oid)
  },
  _myOpenId() {
    const v = this.data.view || {}
    return String(v.myOpenId || loadStoredOpenId(WOLF_OPENID_KEY) || '').trim()
  },
  _pickHintForMode(mode) {
    const m = {
      wolf: '👇 点下方成员选择夜间关注对象',
      hostWolf: '👇 主持代选：点成员指定夜间关注对象',
      seer: '👇 点成员查看身份线索',
      poison: '👇 点成员后按确认',
      vote: '👇 点成员后确认投票',
      hunter: '👇 点成员后确认',
      guard: '👇 点成员后确认守护',
      whiteWolf: '👇 自爆：点成员后确认带走',
      sheriffVote: '👇 点候选人后确认警徽'
    }
    return m[mode] || '👇 点成员选择'
  },
  _pickNeedConfirm(mode) {
    return (
      mode === 'poison' ||
      mode === 'vote' ||
      mode === 'hunter' ||
      mode === 'guard' ||
      mode === 'whiteWolf' ||
      mode === 'sheriffVote'
    )
  },
  _patchPickMembers(patch) {
    const mode = patch.pickMode != null ? patch.pickMode : this.data.pickMode
    if (!mode) {
      patch.pickHint = ''
      patch.pickNeedConfirm = false
      return
    }
    const opts = this.buildPickOptions(mode)
    const oidSet = Object.create(null)
    opts.forEach((o) => {
      oidSet[o.openId] = true
    })
    const base = patch.displayPlayers || this.data.displayPlayers || []
    patch.displayPlayers = base.map((p) =>
      Object.assign({}, p, {
        pickSelectable: !!oidSet[p.openId]
      })
    )
    patch.pickOptions = opts
    patch.pickNeedConfirm = this._pickNeedConfirm(mode)
    if (patch.pickHint == null || patch.pickHint === '') {
      patch.pickHint = this.data.pickHint || this._pickHintForMode(mode)
    }
  },
  _applySyncResult(r) {
    const res = r || {}
    if (res.errMsg) {
      console.warn('[werewolf syncState]', res.errMsg)
      return
    }
    if (res.myOpenId) {
      this._storeMyOpenId(res.myOpenId)
    }
    const patch = {}
    if (res.state) {
      const d = res.state
      const im = SIZES.indexOf(d.maxPlayers)
      patch.pub = d
      patch.roomCode = d.roomCode || this.data.roomCode
      patch.maxIndex = im >= 0 ? im : this.data.maxIndex
      patch.pzh = phZh(d.currentPhase)
      patch.memberCountLine = memberCountLine(
        (d.players && d.players.length) || 0,
        d.maxPlayers | 0
      )
    }
    if (res.view) {
      const v = res.view
      patch.view = v
      patch.rzh = v.isHost ? '主持' : (v.myRole ? roleZh(v.myRole) : '')
    }
    if (Object.keys(patch).length) {
      this.setData(patch, () => {
        this.syncDisplayText()
        if (patch.pub && patch.pub.aiMode) {
          this.startAiPoll && this.startAiPoll()
        }
      })
    } else {
      this.loadView()
    }
  },
  _refreshRoomState() {
    const id = this.data.roomId
    if (!id || !wx.cloud || !ensureWerewolfCloud()) {
      this.loadView()
      return
    }
    if (!this._w) {
      this.startWatch(String(id))
    }
    callWerewolfService(
      { action: 'syncState', roomId: id },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (
            !retrySyncIfNotInRoom(this, r, this._refreshRoomState, {
              callService: callWerewolfService
            })
          ) {
            return
          }
          this._applySyncResult(r)
        },
        onError: () => {
          refreshCloudDoc('werewolf_state', id).then((d) => {
            if (d) {
              const im = SIZES.indexOf(d.maxPlayers)
              this.setData({
                pub: d,
                roomCode: d.roomCode || this.data.roomCode,
                maxIndex: im >= 0 ? im : this.data.maxIndex,
                memberCountLine: memberCountLine(
                  (d.players && d.players.length) || 0,
                  d.maxPlayers | 0
                )
              })
              this.syncDisplayText()
            }
            this.loadView()
          })
        }
      }
    )
  },
  onNickIn(e) {
    const nick = (e.detail.value || '').trim().slice(0, 12) || getFallbackNickName()
    this.setData({ nick })
  },
  onCodeIn(e) {
    this.setData({
      joinCode: (e.detail.value || '')
        .replace(/\D/g, '')
        .slice(0, 6)
    })
  },
  saveNick() {
    if (this.data.nick) {
      wx.setStorageSync('werewolf_nick', this.data.nick)
    }
  },
  doCreate() {
    if (this._opBusy) {
      return
    }
    this._opBusy = true
    this.setData({ opBusy: true })
    this.saveNick()
    wx.showLoading({ title: '创建中' })
    callWerewolfService(
      withJoinProfile({ action: 'create' }),
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = res.result || {}
          this.setData({ roomId: r.roomId, roomCode: r.roomCode || '' })
          this.afterHasRoomId(r.roomId, r)
        },
        onError: () => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
        }
      }
    )
  },
  doJoin() {
    if (this._opBusy) {
      return
    }
    this._opBusy = true
    this.setData({ opBusy: true })
    this.saveNick()
    const c = (this.data.joinCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (c.length !== 6) {
      this._opBusy = false
      this.setData({ opBusy: false })
      wx.showToast({ title: '请输入 6 位数字口令', icon: 'none' })
      return
    }
    wx.showLoading({ title: '进房' })
    callWerewolfService(
      withJoinProfile({
        action: 'join',
        roomCode: c,
        nickName: this.data.nick || getFallbackNickName()
      }),
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = res.result || {}
          this.setData({ roomId: r.roomId, roomCode: c })
          this.afterHasRoomId(r.roomId, r)
        },
        onError: () => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onDecrease() {
    const r = stepSizeIndex(this.data.maxIndex, -1)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._applyBoardSize(r.index)
  },
  onIncrease() {
    const r = stepSizeIndex(this.data.maxIndex, 1)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this._applyBoardSize(r.index)
  },
  _applyBoardSize(index) {
    const n = SIZES[index] || 6
    saveStoredSize(n)
    this.setData({ maxIndex: index }, () => {
      if (this.data.roomId) {
        this._saveMaxPlayers()
      }
    })
  },
  _saveMaxPlayers() {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const pub = this.data.pub || {}
    if (pub.status !== 'waiting') {
      return
    }
    const n = SIZES[this.data.maxIndex] || 6
    if (this._lastSavedMax === n) {
      return
    }
    this._lastSavedMax = n
    callWerewolfService(
      { action: 'setSize', roomId: this.data.roomId, maxPlayers: n },
      {
        onOk: () => {
          wx.showToast({ title: '已保存', icon: 'none' })
          this.syncDisplayText()
        },
        onError: () => {
          this._lastSavedMax = null
        }
      }
    )
  },
  doAddMockPlayer() {
    if (!this.data.view || !this.data.view.isHost || !this.data.roomId) {
      return
    }
    if (this.data.opBusy) {
      return
    }
    this.setData({ opBusy: true })
    wx.showLoading({ title: '添加中' })
    callWerewolfService(
      { action: 'addMockPlayer', roomId: this.data.roomId },
      {
        onOk: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
          wx.showToast({ title: '已添加模拟玩家', icon: 'none' })
          this.loadView()
        },
        onError: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
        }
      }
    )
  },
  doFillMockPlayers() {
    if (!this.data.view || !this.data.view.isHost || !this.data.roomId) {
      return
    }
    if (this.data.opBusy) {
      return
    }
    this.setData({ opBusy: true })
    wx.showLoading({ title: '补齐中' })
    callWerewolfService(
      { action: 'fillMockPlayers', roomId: this.data.roomId },
      {
        onOk: (res) => {
          wx.hideLoading()
          this.setData({ opBusy: false })
          const added = ((res && res.result) || {}).added | 0
          wx.showToast({
            title: added > 0 ? '已补齐 ' + added + ' 人' : '人数已够',
            icon: 'none'
          })
          this.loadView()
        },
        onError: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
        }
      }
    )
  },
  doStart() {
    const pub = this.data.pub || {}
    const players = pub.players || []
    const n = players.length
    const hostOid = pub.hostOpenId || ''
    const need = 0
    const v = this.data.view || {}
    const ctx = { playerCount: n, needPlayers: 0 }
    const checks = buildStartChecks({
      isHost: v.isHost,
      playerCount: n,
      minPlayers: 6,
      needPlayers: 0,
      kind: 'werewolf',
      ctx,
      players: pub.players || [],
      hostOpenId: hostOid,
      startVerb: '开始互动'
    })
    this.setData({ opBusy: true })
    const useAi =
      this.data.aiHostLobby && isWerewolfAIModeEnabled()
    if (useAi) {
      for (let i = 0; i < checks.length; i++) {
        if (checks[i] && checks[i].fail) {
          showStartBlockTip(checks[i])
          this.setData({ opBusy: false })
          return
        }
      }
      this.doStartAI()
      return
    }
    runStartAction({
      kind: 'werewolf',
      ctx,
      localChecks: checks,
      callService: callWerewolfService,
      payload: { action: 'start', roomId: this.data.roomId },
      loadingTitle: '开始互动',
      onSuccess: () => {
        this.loadView()
      },
      onFinally: () => {
        this.setData({ opBusy: false })
      }
    })
  },
  afterHasRoomId(roomId, joinResult) {
    this.setData({ roomId })
    onRoomEntered(this, String(roomId), 'werewolf')
    const r = joinResult || {}
    if (r.myOpenId) {
      this._storeMyOpenId(r.myOpenId)
    }
    if (r.roomCode) {
      this.setData({ roomCode: r.roomCode })
    }
    this.startWatch(String(roomId))
    ensureInRoomPoll(this, this._refreshRoomState)
    this._refreshRoomState()
  },
  startWatch(roomId) {
    this.stopWatch()
    if (!wx.cloud) {
      return
    }
    if (!ensureWerewolfCloud()) {
      return
    }
    const db = wx.cloud.database()
    this._w = db
      .collection('werewolf_state')
      .doc(String(roomId))
      .watch({
        onChange: (s) => {
          const d = s && (s.data != null ? s.data : s.doc)
          if (d) {
            const im = SIZES.indexOf(d.maxPlayers)
            this.setData({
              pub: d,
              roomCode: d.roomCode || this.data.roomCode,
              maxIndex: im >= 0 ? im : 0,
              pzh: phZh(d.currentPhase),
              memberCountLine: memberCountLine(
                (d.players && d.players.length) || 0,
                d.maxPlayers | 0
              )
            })
            this.syncDisplayText()
            if (d.aiMode && this.startAiPoll) {
              this.startAiPoll()
            }
          }
        },
        onError: (e) => {
          console.error('werewolf watch', e)
          markRoomDbWatch(this, false)
        }
      })
    markRoomDbWatch(this, true)
  },
  stopWatch() {
    if (this._w) {
      this._w.close()
      this._w = null
    }
    markRoomDbWatch(this, false)
  },
  syncDisplayText() {
    const p = this.data.pub || {}
    const v = this.data.view || {}
    const pl = (p.players || this.data.playerList || []).map((m) => ({
      openId: m.openId,
      nickName: m.nickName != null ? m.nickName : m.nick,
      avatarUrl: m.avatarUrl || '',
      profileReady: !!m.profileReady,
      isAlive: m.isAlive !== false,
      isHost: !!(p.hostOpenId && m.openId === p.hostOpenId),
      isSheriff: !!m.isSheriff
    }))
    const phase = p.status === 'waiting' ? 'waiting' : p.currentPhase || 'lobby'
    const patch = {
      wolfMatesLine:
        v.wolfMates && v.wolfMates.length ? v.wolfMates.join('、') : '',
      seerLine: v.seer && v.seer.label ? v.seer.label : '',
      publicLogText:
        p.publicLog && p.publicLog.length ? p.publicLog.join('\n') : '',
      lastNightText:
        p.lastNightReport && p.lastNightReport.length
          ? p.lastNightReport.join(' ')
          : '',
      allRolesList: (v.allRoles || []).map((hr) => ({
        o: hr.o,
        n: hr.n,
        r: roleZh(hr.r)
      })),
      playerList: pl
    }
    const needN = 0
    const hostOid = p.hostOpenId || ''
    const memberCount = pl.length
    patchLobbyUi(patch, {
      state: p,
      view: v,
      players: pl,
      phase,
      maxPlayers: needN,
      minPlayers: 6,
      isHost: v.isHost,
      myOpenId: v.myOpenId || '',
      hostOpenId: hostOid,
      hostWaiting: '⏳ 参与者到齐后点「开始互动」发牌',
      guestWaiting: '👥 等待组长开始互动'
    }, this)
    if (this.data.pickMode) {
      patch.pickMode = this.data.pickMode
      patch.pickSelOid = this.data.pickSelOid
      patch.pickHint = this.data.pickHint
      this._patchPickMembers(patch)
    }
    if (this._patchSheriffTransferUi) {
      this._patchSheriffTransferUi(patch, p, v)
    }
    this.setData(patch)
    if (p.status === 'playing' && v.isHost && phase && phase !== 'lobby' && phase !== 'waiting') {
      this._maybeAiHostNarrate(p.currentPhase || phase)
    }
  },
  _maybeAiHostNarrate(phase) {
    if (!isAiButtonsEnabled()) {
      return
    }
    if (!this.data.agentHostOn) {
      return
    }
    const v = this.data.view || {}
    if (!v.isHost || !this.data.roomId) {
      return
    }
    const ph = phase || (this.data.pub && this.data.pub.currentPhase) || ''
    if (!ph || ph === 'end' || ph === 'lobby') {
      return
    }
    const day = (this.data.pub && this.data.pub.day) | 0
    const key = ph + ':' + day
    if (this._lastAiNarrateKey === key) {
      return
    }
    this._lastAiNarrateKey = key
    const sceneMap = {
      night: 'night',
      day_announce: 'day',
      speak: 'midgame',
      vote: 'vote',
      hunter: 'hunter'
    }
    runHostNarrate(this, {
      gameKind: 'werewolf',
      roomId: this.data.roomId,
      scene: sceneMap[ph] || 'midgame',
      silent: true,
      onOk: (r) => {
        const line = String((r && (r.text || r.speakText)) || '').slice(0, 160)
        if (line) {
          this.setData({ agentSpeakLine: line })
        }
      }
    })
  },
  onToggleAgentHost() {
    const on = !this.data.agentHostOn
    this.setData({ agentHostOn: on })
    wx.showToast({ title: on ? 'AI 副主持已开' : 'AI 副主持已关', icon: 'none' })
    if (on) {
      this._lastAiNarrateKey = ''
      this._maybeAiHostNarrate(this.data.pub && this.data.pub.currentPhase)
    }
  },
  onAiHostNarrate() {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    this._lastAiNarrateKey = ''
    this._maybeAiHostNarrate(this.data.pub && this.data.pub.currentPhase)
  },
  buildPickOptions(mode) {
    const pub = this.data.pub || {}
    const selfOid = this._myOpenId()
    if (mode === 'sheriffVote') {
      const cands = (pub.sheriffCandidates || []).map((c) =>
        typeof c === 'string'
          ? { openId: c, nickName: ((pub.players || []).find((p) => p.openId === c) || {}).nickName || '候选人' }
          : c
      )
      return cands
        .filter((p) => p && p.openId && p.openId !== selfOid)
        .map((p) => ({ openId: p.openId, nickName: p.nickName || '候选人' }))
    }
    const pl =
      (this.data.displayPlayers && this.data.displayPlayers.length && this.data.displayPlayers) ||
      this.data.playerList ||
      (this.data.view && this.data.view.players) ||
      pub.players ||
      []
    return pl
      .filter((p) => {
        if (!p || !p.openId) {
          return false
        }
        if (p.isAlive === false) {
          return false
        }
        if (selfOid && p.openId === selfOid && mode !== 'hostWolf') {
          return false
        }
        return true
      })
      .map((p) => ({
        openId: p.openId,
        nickName: p.nickName != null ? p.nickName : p.nick || '参与者'
      }))
  },
  onShowPick(e) {
    const mode = (e.currentTarget.dataset.mode || '').toString()
    const opts = this.buildPickOptions(mode)
    if (!opts.length) {
      wx.showToast({ title: '暂无可选参与者', icon: 'none' })
      return
    }
    this.setData(
      {
        pickMode: mode,
        pickOptions: opts,
        pickSelOid: '',
        pickHint: this._pickHintForMode(mode),
        pickNeedConfirm: this._pickNeedConfirm(mode)
      },
      () => {
        this.syncDisplayText()
        wx.pageScrollTo({ selector: '.rg-members-card', duration: 280 }).catch(() => {})
      }
    )
  },
 onPickCancel() {
    this.setData(
      { pickMode: '', pickOptions: [], pickSelOid: '', pickHint: '', pickNeedConfirm: false },
      () => this.syncDisplayText()
    )
  },
  onMemberPickTap(e) {
    if (!this.data.pickMode) {
      return
    }
    const ds = (e && e.currentTarget && e.currentTarget.dataset) || {}
    if (ds.selectable === false || ds.selectable === 'false') {
      return
    }
    const oid = String(ds.oid || '').trim()
    if (!oid) {
      return
    }
    this._handlePickTarget(oid)
  },
  _handlePickTarget(oid) {
    const mode = this.data.pickMode
    const opt = (this.data.pickOptions || []).find((x) => x.openId === oid)
    const name = (opt && opt.nickName) || '该参与者'
    const rid = this.data.roomId
    if (!mode || !rid) {
      return
    }
    if (this._pickNeedConfirm(mode)) {
      this.setData({ pickSelOid: oid }, () => this.syncDisplayText())
      return
    }
    if (mode === 'wolf' || mode === 'hostWolf') {
      wx.showModal({
        title: mode === 'hostWolf' ? '主持代选关注对象' : '确认夜间关注对象',
        content: name,
        success: (r) => {
          if (!r.confirm) {
            return
          }
          callWerewolfService(
            {
              action: mode === 'hostWolf' ? 'hostWolfSet' : 'wWolf',
              roomId: rid,
              targetOpenId: oid
            },
            {
              onOk: () => {
                this.onPickCancel()
                wx.showToast({ title: '已同步', icon: 'success' })
                this.loadView()
              }
            }
          )
        }
      })
      return
    }
    if (mode === 'seer') {
      callWerewolfService(
        { action: 'wSeer', roomId: rid, targetOpenId: oid },
        {
          onOk: (res) => {
            const r = res.result || {}
            wx.showModal({
              title: '查看线索',
              content:
                (r.isW ? '身份倾向：暗位侧' : '身份倾向：村民侧') +
                (r.label ? '：' + r.label : ''),
              showCancel: false
            })
            this.onPickCancel()
            this.loadView()
          }
        }
      )
    }
  },
  onPickItem(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    if (oid) {
      this._handlePickTarget(oid)
    }
  },
  onPickConfirm() {
    const oid = this.data.pickSelOid
    const mode = this.data.pickMode
    const rid = this.data.roomId
    if (!oid || !mode || !rid) {
      wx.showToast({ title: '请先选择参与者', icon: 'none' })
      return
    }
    if (mode === 'poison') {
      callWerewolfService(
        { action: 'wWitch', roomId: rid, poison: true, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            this.loadView()
          }
        }
      )
      return
    }
    if (mode === 'vote') {
      callWerewolfService(
        { action: 'vote', roomId: rid, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            wx.showToast({ title: '已投票', icon: 'success' })
            this.loadView()
          }
        }
      )
      return
    }
    if (mode === 'hunter') {
      callWerewolfService(
        { action: 'hunterShot', roomId: rid, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            this.loadView()
          }
        }
      )
      return
    }
    if (mode === 'guard') {
      callWerewolfService(
        { action: 'wGuard', roomId: rid, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            wx.showToast({ title: '已守护', icon: 'success' })
            this.loadView()
          }
        }
      )
      return
    }
    if (mode === 'sheriffVote') {
      callWerewolfService(
        { action: 'sheriffVote', roomId: rid, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            wx.showToast({ title: '已投警徽', icon: 'success' })
            this.loadView()
          }
        }
      )
      return
    }
    if (mode === 'whiteWolf') {
      callWerewolfService(
        { action: 'whiteWolfBoom', roomId: rid, targetOpenId: oid },
        {
          onOk: () => {
            this.onPickCancel()
            this.loadView()
          }
        }
      )
    }
  },
  _applyGetView(v) {
    if (!v || !v.roomCode) {
      this.setData({
        view: v,
        rzh: v && v.isHost ? '主持' : (v && v.myRole ? roleZh(v.myRole) : '')
      })
      this.syncDisplayText()
      return
    }
    const myR = v.myRole
    const next = {
      view: v,
      rzh: v.isHost ? '主持' : (myR ? roleZh(myR) : ''),
      pzh: phZh(
        (this.data.pub && this.data.pub.currentPhase) || v.phase || 'lobby'
      )
    }
    const pl = (v.players || []).map((m) => ({
      openId: m.openId,
      nickName: m.nickName != null ? m.nickName : m.nick,
      isAlive: m.isAlive,
      seat: m.seat
    }))
    const prevPub = this.data.pub || {}
    const curPh =
      v.phase == null || v.phase === ''
        ? prevPub.currentPhase || 'lobby'
        : v.phase
    const im = SIZES.indexOf(v.maxPlayers)
    const maxP = v.maxPlayers != null ? v.maxPlayers : prevPub.maxPlayers
    next.pub = Object.assign({}, prevPub, {
      roomCode: v.roomCode || prevPub.roomCode,
      status: v.roomStatus != null ? v.roomStatus : prevPub.status,
      maxPlayers: maxP,
      currentPhase: curPh,
      day: v.day != null ? v.day | 0 : prevPub.day | 0,
      publicLog: v.publicLog || prevPub.publicLog || [],
      lastNightReport:
        v.lastNightReport != null ? v.lastNightReport : prevPub.lastNightReport,
      gameEnd: v.gameEnd != null ? v.gameEnd : prevPub.gameEnd,
      winSide: v.winSide != null ? v.winSide : prevPub.winSide,
      players: pl.length ? pl : prevPub.players || [],
      speakIndex: v.speakIndex != null ? v.speakIndex | 0 : prevPub.speakIndex | 0,
      speakOrder: v.speakOrder || prevPub.speakOrder || [],
      voteOpen: v.voteOpen != null ? !!v.voteOpen : !!prevPub.voteOpen,
      currentVotes: v.currentVotes || prevPub.currentVotes || {},
      pendingHunter:
        v.pendingHunter != null ? v.pendingHunter : prevPub.pendingHunter
    })
    next.roomCode = v.roomCode || this.data.roomCode
    if (im >= 0) {
      next.maxIndex = im
    }
    next.pzh = phZh(curPh || 'lobby')
    const pn = (next.pub.players && next.pub.players.length) || 0
    const needN = (maxP | 0) > 0 ? (maxP | 0) : 0
    next.memberCountLine =
      needN > 0
        ? memberCountLine(pn, needN)
        : memberCountLine(pn, 0, '至少 6 人可开始')
    this.setData(next)
    this.syncDisplayText()
  },
  applyTestSyncSnapshot(v) {
    this._applyGetView(v || {})
  },
  loadView() {
    const { roomId } = this.data
    if (!roomId) {
      return
    }
    callWerewolfService(
      { action: 'getView', roomId },
      {
        silent: true,
        onOk: (res) => {
          this._applyGetView(res.result || {})
        },
        onError: () => {}
      }
    )
  },
  wWitchSave() {
    callWerewolfService(
      { action: 'wWitch', roomId: this.data.roomId, save: true },
      { onOk: () => this.loadView() }
    )
  },
  hostResolveNight() {
    callWerewolfService(
      { action: 'hostResolveNight', roomId: this.data.roomId },
      { onOk: (res) => {
        if ((res.result || {}).over) {
          this.loadView()
        }
        this.loadView()
      } }
    )
  },
  hostDawn() {
    callWerewolfService(
      { action: 'hostDawnToSpeak', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  hostNext() {
    callWerewolfService(
      { action: 'hostNextSpeak', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  hostVote() {
    callWerewolfService(
      { action: 'hostStartVote', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  onSheriffRun() {
    callWerewolfService(
      { action: 'wSheriffSignup', roomId: this.data.roomId, run: true },
      { onOk: () => this.loadView() }
    )
  },
  onSheriffSkip() {
    callWerewolfService(
      { action: 'wSheriffSignup', roomId: this.data.roomId, run: false },
      { onOk: () => this.loadView() }
    )
  },
  hostSheriffToSpeak() {
    callWerewolfService(
      { action: 'hostSheriffToSpeak', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  onSheriffWithdraw() {
    if (this.onAiSheriffWithdraw) {
      this.onAiSheriffWithdraw()
      return
    }
    wx.showModal({
      title: '确认退水',
      content: '退水后放弃竞选警长，且本局不可再次上警。',
      success: (res) => {
        if (res.confirm && this._doSheriffWithdraw) this._doSheriffWithdraw()
      }
    })
  },
  hostEndSheriffWithdraw() {
    callWerewolfService(
      { action: 'hostEndSheriffWithdraw', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  hostSheriffNext() {
    callWerewolfService(
      { action: 'hostSheriffNextSpeak', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  hostResolveSheriffVote() {
    callWerewolfService(
      { action: 'hostResolveSheriffVote', roomId: this.data.roomId },
      { onOk: () => this.loadView() }
    )
  },
  hostResolveVote() {
    callWerewolfService(
      { action: 'hostResolveVote', roomId: this.data.roomId },
      { onOk: (res) => {
        this.loadView()
        if ((res.result || {}).over) {
          wx.showToast({ title: '本环节已结束', icon: 'none' })
        }
      } }
    )
  },
  doAiRecap() {
    const pub = this.data.pub || {}
    const end = pub.gameEnd || pub.winSide || '本局结束'
    runAi(this, {
      cacheTag: 'wolf-recap',
      roomId: this.data.roomId,
      round: (this.data.pub && this.data.pub.day) | 0,
      system: SYSTEM_RECAP,
      resultTitle: 'AI 战报',
      postProcess: { maxLen: 200 },
      buildPrompt: () => '秘密身份推理聚会局结束。结果：' + end + '。'
    })
  },
  doAiPoster() {
    const pub = this.data.pub || {}
    const end = pub.gameEnd || pub.winSide || '对局结束'
    runAiPoster(this, {
      buildPrompt: () => '秘密身份推理聚会战报海报。' + end + '。'
    })
  },
  onAiHostLobbySwitch(e) {
    this.setData({ aiHostLobby: !!(e.detail && e.detail.value) })
  },
  ...(function () {
    const m = Object.assign({}, werewolfAiMixin)
    delete m.data
    return m
  })()
})
