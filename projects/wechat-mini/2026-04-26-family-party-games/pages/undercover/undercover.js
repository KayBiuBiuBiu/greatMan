const { callUndercoverService, ensureUndercoverCloud } = require('../../utils/undercoverRoomCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks
} = require('../../utils/roomUi')
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
  showShareGuide
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6 } = require('../../utils/roomCopy')
const {
  runAi,
  runAiPoster,
  validateUndercoverPair,
  showAiModal,
  SYSTEM_UNDERCOVER_PAIR,
  SYSTEM_RECAP
} = require('../../utils/aiHelper')
const { runPlayerAssist, runGameRecap } = require('../../utils/agentHelper')
const { patchMemberDisplay } = require('../../utils/roomMemberUi')
const { onRoomEntered, onRoomLeft } = require('../../utils/partyAiRoomHooks')
const SIZ = [4, 5, 6, 7, 8, 9, 10, 11, 12]

function roleZh(r) {
  if (r === 'undercover') {
    return '卧底'
  }
  if (r === 'civilian') {
    return '平民'
  }
  return r || ''
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
    rzh: '',
    inVote: false,
    inDiscuss: false,
    inWord: false,
    inWaiting: true,
    inPlaying: false,
    inVoteTie: false,
    voteList: [],
    hostRoles: [],
    logText: '',
    sizeIndex: 2,
    sizeList: SIZ,
    showWord: false,
    memberCountLine: '',
    playerProgressPct: 0,
    displayPlayers: [],
    statusHint: '',
    wordSource: 'system',
    wordSourceLabels: ['系统词库', 'AI 词对'],
    aiPreviewPair: null,
    aiPanelOpen: false,
    aiBusy: false,
    agentBusy: false,
    aiDiffIdx: 1,
    aiDiffLabels: ['简单', '中等', '困难'],
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
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
      this.setData({ roomId: String(cfg.roomId), roomCode: (cfg.roomCode || '').toString() })
      onRoomEntered(this, String(cfg.roomId), 'undercover')
      this.startWatch()
      this.loadView()
    } else if (cfg.mode === 'v2' && String(cfg.roomCode || '').length === 6) {
      this.setData({
        joinCode: String(cfg.roomCode).replace(/\D/g, '').slice(0, 6)
      })
    }
  },
  onUnload() {
    onRoomLeft(this)
    this.unwatch()
  },
  onHide() {
    onPageHideUnlock(this)
  },
  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this._justOpened) {
      this._justOpened = false
      return
    }
    if (this.data.roomId) {
      refreshCloudDoc('uc_state', this.data.roomId).then((d) => {
        if (d) {
          this._applyWatchState(d)
        }
        this.loadView()
      })
    }
  },
  onShareAppMessage() {
    return handleShareAppMessage(this, 'undercover', this._shareCtx())
  },
  onShareTimeline() {
    return handleShareTimeline(this, 'undercover', this._shareCtx())
  },
  onCloseAiShareModal() {
    closeAiShareModal(this)
  },
  onAiShareTimeline() {
    closeAiShareModal(this)
    showShareGuide()
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
    patchMemberDisplay(patch, {
      players: pl,
      phase: cph,
      maxPlayers: needN,
      isHost: view.isHost,
    })
    this.setData(patch)
  },
  _saveMaxPlayers(silent) {
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
    if (!silent) {
      wx.showLoading({ title: '保存人数', mask: true })
    }
    callUndercoverService(
      { action: 'setConfig', roomId: this.data.roomId, maxPlayers: n },
      {
        onOk: () => {
          if (!silent) {
            wx.hideLoading()
          }
          const pl = (this.data.state && this.data.state.publicPlayers) || []
          this.setData({
            memberCountLine: memberCountLine(pl.length, n),
            playerProgressPct: computeProgressPct(pl.length, n)
          })
        },
        onError: () => {
          if (!silent) {
            wx.hideLoading()
          }
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
      { action: 'create' },
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
          this.startWatch()
          this.loadView()
        },
        onError: () => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onSizeCh(e) {
    const i = parseInt(e.detail.value, 10) || 0
    this.setData({ sizeIndex: i }, () => {
      this._saveMaxPlayers(false)
    })
  },
  onSizeStep(e) {
    const delta = parseInt((e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.delta) || 0, 10)
    const cur = this.data.sizeIndex | 0
    const next = Math.max(0, Math.min(SIZ.length - 1, cur + delta))
    if (next === cur) {
      return
    }
    this.setData({ sizeIndex: next }, () => {
      this._saveMaxPlayers(false)
    })
  },
  toggleAiPanel() {
    this.setData({ aiPanelOpen: !this.data.aiPanelOpen })
  },
  onWordSourceTap(e) {
    const src = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.src) || 'system'
    const patch = { wordSource: src }
    if (src === 'system') {
      patch.aiPreviewPair = null
    }
    this.setData(patch)
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
        page.setData({
          wordSource: 'ai',
          aiPreviewPair: {
            civilianWord: v.civilianWord,
            undercoverWord: v.undercoverWord
          },
          aiPanelOpen: true
        })
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
      playerHint: (this.data.view && this.data.view.isHost) ? '我是房主' : '我是玩家'
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
  },
  submitMyVote() {
    const t = this._voteOid
    if (!t) {
      wx.showToast({ title: '先点选一人', icon: 'none' })
      return
    }
    callUndercoverService(
      { action: 'submitVote', roomId: this.data.roomId, targetOpenId: t },
      {
        onOk: () => {
          this._voteOid = ''
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
          const stFromState = this.data.state && this.data.state.currentPhase
          const st = stFromState || v.phase
          const flags = this._phaseFlags(st)
          const path = {
            view: v,
            rzh: roleZh(v && v.myRole),
            voteList: (v && v.voteOptions) || [],
            hostRoles: (v && v.allRoles) || [],
            ...flags
          }
          const prevSt = this.data.state || {}
          const players = v.publicPlayers || prevSt.publicPlayers || []
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
          path.memberCountLine = memberCountLine(players.length, needN)
          patchMemberDisplay(path, {
            players,
            phase: path.state.currentPhase,
            maxPlayers: needN,
            isHost: v.isHost,
          })
          this.setData(path)
          if (v.phase === 'word' && v.myWord && !v.wordAck) {
            this.setData({ showWord: true })
          }
        }
      }
    )
  },
  unwatch() {
    if (this._w) {
      this._w.close()
      this._w = null
    }
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
            this.loadView()
          }
        },
        onError: (err) => {
          console.error('[uc_state watch]', err)
        }
      })
  }
})
