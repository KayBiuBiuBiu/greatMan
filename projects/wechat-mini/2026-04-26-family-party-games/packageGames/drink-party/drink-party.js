const { callDrink, ensure } = require('../../utils/drinkRoomCloud')
const { withJoinProfile } = require('../../utils/userProfile')
const { joinRoomWithUi, enterCloudRoomOnLoad } = require('../utils/roomJoin')
const {
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks,
  explainDrinkStartFail
} = require('../utils/roomUi')
const { patchLobbyUi, enrichPlayers } = require('../utils/roomMemberUi')
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
  openAiShareModal,
  ensureAiUnlock,
  LEVEL
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { runAi, SYSTEM_DRINK_COMMENT } = require('../utils/aiHelper')
const { runPlayerAssist, runGameRecap } = require('../../utils/agentHelper')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const { watchDocument, stopDevtoolsPoll, markRoomDbWatch } = require('../../utils/cloudRealtime')
const { stopLobbyPoll } = require('../utils/roomSync')
const lobbyReady = require('../utils/roomLobbyReady')
const { overlayLobbyProfileReady } = lobbyReady

/** 抽签倒计时 10 秒（与云端 COUNTDOWN_MS 一致；揭晓后才响铃/震动） */
const COUNTDOWN_UI_MS = 10000
const COUNTDOWN_SEC = 10

function defNick() {
  return (wx.getStorageSync('drink_nick') || '参与者').toString()
}
function fromWatch(s) {
  return s && (s.data != null ? s.data : s.doc)
}

function buildDrinkPhaseHint(phase, isHost) {
  const ph = phase || 'waiting'
  if (ph === 'waiting') {
    return isHost ? '⏳ 等待组长「开始本轮」' : '👥 等待组长开始本轮'
  }
  if (ph === 'countdown') {
    return '🎲 抽签中，请屏息等待…'
  }
  if (ph === 'result' || ph === 'voting') {
    return isHost ? '🍻 结果揭晓，组长可点「下一轮」' : '🍻 结果揭晓'
  }
  return ''
}

/** 统一结果展示：兼容旧云函数（投票/得票）与新玩法（drinkSips 1～10） */
function normalizeDrinkView(d) {
  if (!d) {
    return {
      state: d,
      drinkSips: 0,
      drinkResultText: '',
      targetOid: '',
      targetNick: '—',
      phase: 'waiting',
      showResult: false
    }
  }
  const ph = d.phase || 'waiting'
  const raw = d.result && typeof d.result === 'object' ? d.result : {}
  const targetOpenId = raw.targetOpenId || d.targetOpenId || ''
  const targetNick = raw.targetNick || d.targetNick || '—'
  let drinkSips = raw.drinkSips | 0
  if (!drinkSips && targetOpenId && (ph === 'result' || ph === 'voting')) {
    let seed = (d.currentRound | 0) * 997
    for (let i = 0; i < targetOpenId.length; i += 1) {
      seed += targetOpenId.charCodeAt(i)
    }
    drinkSips = 1 + (Math.abs(seed) % 10)
  }
  const result = Object.assign({}, raw, {
    targetOpenId,
    targetNick,
    drinkSips
  })
  const state = Object.assign({}, d, {
    targetOpenId,
    targetNick,
    result: ph === 'result' || ph === 'voting' ? result : d.result
  })
  let drinkResultText = ''
  let showResult = false
  if (ph === 'result' && targetNick) {
    drinkResultText = targetNick + ' 喝 ' + drinkSips + ' 口饮料'
    showResult = true
  } else if (ph === 'voting' && targetNick) {
    drinkResultText = targetNick + ' 喝 ' + drinkSips + ' 口饮料'
    showResult = true
  }
  return {
    state,
    drinkSips,
    drinkResultText,
    targetOid: targetOpenId,
    targetNick,
    phase: ph,
    showResult
  }
}

function enrichDrinkDisplayPlayers(list, state, page) {
  const d = state || {}
  const ph = d.phase || ''
  const hostOpenId = d.hostOpenId || ''
  const targetOid = (d.result && d.result.targetOpenId) || d.targetOpenId || ''
  const src = overlayLobbyProfileReady(list || [], null, page)
  const base = enrichPlayers(
    src.map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      avatarUrl: p.avatarUrl || '',
      isHost: p.isHost,
      isAlive: true,
      profileReady: !!p.profileReady
    })),
    ph === 'waiting' ? 'waiting' : 'playing',
    hostOpenId
  )
  return base.map((p) => {
    let readyLabel = p.readyLabel
    const sips = (d.result && d.result.drinkSips) | 0
    if (ph === 'result' && targetOid && p.openId === targetOid) {
      readyLabel = sips > 0 ? '喝 ' + sips + ' 口' : '本机响了'
    }
    return Object.assign({}, p, { readyLabel })
  })
}
Page({
  data: {
    opBusy: false,
    roundDisp: 0,
    roomId: '',
    roomCode: '',
    joinCode: '',
    nick: defNick(),
    state: null,
    isHost: false,
    iAmRinger: false,
    drinkSips: 0,
    drinkResultText: '',
    showDrinkResult: false,
    flowTag: 'v2-drink',
    myOpenId: '',
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    phaseHint: '',
    statusBannerWarn: false,
    playerProgressPct: 0,
    inWaiting: false,
    canStart: false,
    aiBusy: false,
    agentBusy: false,
    agentHostOn: true,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {},
    showUserInfoModal: false,
    lobbySelfReady: false,
    ringFlash: false,
    inCountdown: false,
    countdownSec: 0,
    memberPulseDuration: 400
  },
  _w: null,
  _tcd: null,
  _roomPollTimer: null,
  _ringAudio: null,
  _ringAlertKey: '',
  _my: '',
  _revealBusy: false,
  _legacyVoteSkipRound: 0,
  _countdownShownAt: 0,
  _cdRound: 0,
  _countdownEndOverride: 0,
  _countdownEndAt() {
    if (this._countdownEndOverride > 0) {
      return this._countdownEndOverride
    }
    if (this._countdownShownAt > 0) {
      return this._countdownShownAt + COUNTDOWN_UI_MS
    }
    return 0
  },
  _beginCountdown(round, _cloudEndsAt) {
    const r = round | 0
    const now = Date.now()
    const end = now + COUNTDOWN_UI_MS
    if (this._cdRound === r && this._countdownShownAt > 0 && now < this._countdownEndAt()) {
      return
    }
    this._cdRound = r
    this._countdownShownAt = now
    this._countdownEndOverride = end
  },
  _buildCountdownUiPatch() {
    const left = this._countdownSecLeft()
    const pulseMs = this._memberPulseDurationMs()
    const st = this.data.state || {}
    return {
      inCountdown: left > 0,
      countdownSec: left,
      memberPulseDuration: pulseMs,
      phaseHint:
        left > 0 ? '抽签中 · ' + left + ' 秒后揭晓' : '即将揭晓…',
      displayPlayers: enrichDrinkDisplayPlayers(st.publicPlayers || [], st, this)
    }
  },
  _countdownDone() {
    const end = this._countdownEndAt()
    return end > 0 && Date.now() >= end
  },
  _countdownSecLeft() {
    const end = this._countdownEndAt()
    if (!end) {
      return 0
    }
    return Math.max(0, Math.ceil((end - Date.now()) / 1000))
  },
  _memberPulseDurationMs() {
    const end = this._countdownEndAt()
    const start = end - COUNTDOWN_UI_MS
    if (!end || !start) {
      return 400
    }
    const total = Math.max(1, end - start)
    const elapsed = Math.min(total, Math.max(0, Date.now() - start))
    const progress = elapsed / total
    return Math.round(320 + progress * 1500)
  },
  _shareCtx() {
    return {
      roomId: this.data.roomId,
      roomCode: (this.data.state && this.data.state.roomCode) || this.data.roomCode
    }
  },
  onLoad(q) {
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    const id = (q && q.roomId) ? String(q.roomId) : ''
    const code = (q && q.roomCode) ? String(q.roomCode) : ''
    this.setData({
      joinCode: code
        .replace(/\D/g, '')
        .slice(0, 6),
      roomId: id,
      roomCode: code
    })
    if (id && this.data.joinCode.length === 6) {
      enterCloudRoomOnLoad(this, {
        roomId: id,
        roomCode: this.data.joinCode,
        callService: callDrink,
        onReady: () => this._bootInRoom()
      })
    } else if (id && this.data.joinCode.length === 6) {
      enterCloudRoomOnLoad(this, {
        roomId: id,
        roomCode: this.data.joinCode,
        callService: callDrink,
        silentJoinToast: true,
        onReady: () => this._bootInRoom()
      })
    } else if (id) {
      this._bootInRoom()
    } else {
      this.fetchMyOpenId()
    }
  },
  onUnload() {
    onRoomLeft(this)
    this.clearT()
    this._destroyRingAudio()
    stopInRoomPoll(this)
    stopLobbyPoll(this)
    this.unwatch()
  },
  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    refreshAiUnlockPage(this)
    if (this.data.roomId) {
      resumeInRoomPollOnShow(this, this._refreshRoomState)
      this._refreshRoomState()
      this.fetchMyOpenId()
    }
  },
  onHide() {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
    stopLobbyPoll(this)
    this.clearT()
  },
  onShareAppMessage() {
    return handleShareAppMessage(this, 'drink', this._shareCtx())
  },
  onShareTimeline() {
    return handleShareTimeline(this, 'drink', this._shareCtx())
  },
  _lobbyReadyCtx() {
    return {
      callService: callDrink,
      roomId: this.data.roomId,
      roomCode: (this.data.state && this.data.state.roomCode) || this.data.roomCode,
      myOpenId: this.data.myOpenId,
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
  unwatch() {
    stopDevtoolsPoll(this, '_devtoolsPollDrink')
    if (this._w) {
      try {
        this._w.close()
      } catch (e) {}
      this._w = null
    }
    markRoomDbWatch(this, false)
  },
  clearT() {
    this._stopCountdownTimer()
  },
  /** 包内音频，无需 CDN；把你的 ring.mp3 放到 assets/audio/ 即可 */
  _ringAudioSrc() {
    try {
      const cfg = require('../../cloud-env.js')
      const override = String((cfg && cfg.drinkRingAudioUrl) || '').trim()
      if (override) {
        return override
      }
    } catch (e) {}
    return '/assets/audio/ring.mp3'
  },
  _destroyRingAudio() {
    if (this._ringAudio) {
      try {
        this._ringAudio.stop()
        this._ringAudio.destroy()
      } catch (e) {}
      this._ringAudio = null
    }
  },
  _playAudioFile(opts) {
    const o = opts || {}
    const src = o.src || this._ringAudioSrc()
    if (!src || !wx.createInnerAudioContext) {
      return
    }
    this._destroyRingAudio()
    const audio = wx.createInnerAudioContext()
    audio.src = src
    audio.obeyMuteSwitch = false
    if (o.volume != null) {
      audio.volume = o.volume
    }
    audio.onEnded(() => {
      this._destroyRingAudio()
    })
    audio.onError(() => {
      this._destroyRingAudio()
    })
    this._ringAudio = audio
    try {
      audio.play()
    } catch (e) {}
  },
  /** 仅被抽中的响铃者：倒计时结束且揭晓后响铃 + 强震 */
  _playRingAlert(drinkSips) {
    const ph = (this.data.state && this.data.state.phase) || ''
    if (this.data.inCountdown || ph === 'countdown') {
      return
    }
    this.setData({ ringFlash: true })
    setTimeout(() => {
      this.setData({ ringFlash: false })
    }, 1000)
    try {
      if (wx.vibrateLong) {
        wx.vibrateLong()
      }
    } catch (e) {
      try {
        wx.vibrateShort({ type: 'heavy' })
      } catch (e2) {}
    }
    this._playAudioFile({ volume: 1 })
    const sips = drinkSips | 0 || this.data.drinkSips | 0
    const tip = sips > 0 ? '你的手机响了！喝 ' + sips + ' 口饮料' : '你的手机响了'
    wx.showToast({ title: tip, icon: 'none', duration: 3000 })
  },
  _onRingerMaybe(d, my, rPh) {
    if (rPh !== 'result' || !d || !my) {
      return
    }
    if (this.data.inCountdown || d.phase === 'countdown') {
      return
    }
    const res = d.result || {}
    const targetOid = res.targetOpenId || d.targetOpenId || ''
    if (!targetOid || targetOid !== my) {
      return
    }
    const key = String(d.currentRound | 0) + '|' + targetOid
    if (this._ringAlertKey === key) {
      return
    }
    this._ringAlertKey = key
    this._playRingAlert(res.drinkSips | 0)
  },
  _storeMyOpenId(oid) {
    const o = String(oid || '').trim()
    if (!o) {
      return
    }
    this._my = o
    if (this.data.myOpenId !== o) {
      this.setData({ myOpenId: o })
    }
    try {
      wx.setStorageSync('drink_my_open_id', o)
    } catch (e) {}
  },
  _loadStoredOpenId() {
    try {
      const o = String(wx.getStorageSync('drink_my_open_id') || '').trim()
      if (o) {
        this._storeMyOpenId(o)
      }
    } catch (e) {}
  },
  fetchMyOpenId() {
    if (!wx.cloud || !ensure()) {
      return
    }
    callDrink(
      { action: 'getOpenId' },
      {
        silent: true,
        onOk: (res) => {
          const o = (res && res.result && res.result.openId) || ''
          this._storeMyOpenId(o)
          if (this.data.state) {
            this._applyS(this.data.state)
          }
        }
      }
    )
  },
  _refreshRoomState() {
    if (!this.data.roomId || !wx.cloud || !ensure()) {
      return
    }
    if (!this._w) {
      this._startW()
    }
    callDrink(
      { action: 'syncState', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            console.warn('[drink syncState]', r.errMsg)
            return
          }
          if (
            !retrySyncIfNotInRoom(this, r, this._refreshRoomState, {
              callService: callDrink
            })
          ) {
            return
          }
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          if (r.state) {
            this._applyS(r.state)
          }
        },
        onError: () => {
          refreshCloudDoc('drink_gameState', this.data.roomId).then((d) => {
            if (d) {
              this._applyS(d)
            }
          })
        }
      }
    )
  },
  _bootInRoom() {
    if (this.data.roomId) {
      onRoomEntered(this, String(this.data.roomId), 'drink')
      refreshAiUnlockPage(this)
    }
    this._loadStoredOpenId()
    this.fetchMyOpenId()
    setTimeout(() => this.fetchMyOpenId(), 300)
    this._startW()
    ensureInRoomPoll(this, this._refreshRoomState)
    this._refreshRoomState()
  },
  _startW() {
    this.unwatch()
    if (!this.data.roomId || !wx.cloud || !ensure()) {
      return
    }
    const id = String(this.data.roomId)
    const db = wx.cloud.database()
    const onCh = (s) => {
      const d = fromWatch(s)
      if (d) {
        this._applyS(d)
      }
    }
    this._w = watchDocument(this, {
      db,
      collection: 'drink_gameState',
      docId: id,
      onChange: onCh,
      onError: (e) => {
        console.error('watch drink', e)
      },
      pollTimerKey: '_devtoolsPollDrink',
      pollFn: () => {
        if (this.data.roomId) {
          this._refreshRoomState()
        }
      },
      intervalMs: 2500
    })
  },
  onAiUnlockTap() {
    openAiShareModal(this)
  },
  _skipLegacyVoteIfNeeded(d) {
    if (!d || d.phase === 'countdown' || d.phase !== 'voting' || !d.targetOpenId || !this.data.roomId) {
      return
    }
    const r = d.currentRound | 0
    if (this._legacyVoteSkipRound === r) {
      return
    }
    this._legacyVoteSkipRound = r
    callDrink(
      { action: 'finalizeVoting', roomId: this.data.roomId, force: true },
      { silent: true }
    )
  },
  _applyS(d) {
    const norm = normalizeDrinkView(d)
    d = norm.state
    const rDisp = (d && d.currentRound) | 0
    const pn = (d && d.publicPlayers && d.publicPlayers.length) || 0
    const my = this._my || (this.data.myOpenId || '')
    this._my = my
    const isHost = !!(d && d.hostOpenId && my && d.hostOpenId === my)
    const rPh = norm.phase
    const patch = {
      state: d,
      roundDisp: rDisp,
      isHost,
      drinkSips: norm.drinkSips,
      drinkResultText: norm.drinkResultText,
      showDrinkResult: norm.showResult
    }
    if (rPh === 'countdown') {
      this._beginCountdown(rDisp, d && d.countdownEndsAt)
    } else {
      this._cdRound = 0
      this._countdownShownAt = 0
      this._countdownEndOverride = 0
    }
    const phase = rPh || 'waiting'
    patchLobbyUi(patch, {
      state: d,
      players: (d && d.publicPlayers) || [],
      phase: phase === 'waiting' ? 'waiting' : phase,
      minPlayers: 2,
      maxPlayers: 0,
      isHost,
      myOpenId: my,
      hostWaiting: '⏳ 等待组长「开始本轮」',
      guestWaiting: '👥 等待组长开始本轮'
    }, this)
    if (rPh === 'countdown') {
      Object.assign(patch, this._buildCountdownUiPatch())
    } else if (phase === 'waiting') {
      patch.phaseHint = patch.statusHint || buildDrinkPhaseHint(phase, isHost)
      patch.displayPlayers = enrichDrinkDisplayPlayers((d && d.publicPlayers) || [], d, this)
    } else {
      patch.phaseHint = buildDrinkPhaseHint(phase, isHost)
      patch.inCountdown = false
      patch.countdownSec = 0
      patch.displayPlayers = enrichDrinkDisplayPlayers((d && d.publicPlayers) || [], d, this)
    }
    if (rPh !== 'countdown' && phase !== 'waiting') {
      patch.displayPlayers =
        patch.displayPlayers ||
        enrichDrinkDisplayPlayers((d && d.publicPlayers) || [], d, this)
    }
    const targetOid = norm.targetOid
    const ringPh = rPh === 'result' || rPh === 'voting'
    this.setData(patch, () => {
      const iAmRinger = !!(my && targetOid && targetOid === my && ringPh)
      this.setData({ iAmRinger })
      if (rPh === 'voting') {
        this._skipLegacyVoteIfNeeded(d)
      }
      this._onRingerMaybe(d, my, ringPh ? 'result' : rPh)
      if (rPh === 'countdown') {
        this._startCountdownTimer()
      } else {
        this._stopCountdownTimer()
        if (this.data.inCountdown) {
          this.setData({ inCountdown: false, countdownSec: 0 })
        }
      }
    })
  },
  _stopCountdownTimer() {
    if (this._tcd) {
      clearInterval(this._tcd)
      this._tcd = null
    }
  },
  _tickCountdownOnce() {
    const st2 = this.data.state
    if (!st2 || st2.phase !== 'countdown') {
      this._stopCountdownTimer()
      return
    }
    const left = this._countdownSecLeft()
    this.setData(
      Object.assign(this._buildCountdownUiPatch(), {
        countdownSec: left
      })
    )
    if (left <= 0 && this._countdownDone()) {
      this._stopCountdownTimer()
      this._tryReveal()
    }
  },
  _startCountdownTimer() {
    this._stopCountdownTimer()
    this._tickCountdownOnce()
    this._tcd = setInterval(() => {
      this._tickCountdownOnce()
    }, 200)
  },
  _onPhaseTick(d, ph) {
    if (ph === 'countdown') {
      this._beginCountdown((d && d.currentRound) | 0, d && d.countdownEndsAt)
      this._startCountdownTimer()
    } else {
      this._stopCountdownTimer()
    }
  },
  _tryReveal() {
    const d = this.data.state
    if (!d || d.phase !== 'countdown' || this._revealBusy) {
      return
    }
    if (!this._countdownDone()) {
      return
    }
    this._revealBusy = true
    this.setData({ inCountdown: false, countdownSec: 0, phaseHint: '正在揭晓…' })
    callDrink(
      { action: 'revealRinger', roomId: this.data.roomId },
      {
        silent: true,
        onOk: () => {
          this._revealBusy = false
          this._refreshRoomState()
        },
        onError: (_err, extra) => {
          this._revealBusy = false
          const r = (extra && extra.result) || {}
          const msg = r.errMsg || '揭晓失败'
          wx.showToast({
            title: /尚未到开响|未部署|FUNCTION_NOT_FOUND/i.test(msg)
              ? '请上传部署 drinkRoomService 后重试'
              : msg + '，自动重试',
            icon: 'none',
            duration: 2800
          })
          setTimeout(() => {
            if (this.data.state && this.data.state.phase === 'countdown') {
              this._tryReveal()
            }
          }, 900)
        }
      }
    )
  },
  onNick(e) {
    this.setData({ nick: String((e && e.detail && e.detail.value) || '').slice(0, 12) })
  },
  onCode(e) {
    this.setData({ joinCode: (e && e.detail && e.detail.value || '')
      .toString()
      .replace(/\D/g, '')
      .slice(0, 6) })
  },
  doCreate() {
    if (!wx.cloud) {
      wx.showToast({ title: '需开通云', icon: 'none' })
      return
    }
    if (!ensure()) {
      return
    }
    const n = (this.data.nick || '参与者').trim().slice(0, 12) || '参与者'
    wx.setStorageSync('drink_nick', n)
    this.setData({ opBusy: true })
    callDrink(
      withJoinProfile({ action: 'create', nickName: n }),
      {
        onOk: (res) => {
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          this.setData({
            roomId: String(r.roomId),
            roomCode: r.roomCode
          })
          this._bootInRoom()
        },
        onError: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },
  doJoin() {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    if (!ensure()) {
      wx.showToast({ title: '云环境未就绪', icon: 'none' })
      return
    }
    const c = (this.data.joinCode || '')
      .replace(/\D/g, '')
      .slice(0, 6)
    if (c.length !== 6) {
      wx.showToast({ title: TOAST_ROOM_CODE_6, icon: 'none' })
      return
    }
    const n = (this.data.nick || '参与者').trim().slice(0, 12) || '参与者'
    wx.setStorageSync('drink_nick', n)
    this.setData({ opBusy: true })
    joinRoomWithUi(
      callDrink,
      { roomCode: c, nickName: n },
      {
        onOk: (r) => {
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          this.setData({ opBusy: false, roomId: String(r.roomId), roomCode: c, joinCode: c })
          this._bootInRoom()
        },
        onFail: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onCopyRoomCode() {
    const c = (this.data.state && this.data.state.roomCode) || this.data.roomCode
    copyRoomCodeToClipboard(c)
  },
  onStart() {
    const st = this.data.state
    const n = (st && st.publicPlayers && st.publicPlayers.length) || 0
    const ph = (st && st.phase) || 'waiting'
    const ctx = { playerCount: n }
    const extra = []
    if (ph === 'result') {
      const box = explainDrinkStartFail('请先点「下一轮」再开始', ctx)
      extra.push({ fail: true, title: box.title, content: box.content })
    }
    if (ph === 'countdown') {
      const box = explainDrinkStartFail('请先等待本回合抽签结束', ctx)
      extra.push({ fail: true, title: box.title, content: box.content })
    }
    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'drink',
      ctx,
      players: (st && st.publicPlayers) || [],
      hostOpenId: (st && st.hostOpenId) || '',
      startVerb: '开始本轮',
      extra
    })
    this.setData({ opBusy: true })
    runStartAction({
      kind: 'drink',
      ctx,
      localChecks: checks,
      callService: callDrink,
      payload: { action: 'startRound', roomId: this.data.roomId },
      onSuccess: (res) => {
        const r = (res && res.result) || {}
        const base = this.data.state || {}
        const nextR = (r.currentRound | 0) || (base.currentRound | 0)
        const endsAt = (r.countdownEndsAt | 0) || Date.now() + COUNTDOWN_UI_MS
        this._beginCountdown(nextR, endsAt)
        const optimistic = Object.assign({}, base, {
          phase: 'countdown',
          countdownEndsAt: this._countdownEndOverride,
          currentRound: nextR
        })
        this._applyS(optimistic)
        this._startCountdownTimer()
        this._refreshRoomState()
      },
      onFinally: () => {
        this.setData({ opBusy: false })
      }
    })
  },
  onNextRound() {
    this.setData({ opBusy: true })
    callDrink(
      { action: 'nextRound', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ opBusy: false })
          this._ringAlertKey = ''
          this._refreshRoomState()
        },
        onError: () => { this.setData({ opBusy: false }) }
      }
    )
  },
  _resultCtx() {
    const st = this.data.state || {}
    const r = st.result || {}
    const sips = r.drinkSips | 0
    return {
      target: r.targetNick || st.targetNick || '响铃者',
      drinkSips: sips
    }
  },
  onAiCommentResult() {
    if (!ensureAiUnlock(LEVEL.GEN, 'AI 解说', this)) {
      return
    }
    const c = this._resultCtx()
    runAi(this, {
      cacheTag: 'drink-comment',
      roomId: this.data.roomId,
      round: (this.data.state && this.data.state.currentRound) | 0,
      system: SYSTEM_DRINK_COMMENT,
      resultTitle: 'AI 解说',
      postProcess: { maxLen: 120 },
      buildPrompt: () =>
        `趣味抽签本轮结束。响铃者「${c.target}」需喝 ${c.drinkSips} 口饮料。`
    })
  },
  onAgentAssist() {
    runPlayerAssist(this, {
      gameKind: 'drink',
      roomId: this.data.roomId,
      playerHint: this.data.isHost ? '我是组长' : '我是参与者'
    })
  },
  onToggleAgentHost() {
    this.setData({ agentHostOn: !this.data.agentHostOn })
    wx.showToast({
      title: this.data.agentHostOn ? '副主持已开' : '副主持已关',
      icon: 'none'
    })
  },
  onAgentRecap() {
    const st = this.data.state || {}
    runGameRecap(this, {
      gameKind: 'drink',
      gameName: '趣味抽签',
      publicLog: st.publicLog || [st.result]
    })
  }
})
