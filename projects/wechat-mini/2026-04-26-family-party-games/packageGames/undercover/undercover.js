const { callUndercoverService, ensureUndercoverCloud } = require('../../utils/undercoverRoomCloud')
const { enterCloudRoomOnLoad } = require('../utils/roomJoin')
const { withJoinProfile } = require('../../utils/userProfile')
const { markRoomDbWatch } = require('../../utils/cloudRealtime')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../utils/roomUi')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const {
  refreshAiUnlockPage,
  LEVEL,
  tryRedeemShareFromQuery,
  onPageShowUnlock,
  onPageHideUnlock,
  closeAiShareModal,
  showShareGuide,
  openAiShareModal
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../utils/roomCopy')
const {
  runAi,
  runAiPoster,
  validateUndercoverPair,
  showAiModal,
  SYSTEM_UNDERCOVER_PAIR,
  SYSTEM_RECAP
} = require('../utils/aiHelper')
const { runPlayerAssist, runGameRecap } = require('../../utils/agentHelper')
const { runEnhancedAgentMenu } = require('../utils/aiHost')
const { buildShareCardPageUrl } = require('../../utils/shareCard')
const { patchLobbyUi } = require('../utils/roomMemberUi')
const { overlayLobbyProfileReady } = require('../utils/roomLobbyReady')
const { stepIndex, vibrateBoundary } = require('../../utils/listStepper')
const UC_SIZE_HINT = '人数 4～12，需凑满开局'
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const {
  storeMyOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const lobbyReady = require('../utils/roomLobbyReady')
const UC_OPENID_KEY = 'uc_my_open_id'
const SIZ = [4, 5, 6, 7, 8, 9, 10, 11, 12]
const WORD_SOURCE_OPTIONS = ['系统词库', 'AI 词对']
const WORD_SOURCE_VALUES = ['system', 'ai']

function ucSettingsDisplay(data) {
  const d = data || {}
  const ws = d.wordSource || 'system'
  let wordSourceIdx = WORD_SOURCE_VALUES.indexOf(ws)
  if (wordSourceIdx < 0) {
    wordSourceIdx = 0
  }
  return {
    wordSourceOptions: WORD_SOURCE_OPTIONS,
    wordSourceIdx,
    wordSourceLabel: WORD_SOURCE_OPTIONS[wordSourceIdx] || WORD_SOURCE_OPTIONS[0]
  }
}

function mergePlayerProfileReady(viewPlayers, statePlayers) {
  const src = statePlayers || []
  return (viewPlayers || []).map((p) => {
    const sp = src.find((x) => x && x.openId === p.openId)
    if (!sp || sp.profileReady == null) {
      return p
    }
    return Object.assign({}, p, { profileReady: !!sp.profileReady })
  })
}

function patchUcMemberDisplay(patch, phase, players, page, myOpenId) {
  const ph = phase || 'waiting'
  const inLobby = ph === 'waiting' || ph === 'lobby' || !ph
  const inWord = ph === 'word'
  const src = overlayLobbyProfileReady(players || [], myOpenId, page)
  patch.displayPlayers = (patch.displayPlayers || []).map((p) => {
    const raw = src.find((x) => x && x.openId === p.openId) || p
    let ready = false
    if (inLobby) {
      ready = !!p.isHost || !!raw.profileReady
    } else if (inWord) {
      ready = !!raw.wordAck
    } else if (ph !== 'ended') {
      ready = raw.isAlive !== false
    }
    return Object.assign({}, p, { ready, readyLabel: '' })
  })
}

Page({
  data: {
    opBusy: false,
    playMode: 'v2',
    roomId: '',
    roomCode: '',
    joinCode: '',
    nick: '',
    state: null,
    view: {},
    inVote: false,
    inDiscuss: false,
    inWord: false,
    inWaiting: true,
    inPlaying: false,
    inVoteTie: false,
    voteList: [],
    votePickOid: '',
    hostRoles: [],
    logText: '',
    sizeIndex: 2,
    sizeList: SIZ,
    ucSizeHint: UC_SIZE_HINT,
    showWord: false,
    memberCountLine: '',
    playerProgressPct: 0,
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    canStart: false,
    wordSource: 'system',
    wordSourceOptions: WORD_SOURCE_OPTIONS,
    wordSourceIdx: 0,
    wordSourceLabel: WORD_SOURCE_OPTIONS[0],
    aiPreviewPair: null,
    aiBusy: false,
    agentBusy: false,
    aiDiffIdx: 1,
    aiDiffLabels: ['简单', '中等', '困难'],
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    showUserInfoModal: false,
    lobbySelfReady: false,
    shareCopy: {}
  },
  _shareCtx() {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.state && this.data.state.roomCode)
    }
  },
  onLoad(query) {
    enableShareMenus()
    tryRedeemShareFromQuery(query || {})
    this._justOpened = true
    const cfg = this.parseCfg(query)
    this.setData({
      nick: (wx.getStorageSync('uc_nick') || '').toString() || '参与者',
      playMode: 'v2'
    })
    if (cfg.mode === 'v2' && cfg.roomId) {
      const rid = String(cfg.roomId)
      const code = String(cfg.roomCode || '')
        .replace(/\D/g, '')
        .slice(0, 6)
      this.setData({ roomId: rid, roomCode: code, joinCode: code || this.data.joinCode })
      if (code.length === 6) {
        enterCloudRoomOnLoad(this, {
          roomId: rid,
          roomCode: code,
          callService: callUndercoverService,
          silentJoinToast: true,
          onReady: (id, jr) => {
            this.setData({ roomId: String(id), roomCode: code, joinCode: code })
            onRoomEntered(this, String(id), 'undercover')
            this._bootInRoom(jr)
          }
        })
      } else {
        onRoomEntered(this, rid, 'undercover')
        this._bootInRoom()
      }
    } else if (cfg.mode === 'v2' && String(cfg.roomCode || '').length === 6) {
      this.setData({
        joinCode: String(cfg.roomCode).replace(/\D/g, '').slice(0, 6)
      })
    }
  },
  onUnload() {
    onRoomLeft(this)
    stopInRoomPoll(this)
    this.unwatch()
  },
  onHide() {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
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
  _storeMyOpenId(oid) {
    storeMyOpenId(UC_OPENID_KEY, oid)
  },
  _bootInRoom(joinResult) {
    if (!this.data.roomId) {
      return
    }
    const r = joinResult || {}
    if (r.myOpenId) {
      this._storeMyOpenId(r.myOpenId)
    }
    this.startWatch()
    ensureInRoomPoll(this, this._refreshRoomState)
    this._refreshRoomState()
  },
  _refreshRoomState() {
    if (!this.data.roomId || !wx.cloud || !ensureUndercoverCloud()) {
      return
    }
    if (!this._w) {
      this.startWatch()
    }
    callUndercoverService(
      { action: 'syncState', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            console.warn('[uc syncState]', r.errMsg)
            return
          }
          if (!retrySyncIfNotInRoom(this, r, this._refreshRoomState, {
            callService: callUndercoverService
          })) {
            return
          }
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          if (r.state) {
            this._applyWatchState(r.state)
          }
          if (r.view) {
            const stPlayers =
              (r.state && r.state.publicPlayers) ||
              (this.data.state && this.data.state.publicPlayers) ||
              []
            if (stPlayers.length && r.view.publicPlayers) {
              r.view.publicPlayers = mergePlayerProfileReady(
                r.view.publicPlayers,
                stPlayers
              )
            }
            this._patchFromView(r.view)
          } else if (!r.state) {
            this.loadView()
          }
        },
        onError: () => {
          refreshCloudDoc('uc_state', this.data.roomId).then((d) => {
            if (d) {
              this._applyWatchState(d)
            }
            this.loadView()
          })
        }
      }
    )
  },
  _patchFromView(v) {
    const stFromState = this.data.state && this.data.state.currentPhase
    const st = stFromState || (v && v.phase)
    const flags = this._phaseFlags(st)
    const path = {
      view: v,
      voteList: (v && v.voteOptions) || [],
      votePickOid:
        (v && v.hasVoted) || !flags.inVote ? '' : this.data.votePickOid || '',
      hostRoles: (v && v.allRoles) || [],
      ...flags
    }
    const prevSt = this.data.state || {}
    const statePlayers = prevSt.publicPlayers || []
    const players = mergePlayerProfileReady(
      v.publicPlayers || statePlayers || [],
      statePlayers
    )
    const mp = (v.maxPlayers | 0) || (prevSt.maxPlayers | 0) || 0
    const si = mp > 0 ? SIZ.indexOf(mp) : -1
    if (si >= 0) {
      path.sizeIndex = si
      this._lastSavedMax = SIZ[si]
    }
    path.state = {
      currentPhase: v.phase || prevSt.currentPhase || 'waiting',
      currentRound:
        v.currentRound != null ? v.currentRound | 0 : prevSt.currentRound | 0,
      publicPlayers: players,
      publicLog: v.publicLog || prevSt.publicLog || [],
      maxPlayers: mp || prevSt.maxPlayers,
      roomCode: v.roomCode || prevSt.roomCode,
      roomId: this.data.roomId,
      voteProgress: v.voteProgress || prevSt.voteProgress || { cast: 0, need: 0 }
    }
    path.logText = (path.state.publicLog || []).join('\n')
    const idx = si >= 0 ? si : this.data.sizeIndex | 0
    const needN = (path.state.maxPlayers | 0) || SIZ[idx] || 6
    patchLobbyUi(path, {
      state: path.state,
      view: v,
      players,
      phase: path.state.currentPhase,
      maxPlayers: needN,
      minPlayers: 3,
      isHost: v.isHost
    }, this)
    patchUcMemberDisplay(path, path.state.currentPhase, players, this, v.myOpenId || '')
    this.setData(path)
    if (v.phase === 'word' && v.myWord && !v.wordAck) {
      this.setData({ showWord: true })
    }
  },
  onShareAppMessage() {
    return handleShareAppMessage(this, 'undercover', this._shareCtx())
  },
  onShareTimeline() {
    return handleShareTimeline(this, 'undercover', this._shareCtx())
  },
  _lobbyReadyCtx() {
    return {
      callService: callUndercoverService,
      roomId: this.data.roomId,
      roomCode: (this.data.state && this.data.state.roomCode) || this.data.roomCode,
      onSynced: () => this._refreshRoomState()
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
  onCopyRoomCode() {
    const c = this.data.roomCode || (this.data.state && this.data.state.roomCode)
    copyRoomCodeToClipboard(c)
  },
  parseCfg(query) {
    if (!query.config) {
      return {}
    }
    try {
      return JSON.parse(decodeURIComponent(query.config))
    } catch (e) {
      return {}
    }
  },
  _phaseFlags(cph) {
    const ph = cph || 'waiting'
    return {
      inVote: ph === 'vote' || ph === 'vote_tie',
      inVoteTie: ph === 'vote_tie',
      inDiscuss: ph === 'discuss',
      inWord: ph === 'word',
      inWaiting: ph === 'waiting' || ph === 'lobby' || !ph,
      inPlaying: ph !== 'waiting' && ph !== 'lobby' && !!ph && ph !== 'ended'
    }
  },
  _applyWatchState(d) {
    const pl = d.publicPlayers || []
    const mp = d.maxPlayers | 0
    const si = mp > 0 ? SIZ.indexOf(mp) : -1
    const cph = d.currentPhase || ''
    const flags = this._phaseFlags(cph)
    const needN = (mp | 0) || SIZ[si >= 0 ? si : this.data.sizeIndex | 0] || 6
    const view = this.data.view || {}
    const patch = {
      state: d,
      logText: (d.publicLog || []).join('\n'),
      sizeIndex: si >= 0 ? si : this.data.sizeIndex,
      memberCountLine: memberCountLine(pl.length, needN),
      ...flags
    }
    patchLobbyUi(patch, {
      state: d,
      view,
      players: pl,
      phase: cph,
      maxPlayers: needN,
      minPlayers: 3,
      isHost: view.isHost,
      hostOpenId: d.hostOpenId || ''
    }, this)
    patchUcMemberDisplay(patch, cph, pl, this, (view && view.myOpenId) || '')
    this.setData(Object.assign(patch, ucSettingsDisplay(Object.assign({}, this.data, patch))))
  },
  onWordSourceChange(e) {
    const i = parseInt((e.detail && e.detail.value) || 0, 10) || 0
    const src = WORD_SOURCE_VALUES[i] || 'system'
    const patch = {
      wordSource: src,
      wordSourceIdx: i,
      wordSourceLabel: WORD_SOURCE_OPTIONS[i] || WORD_SOURCE_OPTIONS[0]
    }
    if (src === 'system') {
      patch.aiPreviewPair = null
    }
    this.setData(patch)
  },
  onAiUnlockTap() {
    openAiShareModal(this)
  },
  _saveMaxPlayers() {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const st = this.data.state || {}
    const ph = st.currentPhase || (this.data.view && this.data.view.phase) || 'waiting'
    if (ph !== 'waiting' && ph !== 'lobby' && ph) {
      return
    }
    const n = SIZ[this.data.sizeIndex] || 6
    if (this._lastSavedMax === n) {
      return
    }
    this._lastSavedMax = n
    callUndercoverService(
      { action: 'setConfig', roomId: this.data.roomId, maxPlayers: n },
      {
        onOk: () => {
          wx.showToast({ title: '已保存', icon: 'none' })
          const pl = (this.data.state && this.data.state.publicPlayers) || []
          const patch = {}
          patchLobbyUi(patch, {
            state: this.data.state,
            view: this.data.view,
            players: pl,
            phase: (this.data.state && this.data.state.currentPhase) || 'waiting',
            maxPlayers: n,
            minPlayers: 3,
            isHost: this.data.view && this.data.view.isHost
          }, this)
          this.setData(patch)
        },
        onError: () => {
          this._lastSavedMax = null
        }
      }
    )
  },
  onNick(e) {
    this.setData({ nick: (e.detail.value || '').trim().slice(0, 12) || '参与者' })
  },
  saveNick() {
    if (this.data.nick) {
      wx.setStorageSync('uc_nick', this.data.nick)
    }
  },
  onCode(e) {
    this.setData({ joinCode: (e.detail.value || '').replace(/\D/g, '').slice(0, 6) })
  },
  doCreate() {
    if (this._opBusy) {
      return
    }
    this._opBusy = true
    this.setData({ opBusy: true })
    this.saveNick()
    wx.showLoading({ title: '创建' })
    callUndercoverService(
      withJoinProfile({
        action: 'create',
        nickName: this.data.nick || '参与者'
      }),
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (!r.roomId) {
            wx.showToast({ title: (r && r.errMsg) || '失败', icon: 'none' })
            return
          }
          this.setData({ roomId: r.roomId, roomCode: r.roomCode || '' })
          onRoomEntered(this, String(r.roomId), 'undercover')
          this._bootInRoom(r)
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
    const c = (this.data.joinCode || '').replace(/\D/g, '').slice(0, 6)
    if (c.length !== 6) {
      wx.showToast({ title: '请输入 6 位数字口令', icon: 'none' })
      return
    }
    this._opBusy = true
    this.setData({ opBusy: true })
    this.saveNick()
    wx.showLoading({ title: '加入中' })
    callUndercoverService(
      withJoinProfile({
        action: 'join',
        roomCode: c,
        nickName: this.data.nick || '参与者'
      }),
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          this.setData({ roomId: r.roomId, roomCode: c, joinCode: c })
          onRoomEntered(this, String(r.roomId), 'undercover')
          this._bootInRoom(r)
        },
        onError: (err) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          wx.showToast({
            title: (err && err.message) || '进组失败，请检查网络',
            icon: 'none'
          })
        }
      }
    )
  },
  onSizeDecrease() {
    const r = stepIndex(this.data.sizeIndex, -1, SIZ.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData({ sizeIndex: r.index }, () => {
      this._saveMaxPlayers()
    })
  },
  onSizeIncrease() {
    const r = stepIndex(this.data.sizeIndex, 1, SIZ.length)
    if (r.atBoundary) {
      vibrateBoundary()
      return
    }
    this.setData({ sizeIndex: r.index }, () => {
      this._saveMaxPlayers()
    })
  },
  onAiDiffTap(e) {
    const i = parseInt((e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.idx) || 0, 10)
    this.setData({ aiDiffIdx: i })
  },
  doAiGenWords() {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const labels = this.data.aiDiffLabels || ['简单', '中等', '困难']
    const diff = labels[this.data.aiDiffIdx | 0] || '中等'
    const n =
      (this.data.state && this.data.state.publicPlayers && this.data.state.publicPlayers.length) ||
      SIZ[this.data.sizeIndex | 0] ||
      6
    const page = this
    runAi(this, {
      cacheTag: 'uc-pair',
      roomId: this.data.roomId,
      round: 0,
      loadingTitle: 'AI 生成词对',
      system: SYSTEM_UNDERCOVER_PAIR,
      buildPrompt: () =>
        '为' + n + '人聚会「谁是卧底」出一组词。难度：' + diff + '。',
      onOk: (text) => {
        const v = validateUndercoverPair(text)
        if (!v.ok) {
          showAiModal('解析失败', v.err + '，请重试')
          return
        }
        page.setData(
          Object.assign(
            {
              wordSource: 'ai',
              aiPreviewPair: {
                civilianWord: v.civilianWord,
                undercoverWord: v.undercoverWord
              }
            },
            ucSettingsDisplay({ wordSource: 'ai' })
          )
        )
        wx.showToast({
          title: '词对已生成，可开始互动',
          icon: 'none',
          duration: 2200
        })
      }
    })
  },
  doAiRecap() {
    const st = this.data.state || {}
    let side = '本局结束'
    if (st.winSide === 'good') {
      side = '平民侧胜'
    } else if (st.winSide === 'bad') {
      side = '卧底侧胜'
    }
    const pair = st.pair || []
    runAi(this, {
      cacheTag: 'uc-recap',
      aiUnlockTier: LEVEL.RECAP,
      aiUnlockName: 'AI 战报',
      roomId: this.data.roomId,
      round: (st && st.currentRound) | 0,
      system: SYSTEM_RECAP,
      resultTitle: 'AI 战报',
      postProcess: { maxLen: 200 },
      buildPrompt: () =>
        '谁是卧底结束。' +
        side +
        '。词对「' +
        (pair[0] || '?') +
        '」与「' +
        (pair[1] || '?') +
        '」。'
    })
  },
  doAiPoster() {
    const st = this.data.state || {}
    let side = '本局结束'
    if (st.winSide === 'good') {
      side = '平民侧胜'
    } else if (st.winSide === 'bad') {
      side = '卧底侧胜'
    }
    const pair = st.pair || []
    runAiPoster(this, {
      buildPrompt: () =>
        '谁是卧底战报海报。' + side + '。词对「' + (pair[0] || '') + '」与「' + (pair[1] || '') + '」。'
    })
  },
  doAgentAssist() {
    runPlayerAssist(this, {
      gameKind: 'undercover',
      roomId: this.data.roomId,
      playerHint: (this.data.view && this.data.view.isHost) ? '我是组长' : '我是玩家'
    })
  },

  onShowAIAssist() {
    const st = this.data.state || {}
    runEnhancedAgentMenu(this, {
      roomId: this.data.roomId,
      gameKind: 'undercover',
      gameName: '谁是卧底',
      playerHint: (this.data.view && this.data.view.isHost) ? '我是组长' : '我是玩家',
      publicLog: st.publicLog || []
    })
  },

  shareAchievement() {
    const st = this.data.state || {}
    const v = this.data.view || {}
    let detail = '本局结束'
    if (st.winSide === 'good') {
      detail = '普通词侧收束'
    } else if (st.winSide === 'bad') {
      detail = '持不同词侧收束'
    }
    const code = String(v.roomCode || this.data.roomCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    wx.navigateTo({
      url: buildShareCardPageUrl('achievement', {
        roomId: this.data.roomId,
        roomCode: code,
        gameKind: 'undercover',
        gameId: this.data.roomId,
        detail: detail
      })
    })
  },
  doAgentRecap() {
    const st = this.data.state || {}
    runGameRecap(this, {
      gameKind: 'undercover',
      gameName: '谁是卧底',
      publicLog: st.publicLog || []
    })
  },
  doPlayAgain() {
    const v = this.data.view || {}
    if (!v.isHost) {
      return
    }
    if (this.data.opBusy) {
      return
    }
    this.setData({ opBusy: true })
    wx.showLoading({ title: '正在开局…', mask: true })
    callUndercoverService(
      { action: 'playAgain', roomId: this.data.roomId },
      {
        onOk: () => {
          wx.hideLoading()
          this.setData({ opBusy: false, showWord: false, votePickOid: '' })
          this.loadView()
          wx.showToast({ title: '新一轮开始', icon: 'success' })
        },
        onError: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
        }
      }
    )
  },
  doStart() {
    const st = this.data.state || {}
    const n = (st.publicPlayers && st.publicPlayers.length) || 0
    const need = (st.maxPlayers | 0) || SIZ[this.data.sizeIndex | 0] || 6
    const v = this.data.view || {}
    const ctx = { playerCount: n, needPlayers: need }
    const checks = buildStartChecks({
      isHost: v.isHost,
      playerCount: n,
      minPlayers: 3,
      needPlayers: need,
      kind: 'undercover',
      ctx,
      players: st.publicPlayers || [],
      hostOpenId: st.hostOpenId || v.hostOpenId || '',
      startVerb: '开始互动'
    })
    const page = this
    const useAi = this.data.wordSource === 'ai'
    if (useAi) {
      const pair = this.data.aiPreviewPair
      if (!pair || !pair.civilianWord || !pair.undercoverWord) {
        wx.showToast({ title: '请先生成 AI 词对', icon: 'none' })
        return
      }
    }
    this.setData({ opBusy: true })
    const finish = () => {
      page.setData({ opBusy: false })
    }
    const runGameStart = () => {
      runStartAction({
        kind: 'undercover',
        ctx,
        localChecks: checks,
        callService: callUndercoverService,
        payload: { action: 'startGame', roomId: page.data.roomId },
        loadingTitle: '开始互动',
        onSuccess: () => {
          page.setData({ aiPreviewPair: null })
          page.loadView()
        },
        onFinally: finish
      })
    }
    if (useAi) {
      const pair = this.data.aiPreviewPair
      runStartAction({
        kind: 'undercover',
        ctx,
        localChecks: [],
        callService: callUndercoverService,
        payload: {
          action: 'setCustomPair',
          roomId: page.data.roomId,
          civilianWord: pair.civilianWord,
          undercoverWord: pair.undercoverWord
        },
        loadingTitle: '准备词对',
        onSuccess: runGameStart,
        onFinally: (ok) => {
          if (!ok) {
            finish()
          }
        }
      })
      return
    }
    runGameStart()
  },
  doAckWord() {
    callUndercoverService(
      { action: 'ackWord', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ showWord: false })
          this.loadView()
        }
      }
    )
  },
  openMyWord() {
    const w = (this.data.view && this.data.view.myWord) || ''
    if (w) {
      this.setData({ showWord: true })
    }
  },
  onMask() {},
  showWordFirst() {
    this.setData({ showWord: true })
  },
  hDiscuss() {
    this.hostAct('hostToDiscuss')
  },
  hNext() {
    this.hostAct('hostNextSpeak')
  },
  hStartVote() {
    this.hostAct('startVote')
  },
  hEndVote() {
    this.hostAct('endVote')
  },
  hTieRetry() {
    this.hostAct('startTieVote')
  },
  hostAct(act) {
    wx.showLoading()
    const d = { action: act, roomId: this.data.roomId }
    callUndercoverService(d, {
      onOk: () => {
        wx.hideLoading()
        this.loadView()
      },
      onError: () => {
        wx.hideLoading()
      }
    })
  },
  onVotePick(e) {
    const o = (e && e.currentTarget && e.currentTarget.dataset) || {}
    const oid = o.oid
    if (!oid) {
      return
    }
    this._voteOid = oid
    this.setData({ votePickOid: oid })
  },
  submitMyVote() {
    const t = this._voteOid || this.data.votePickOid
    if (!t) {
      wx.showToast({ title: '先点选一人', icon: 'none' })
      return
    }
    callUndercoverService(
      { action: 'submitVote', roomId: this.data.roomId, targetOpenId: t },
      {
        onOk: () => {
          this._voteOid = ''
          this.setData({ votePickOid: '' })
          this.loadView()
        },
        onError: () => {}
      }
    )
  },
  loadView() {
    if (!this.data.roomId) {
      return
    }
    callUndercoverService(
      { action: 'getView', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const v = (res && res.result) || {}
          this._patchFromView(v)
        }
      }
    )
  },
  unwatch() {
    if (this._w) {
      this._w.close()
      this._w = null
    }
    markRoomDbWatch(this, false)
  },
  startWatch() {
    this.unwatch()
    this._lastUcWatchSig = ''
    if (!this.data.roomId) {
      return
    }
    if (!wx.cloud) {
      return
    }
    if (!ensureUndercoverCloud()) {
      return
    }
    const db = wx.cloud.database()
    this._w = db
      .collection('uc_state')
      .doc(String(this.data.roomId))
      .watch({
        onChange: (s) => {
          const d = s && (s.data != null ? s.data : s.doc)
          if (!d) {
            return
          }
          const pl = d.publicPlayers || []
          const ackSig = pl.map((p) => (p.wordAck ? '1' : '0')).join('')
          const sig = [
            d.currentPhase || '',
            String(d.currentRound | 0),
            String(pl.length),
            String((d.voteProgress && d.voteProgress.cast) | 0),
            String((d.voteProgress && d.voteProgress.need) | 0),
            String(d.speakIndex | 0),
            String((d.publicLog || []).length),
            JSON.stringify(d.tieBreakOids || []),
            ackSig
          ].join('|')
          this._applyWatchState(d)
          if (sig !== this._lastUcWatchSig) {
            this._lastUcWatchSig = sig
            this._refreshRoomState()
          }
        },
        onError: (err) => {
          console.error('[uc_state watch]', err)
          markRoomDbWatch(this, false)
        }
      })
    markRoomDbWatch(this, true)
  }
})
