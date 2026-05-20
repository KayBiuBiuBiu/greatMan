const { callDrink, ensure } = require('../../utils/drinkRoomCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  buildStartChecks,
  explainDrinkStartFail
} = require('../../utils/roomUi')
const { patchLobbyUi, enrichPlayers } = require('../../utils/roomMemberUi')
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
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../../utils/roomCopy')
const { runAi, SYSTEM_DRINK_COMMENT, SYSTEM_DRINK_TASK } = require('../../utils/aiHelper')
const { runPlayerAssist, runHostTick, runGameRecap } = require('../../utils/agentHelper')
const { onRoomEntered, onRoomLeft } = require('../../utils/partyAiRoomHooks')
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
    return '🎲 倒计时中，即将揭晓响铃者'
  }
  if (ph === 'voting') {
    return '🗳️ 投票阶段，指认响铃者'
  }
  if (ph === 'result') {
    return isHost ? '📊 结果揭晓，组长可继续下一轮' : '📊 结果揭晓'
  }
  return ''
}

function enrichDrinkDisplayPlayers(list, state, myOpenId) {
  const d = state || {}
  const ph = d.phase || ''
  const votes = d.votesByVoter && typeof d.votesByVoter === 'object' ? d.votesByVoter : {}
  const hostOpenId = d.hostOpenId || ''
  const base = enrichPlayers(
    (list || []).map((p) => ({
      openId: p.openId,
      nickName: p.nickName,
      isHost: p.isHost,
      isAlive: true
    })),
    ph === 'waiting' ? 'waiting' : 'playing',
    hostOpenId
  )
  return base.map((p) => {
    const voted = votes[p.openId] != null && votes[p.openId] !== ''
    let readyLabel = p.readyLabel
    if (ph === 'voting') {
      readyLabel = voted ? '已投票' : '点击指认'
      if (myOpenId && p.openId === myOpenId && voted) {
        readyLabel = '你已投票'
      }
    }
    return Object.assign({}, p, {
      hasVoted: voted,
      ready: ph === 'voting' ? voted : p.ready,
      readyLabel
    })
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
    voteDone: false,
    pick: '',
    cdLabel: '3',
    deadLeftS: 0,
    wrongNames: '',
    roomNameEdit: '',
    myOpenId: '',
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    phaseHint: '',
    statusBannerWarn: false,
    playerProgressPct: 0,
    inWaiting: false,
    canStart: false,
    voteProgressCast: 0,
    voteProgressNeed: 0,
    voteProgressPct: 0,
    aiBusy: false,
    agentBusy: false,
    agentHostOn: true,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {}
  },
  _w: null,
  _tcd: null,
  _tdead: null,
  _tfin: null,
  _my: '',
  _vibR: 0,
  _revR: 0,
  _finR: 0,
  _revealBusy: false,
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
    if (id) {
      this._bootInRoom()
    } else {
      this.fetchMyOpenId()
    }
  },
  onUnload() {
    onRoomLeft(this)
    this.clearT()
    this.unwatch()
  },
  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    refreshAiUnlockPage(this)
    if (this.data.roomId) {
      this._refreshRoomState()
    }
  },
  onHide() {
    onPageHideUnlock(this)
    this.clearT()
  },
  onShareAppMessage() {
    return handleShareAppMessage(this, 'drink', this._shareCtx())
  },
  onShareTimeline() {
    return handleShareTimeline(this, 'drink', this._shareCtx())
  },
  onCloseAiShareModal() {
    closeAiShareModal(this)
  },
  onAiShareTimeline() {
    closeAiShareModal(this)
    showShareGuide()
  },
  unwatch() {
    if (this._w) {
      try {
        this._w.close()
      } catch (e) {}
      this._w = null
    }
  },
  clearT() {
    if (this._tcd) {
      clearInterval(this._tcd)
      this._tcd = null
    }
    if (this._tdead) {
      clearInterval(this._tdead)
      this._tdead = null
    }
    if (this._tfin) {
      clearTimeout(this._tfin)
      this._tfin = null
    }
  },
  fetchMyOpenId() {
    if (!wx.cloud || !ensure()) {
      return
    }
    callDrink(
      { action: 'getOpenId' },
      { silent: true, onOk: (res) => {
        const o = (res && res.result && res.result.openId) || ''
        this._my = o
        this.setData({ myOpenId: o || '' })
        if (this.data.state) {
          this._applyS(this.data.state)
        }
      } }
    )
  },
  _refreshRoomState() {
    if (!this.data.roomId || !wx.cloud || !ensure()) {
      return
    }
    if (!this._w) {
      this._startW()
    }
    refreshCloudDoc('drink_gameState', this.data.roomId).then((d) => {
      if (d) {
        this._applyS(d)
      }
    })
  },
  _bootInRoom() {
    if (this.data.roomId) {
      onRoomEntered(this, String(this.data.roomId), 'drink')
      refreshAiUnlockPage(this)
    }
    this.fetchMyOpenId()
    setTimeout(() => this.fetchMyOpenId(), 200)
    this._startW()
    if (wx.cloud && ensure()) {
      const db = wx.cloud.database()
      db
        .collection('drink_gameState')
        .doc(String(this.data.roomId))
        .get()
        .then((d) => {
          if (d && d.data) {
            this._applyS(d.data)
          }
        })
    }
  },
  _startW() {
    this.unwatch()
    if (!this.data.roomId || !wx.cloud || !ensure()) {
      return
    }
    const id = String(this.data.roomId)
    const db = wx.cloud.database()
    this._w = db
      .collection('drink_gameState')
      .doc(id)
      .watch({
        onChange: (s) => {
          const d = fromWatch(s)
          if (d) {
            this._applyS(d)
          }
        },
        onError: (e) => {
          console.error('watch drink', e)
        }
      })
  },
  onAiUnlockTap() {
    openAiShareModal(this)
  },
  _applyS(d) {
    const rDisp = (d && d.currentRound) | 0
    const pn = (d && d.publicPlayers && d.publicPlayers.length) || 0
    const my = this._my || (this.data.myOpenId || '')
    this._my = my
    const isHost = !!(d && d.hostOpenId && my && d.hostOpenId === my)
    const rPh = d && d.phase
    const patch = {
      state: d,
      roomNameEdit: (d && d.roomName) || '聚会组',
      roundDisp: rDisp,
      isHost
    }
    const phase = rPh || 'waiting'
    patchLobbyUi(patch, {
      state: d,
      players: (d && d.publicPlayers) || [],
      phase: phase === 'waiting' ? 'waiting' : phase,
      minPlayers: 2,
      maxPlayers: 0,
      isHost,
      hostWaiting: '⏳ 等待组长「开始本轮」',
      guestWaiting: '👥 等待组长开始本轮'
    })
    if (phase === 'waiting') {
      patch.phaseHint = patch.statusHint || buildDrinkPhaseHint(phase, isHost)
    } else {
      patch.phaseHint = buildDrinkPhaseHint(phase, isHost)
    }
    const vp = (d && d.voteProgress) || {}
    patch.voteProgressCast = vp.cast | 0
    patch.voteProgressNeed = vp.need | 0
    patch.voteProgressPct =
      patch.voteProgressNeed > 0
        ? Math.min(100, Math.round((patch.voteProgressCast / patch.voteProgressNeed) * 100))
        : 0
    patch.displayPlayers = enrichDrinkDisplayPlayers((d && d.publicPlayers) || [], d, my)
    this.setData(patch, () => {
      const iAmRinger =
        !!(my && d && d.targetOpenId && d.targetOpenId === my && rPh === 'voting')
      const m = (d && d.votesByVoter) || {}
      const myC = m[my]
      const voteDone = !!(my && myC != null && myC !== '')
      let wrongNames = ''
      if (d && d.result && d.result.wrongVoters && d.result.wrongVoters.length) {
        wrongNames = d.result.wrongVoters
          .map((w) => `${w.nickName}（${w.sips} 次）`)
          .join('、')
      }
      if (rPh === 'voting' && d && d.targetOpenId) {
        this._revR = d.currentRound | 0
      }
      this.setData({ iAmRinger, voteDone, wrongNames })
      this._maybeVibe(d)
      this._onPhaseTick(d, rPh)
      this._maybeAgentHost(d, isHost, rPh)
    })
  },
  _maybeAgentHost(d, isHost, ph) {
    if (!isHost || !this.data.agentHostOn || !this.data.roomId) {
      return
    }
    let cfg = {}
    try {
      cfg = require('../../cloud-env.js')
    } catch (e) {}
    if (cfg.agentEnabled === false || cfg.agentAutoHost === false) {
      return
    }
    if (ph !== 'countdown' && ph !== 'voting') {
      return
    }
    const now = Date.now()
    if (this._agentHostAt && now - this._agentHostAt < 2500) {
      return
    }
    this._agentHostAt = now
    runHostTick(this, {
      gameKind: 'drink',
      roomId: this.data.roomId,
      autoExecute: true,
      speak: true
    })
  },
  _maybeVibe(d) {
    const r = d && d.currentRound | 0
    if (!d || d.phase !== 'voting' || !d.targetOpenId) {
      return
    }
    if (r === this._vibR) {
      return
    }
    this._vibR = r
    const my = this._my
    if (my && d.targetOpenId === my) {
      this._ringerVibrate()
    }
  },
  /**
   * 仅短震、不播放任何音频
   */
  _ringerVibrate() {
    for (let k = 0; k < 3; k += 1) {
      setTimeout(() => {
        try {
          wx.vibrateShort()
        } catch (e) {}
      }, k * 150)
    }
  },
  _onPhaseTick(d, ph) {
    this.clearT()
    if (!d) {
      return
    }
    if (ph === 'countdown' && d.countdownEndsAt) {
      const endT = d.countdownEndsAt
      this._tcd = setInterval(() => {
        const st2 = this.data.state
        if (!st2 || st2.phase !== 'countdown') {
          return
        }
        const remS = (endT - Date.now()) / 1000
        if (remS > 0) {
          const s = Math.min(3, Math.max(1, Math.ceil(remS)))
          const m = { 1: '1', 2: '2', 3: '3' }
          this.setData({ cdLabel: m[s] || String(s) })
        } else {
          this.setData({ cdLabel: 'Go！' })
        }
        if (Date.now() + 20 >= endT) {
          this._tryReveal()
        }
      }, 90)
    } else if (ph === 'voting' && d.votingDeadline) {
      this._tdead = setInterval(() => {
        const st2 = this.data.state
        if (!st2 || st2.phase !== 'voting') {
          return
        }
        const n = st2.votingDeadline
        const r = st2.currentRound | 0
        const left = Math.max(0, ((n - Date.now()) / 1000) | 0)
        this.setData({ deadLeftS: left })
        if (st2.voteProgress && st2.voteProgress.cast >= st2.voteProgress.need) {
          this._tryFin(r, true)
        } else if (Date.now() + 300 >= n) {
          this._tryFin(r, true)
        }
      }, 350)
      const n0 = d.votingDeadline
      const left0 = Math.max(0, ((n0 - Date.now()) / 1000) | 0)
      this.setData({ deadLeftS: left0 })
    } else {
      this.setData({ deadLeftS: 0, cdLabel: '3' })
    }
  },
  _tryReveal() {
    const d = this.data.state
    if (!d || d.phase !== 'countdown' || this._revealBusy) {
      return
    }
    if (Date.now() < (d.countdownEndsAt | 0) - 100) {
      return
    }
    this._revealBusy = true
    callDrink(
      { action: 'revealRinger', roomId: this.data.roomId },
      {
        silent: true,
        onOk: () => { this._revealBusy = false },
        onError: () => { this._revealBusy = false }
      }
    )
  },
  _tryFin(round, once) {
    if (this._finR === round) {
      return
    }
    this._finR = round
    callDrink(
      { action: 'finalizeVoting', roomId: this.data.roomId, force: false },
      { silent: true, onError: () => { if (once) { this._finR = 0 } } }
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
  onRoomName(e) {
    this.setData({ roomNameEdit: String((e && e.detail && e.detail.value) || '')
      .slice(0, 20) })
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
      { action: 'create', nickName: n },
      {
        onOk: (res) => {
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          this.setData({
            roomId: String(r.roomId),
            roomCode: r.roomCode,
            roomNameEdit: '聚会组'
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
    if (!wx.cloud || !ensure()) {
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
    callDrink(
      { action: 'join', roomCode: c, nickName: n },
      {
        onOk: (res) => {
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          this.setData({ roomId: String(r.roomId), roomCode: c, joinCode: c })
          this._bootInRoom()
        },
        onError: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onCopyRoomCode() {
    const c = (this.data.state && this.data.state.roomCode) || this.data.roomCode
    copyRoomCodeToClipboard(c)
  },
  onSaveRoomName() {
    if (!this.data.isHost) {
      return
    }
    callDrink(
      { action: 'setRoomName', roomId: this.data.roomId, roomName: this.data.roomNameEdit },
      { onOk: () => wx.showToast({ title: '已保存', icon: 'none' }) }
    )
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
    if (ph === 'countdown' || ph === 'voting') {
      const box = explainDrinkStartFail('请先结束或等待本回合', ctx)
      extra.push({ fail: true, title: box.title, content: box.content })
    }
    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'drink',
      ctx,
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
      onSuccess: () => {
        this._finR = 0
      },
      onFinally: () => {
        this.setData({ opBusy: false })
      }
    })
  },
  onForceEnd() {
    this.setData({ opBusy: true })
    callDrink(
      { action: 'finalizeVoting', roomId: this.data.roomId, force: true },
      { onOk: () => { this.setData({ opBusy: false }) },
        onError: () => { this.setData({ opBusy: false }) } }
    )
  },
  onNextRound() {
    this.setData({ opBusy: true })
    callDrink(
      { action: 'nextRound', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ opBusy: false })
          this._finR = 0
          this._vibR = 0
          this._revR = 0
        },
        onError: () => { this.setData({ opBusy: false }) }
      }
    )
  },
  onMemberVoteTap(e) {
    const oid = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.oid) || ''
    if (!oid) {
      return
    }
    this.submitMyVote(oid)
  },
  submitMyVote(toOpenId) {
    const oid = toOpenId || this.data.pick
    const st = this.data.state
    if (!oid || !st || st.phase !== 'voting' || this.data.voteDone || this.data.opBusy) {
      return
    }
    this.setData({ pick: oid, opBusy: true })
    callDrink(
      { action: 'submitVote', roomId: this.data.roomId, toOpenId: oid },
      {
        onOk: () => {
          this.setData({ opBusy: false, voteDone: true })
        },
        onError: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onAbstain() {
    if (this.data.voteDone || this.data.opBusy) {
      return
    }
    this.setData({ opBusy: true })
    callDrink(
      { action: 'submitAbstain', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ opBusy: false, voteDone: true, pick: '' })
        },
        onError: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },
  _resultCtx() {
    const st = this.data.state || {}
    const r = st.result || {}
    const wrong = (r.wrongVoters || [])
      .map((w) => w.nickName + '(' + (w.sips | 0) + '次任务)')
      .join('、')
    return {
      target: r.targetNick || st.targetNick || '响铃者',
      targetSips: r.targetSips | 0,
      wrong: wrong || '无'
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
        `趣味抽签本轮结束。响铃者「${c.target}」得${c.targetSips}票。投错的人：${c.wrong}。`
    })
  },
  onAiFunTask() {
    if (!ensureAiUnlock(LEVEL.GEN, 'AI 趣味任务', this)) {
      return
    }
    const c = this._resultCtx()
    runAi(this, {
      cacheTag: 'drink-task',
      roomId: this.data.roomId,
      round: (this.data.state && this.data.state.currentRound) | 0,
      system: SYSTEM_DRINK_TASK,
      resultTitle: 'AI 趣味任务',
      postProcess: { maxLen: 40 },
      buildPrompt: () => `适合「${c.target}」在本轮执行的轻松趣味小任务。`
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
