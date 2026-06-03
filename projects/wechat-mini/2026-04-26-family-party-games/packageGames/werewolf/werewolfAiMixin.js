/**
 * AI 主持模式：轮询、操作、文案（混入 werewolf Page）
 */
const { callWerewolfAIService } = require('./werewolfAICloud')
const { isWerewolfAIModeEnabled } = require('../../data/feature-flags')

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

const NIGHT_STEP_ZH = {
  wolf: '暗位行动',
  seer: '线索员查验',
  witch: '治愈者',
  guard: '守卫守护'
}

function roleZh(r) {
  return RZH[r] || r || '—'
}

function formatMmSs(sec) {
  const s = Math.max(0, sec | 0)
  const m = (s / 60) | 0
  const r = s % 60
  return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r
}

function buildAiPhaseTitle(pub) {
  const p = pub || {}
  const rem = p.remainingSeconds | 0
  const t = formatMmSs(rem)
  const ph = p.currentPhase || ''
  if (ph === 'night') {
    const step = NIGHT_STEP_ZH[p.currentNightStep] || p.currentNightStep || '夜间'
    if (p.currentNightStep === 'witch' && p.witchPhaseStep === 1) {
      return '🌙 治愈者·是否缓解 · ' + t
    }
    if (p.currentNightStep === 'witch' && p.witchPhaseStep === 2) {
      return '🌙 治愈者·备用提醒 · ' + t
    }
    return '🌙 ' + step + ' · ' + t
  }
  if (ph === 'day_announce') return '☀️ 天亮了 · ' + t
  if (ph === 'sheriff_signup') return '🎖 警长竞选 · ' + t
  if (ph === 'sheriff_withdraw') return '💧 退水 · ' + t
  if (ph === 'sheriff_speak') {
    return '🗣️ 警上发言 · ' + (p.currentSpeakerNick || '—') + ' · ' + t
  }
  if (ph === 'sheriff_vote') return '🎖 警徽投票 · ' + t
  if (ph === 'speak') {
    const who = p.currentSpeakerOpenId ? '' : ''
    return '🗣️ 发言 · ' + (p.currentSpeakerNick || '—') + ' · ' + t
  }
  if (ph === 'vote') return '🗳️ 投票 · ' + t
  if (ph === 'hunter') return '🎯 协定者 · ' + t
  if (ph === 'sheriff_transfer') return '🎖 移交警徽 · ' + t
  if (ph === 'end') return '本环节结束'
  return ph
}

const werewolfAiMixin = {
  data: {
    aiHostLobby: true,
    aiModeOn: false,
    aiPhaseTitle: '',
    aiCountdownPct: 100,
    aiView: {},
    aiActionBusy: false,
    aiAliveTargets: [],
    showSheriffTransferModal: false,
    sheriffTransferSeconds: 0,
    sheriffTransferTargets: [],
    sheriffWaitingTransfer: false
  },

  /** 警长移交 UI（AI / 手动共用） */
  _patchSheriffTransferUi(patch, pub, view) {
    const st = pub || {}
    const v = view || {}
    const fromOid = String(st.sheriffTransferFrom || '').trim()
    const myOid = String(
      v.myOpenId || (this.data.aiView && this.data.aiView.myOpenId) || ''
    ).trim()
    const ph = st.currentPhase || ''
    const canTransfer = ph === 'sheriff_transfer' && fromOid && myOid === fromOid
    const targets = (st.players || [])
      .filter((p) => p.isAlive !== false && p.openId !== fromOid)
      .map((p) => ({
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl || ''
      }))
    Object.assign(patch, {
      showSheriffTransferModal: !!canTransfer,
      sheriffTransferSeconds: st.transferRemainingSeconds | 0,
      sheriffTransferTargets: targets,
      sheriffWaitingTransfer: ph === 'sheriff_transfer' && !!fromOid && !canTransfer
    })
  },

  noop() {},

  onToggleAiHostLobby() {
    if (!isWerewolfAIModeEnabled()) {
      wx.showToast({ title: 'AI 主持未开启', icon: 'none' })
      return
    }
    this.setData({ aiHostLobby: !this.data.aiHostLobby })
  },

  _aiPollTick() {
    const id = this.data.roomId
    if (!id || !this.data.aiModeOn) return
    callWerewolfAIService(
      { action: 'getCurrentState', roomId: id },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (!r.inRoom) return
          this._applyAiState(r)
          const rem = (r.remainingSeconds | 0) || 0
          if (rem <= 0 && r.phase && r.phase !== 'end') {
            callWerewolfAIService(
              { action: 'advancePhase', roomId: id },
              { silent: true, onOk: () => this._aiPollTick() }
            )
          }
        }
      }
    )
  },

  _applyAiState(r) {
    const st = r.state || {}
    const v = r.view || {}
    const dur = st.phaseDuration | 0
    const rem = st.remainingSeconds | 0
    const pct = dur > 0 ? Math.min(100, Math.round((rem / dur) * 100)) : 0
    const myOid = String(v.myOpenId || '').trim()
    let pl = (st.players || []).filter((p) => p.isAlive !== false)
    if (myOid && v.actionHint !== 'guard_guard') {
      pl = pl.filter((p) => p.openId !== myOid)
    }
    const patch = {
      pub: Object.assign({}, this.data.pub || {}, st),
      aiView: Object.assign({}, v, {
        wolfMatesLine: (v.wolfMates || []).join('、')
      }),
      aiModeOn: !!st.aiMode,
      aiPhaseTitle: buildAiPhaseTitle(st),
      aiCountdownPct: pct,
      pzh: st.currentPhase || '',
      rzh: v.myRole ? roleZh(v.myRole) : v.isHost ? '旁观' : '',
      wolfMatesLine:
        v.wolfMates && v.wolfMates.length ? v.wolfMates.join('、') : '',
      aiAliveTargets: pl.map((p) => ({
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl || ''
      }))
    }
    if (st.gameEnd) patch.publicLogText = (st.publicLog || []).join('\n')
    else if (st.publicLog) patch.publicLogText = (st.publicLog || []).join('\n')
    this._patchSheriffTransferUi(patch, st, v)
    this.setData(patch, () => this.syncDisplayText())
    if (r.gameEnded) {
      this.stopAiPoll()
      try {
        require('../utils/partySession').markPartyFinishedOnce(this)
      } catch (e) {
        /* ignore */
      }
    }
  },

  startAiPoll() {
    this.stopAiPoll()
    this.setData({ aiModeOn: true })
    this._aiPollTick()
    this._aiPollTimer = setInterval(() => this._aiPollTick(), 1000)
  },

  stopAiPoll() {
    if (this._aiPollTimer) {
      clearInterval(this._aiPollTimer)
      this._aiPollTimer = null
    }
  },

  doStartAI() {
    const pub = this.data.pub || {}
    const players = pub.players || []
    const need = 6
    if (players.length < need) {
      wx.showToast({ title: '至少 ' + need + ' 人才能开始', icon: 'none' })
      return
    }
    this.setData({ opBusy: true })
    wx.showLoading({ title: 'AI 发牌中' })
    callWerewolfAIService(
      { action: 'startAIMode', roomId: this.data.roomId },
      {
        onOk: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
          this.startAiPoll()
          wx.showToast({ title: 'AI 主持已开始', icon: 'success' })
        },
        onError: () => {
          wx.hideLoading()
          this.setData({ opBusy: false })
        }
      }
    )
  },

  _aiReport(payload, cb) {
    if (this.data.aiActionBusy) return
    this.setData({ aiActionBusy: true })
    callWerewolfAIService(
      Object.assign({ action: 'reportAction', roomId: this.data.roomId }, payload),
      {
        onOk: (res) => {
          this.setData({ aiActionBusy: false })
          const r = (res && res.result) || {}
          if (r.label && payload.action === 'check') {
            wx.showModal({
              title: '查验结果',
              content: '身份倾向：' + r.label,
              showCancel: false
            })
          }
          this._aiPollTick()
          cb && cb(r)
        },
        onError: () => this.setData({ aiActionBusy: false })
      }
    )
  },

  onAiWolfKill(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    if (!oid) return
    this._aiReport({ role: 'wolf', action: 'kill', targetOpenId: oid })
  },

  onAiSeerCheck(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'seer', action: 'check', targetOpenId: oid })
  },

  onAiWitchSave(e) {
    const save = e.currentTarget.dataset.save === '1'
    this._aiReport({ role: 'witch', action: 'save', extra: { save } })
  },

  onAiWitchPoison(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'witch', action: 'poison', targetOpenId: oid })
  },

  onAiWitchSkipPoison() {
    this._aiReport({ role: 'witch', action: 'poison', targetOpenId: '' })
  },

  onAiGuard(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'guard', action: 'guard', targetOpenId: oid })
  },

  onAiVote(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'player', action: 'vote', targetOpenId: oid })
  },

  onAiFinishSpeak() {
    this._aiReport({ role: 'player', action: 'finishSpeak' })
  },

  onAiHunterShoot(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'hunter', action: 'shoot', targetOpenId: oid })
  },

  onAiHunterDecline() {
    this._aiReport({ role: 'hunter', action: 'shoot', extra: { decline: true } })
  },

  onAiWhiteWolfBoomStart() {
    this._aiReport({ role: 'white_wolf', action: 'self_destruct' })
  },

  onAiWhiteWolfBoomKill(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'white_wolf', action: 'boom_kill', targetOpenId: oid })
  },

  onAiSheriffRun() {
    this._aiReport({ role: 'player', action: 'sheriff_run' })
  },

  onAiSheriffSkip() {
    this._aiReport({ role: 'player', action: 'sheriff_skip' })
  },

  onAiSheriffWithdraw() {
    wx.showModal({
      title: '确认退水',
      content: '退水后放弃竞选警长，且本局不可再次上警。',
      success: (res) => {
        if (res.confirm) this._doSheriffWithdraw()
      }
    })
  },

  _doSheriffWithdraw() {
    const rid = this.data.roomId
    if (!rid || this.data.aiActionBusy) return
    this.setData({ aiActionBusy: true })
    if (this.data.aiModeOn) {
      callWerewolfAIService(
        { action: 'withdraw', roomId: rid },
        {
          onOk: () => {
            this.setData({ aiActionBusy: false })
            this._aiPollTick && this._aiPollTick()
          },
          onError: () => this.setData({ aiActionBusy: false })
        }
      )
    } else {
      const { callWerewolfService } = require('../../utils/werewolfCloud')
      callWerewolfService(
        { action: 'withdraw', roomId: rid },
        {
          onOk: () => {
            this.setData({ aiActionBusy: false })
            this._refreshRoomState && this._refreshRoomState()
          },
          onError: () => this.setData({ aiActionBusy: false })
        }
      )
    }
  },

  onAiFinishSheriffSpeak() {
    this._aiReport({ role: 'player', action: 'finishSheriffSpeak' })
  },

  onAiSheriffVote(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    this._aiReport({ role: 'player', action: 'sheriff_vote', targetOpenId: oid })
  },

  onSheriffTransferPick(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    if (!oid || this.data.aiActionBusy || this.data.opBusy) return
    const item = (this.data.sheriffTransferTargets || []).find((p) => p.openId === oid)
    const name = (item && item.nickName) || '该玩家'
    wx.showModal({
      title: '确认移交',
      content: '将警徽移交给「' + name + '」？',
      success: (res) => {
        if (res.confirm) this._doSheriffTransfer(oid)
      }
    })
  },

  onSheriffSkipTransfer() {
    if (this.data.aiActionBusy || this.data.opBusy) return
    wx.showModal({
      title: '不移交警徽',
      content: '确认放弃移交？警徽将流失，本局不再产生警长。',
      success: (res) => {
        if (res.confirm) this._doSheriffSkipTransfer()
      }
    })
  },

  _doSheriffTransfer(targetOpenId) {
    const rid = this.data.roomId
    if (!rid || !targetOpenId) return
    const busyKey = this.data.aiModeOn ? 'aiActionBusy' : 'opBusy'
    if (this.data[busyKey]) return
    this.setData({ [busyKey]: true })
    const done = () => this.setData({ [busyKey]: false })
    if (this.data.aiModeOn) {
      callWerewolfAIService(
        { action: 'transferSheriff', roomId: rid, targetOpenId },
        {
          onOk: () => {
            done()
            this._aiPollTick && this._aiPollTick()
          },
          onError: done
        }
      )
    } else {
      const { callWerewolfService } = require('../../utils/werewolfCloud')
      callWerewolfService(
        { action: 'transferSheriff', roomId: rid, targetOpenId },
        {
          onOk: () => {
            done()
            this._refreshRoomState && this._refreshRoomState()
          },
          onError: done
        }
      )
    }
  },

  _doSheriffSkipTransfer() {
    const rid = this.data.roomId
    if (!rid) return
    const busyKey = this.data.aiModeOn ? 'aiActionBusy' : 'opBusy'
    if (this.data[busyKey]) return
    this.setData({ [busyKey]: true })
    const done = () => this.setData({ [busyKey]: false })
    if (this.data.aiModeOn) {
      callWerewolfAIService(
        { action: 'skipTransfer', roomId: rid },
        {
          onOk: () => {
            done()
            this._aiPollTick && this._aiPollTick()
          },
          onError: done
        }
      )
    } else {
      const { callWerewolfService } = require('../../utils/werewolfCloud')
      callWerewolfService(
        { action: 'skipTransfer', roomId: rid },
        {
          onOk: () => {
            done()
            this._refreshRoomState && this._refreshRoomState()
          },
          onError: done
        }
      )
    }
  }
}

module.exports = {
  werewolfAiMixin,
  roleZh,
  formatMmSs,
  buildAiPhaseTitle,
  isWerewolfAIModeEnabled
}
