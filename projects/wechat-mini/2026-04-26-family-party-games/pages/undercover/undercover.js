const { callUndercoverService, ensureUndercoverCloud } = require('../../utils/undercoverRoomCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  showRoomBlockModal,
  runStartAction,
  explainUndercoverStartFail
} = require('../../utils/roomUi')
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
    inVoteTie: false,
    voteList: [],
    hostRoles: [],
    logText: '',
    sizeIndex: 2,
    sizeList: SIZ,
    showWord: false,
    memberCountLine: ''
  },
  onLoad(query) {
    this._justOpened = true
    const cfg = this.parseCfg(query)
    this.setData({
      nick: (wx.getStorageSync('uc_nick') || '').toString() || '参与者',
      playMode: 'v2'
    })
    if (cfg.mode === 'v2' && cfg.roomId) {
      this.setData({ roomId: String(cfg.roomId), roomCode: (cfg.roomCode || '').toString() })
      this.startWatch()
      this.loadView()
    } else if (cfg.mode === 'v2' && String(cfg.roomCode || '').length === 6) {
      this.setData({
        joinCode: String(cfg.roomCode).replace(/\D/g, '').slice(0, 6)
      })
    }
  },
  onUnload() {
    this.unwatch()
  },
  onShow() {
    if (this._justOpened) {
      this._justOpened = false
      return
    }
    if (this.data.roomId) {
      refreshCloudDoc('uc_state', this.data.roomId).then((d) => {
        if (d) {
          const pl = d.publicPlayers || []
          const mp = d.maxPlayers | 0
          const si = mp > 0 ? SIZ.indexOf(mp) : -1
          const needN = mp || SIZ[si >= 0 ? si : this.data.sizeIndex | 0] || 6
          const cph = d.currentPhase || ''
          this.setData({
            state: d,
            logText: (d.publicLog || []).join('\n'),
            sizeIndex: si >= 0 ? si : this.data.sizeIndex,
            memberCountLine: memberCountLine(pl.length, needN),
            inVote: cph === 'vote' || cph === 'vote_tie',
            inVoteTie: cph === 'vote_tie',
            inDiscuss: cph === 'discuss',
            inWord: cph === 'word',
            inWaiting: cph === 'waiting' || cph === 'lobby' || !cph
          })
        }
        this.loadView()
      })
    }
  },
  onShareAppMessage() {
    const code = (this.data.roomCode || '').toString().replace(/\D/g, '')
    let path = '/pages/index/index'
    let title = '家庭聚会助手 - 谁是卧底'
    if (code.length === 6) {
      const cfg = { mode: 'v2', roomCode: code }
      if (this.data.roomId) {
        cfg.roomId = String(this.data.roomId)
      }
      path =
        '/pages/undercover/undercover?config=' +
        encodeURIComponent(JSON.stringify(cfg))
      title = '快来一起玩谁是卧底！口令 ' + code
    }
    return {
      title,
      path,
      imageUrl: ''
    }
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
    this.setData({ sizeIndex: i })
  },
  doSetConfig() {
    if (!this.data.view || !this.data.view.isHost) {
      return
    }
    const n = SIZ[this.data.sizeIndex] || 6
    wx.showLoading({ title: '保存' })
    callUndercoverService(
      { action: 'setConfig', roomId: this.data.roomId, maxPlayers: n },
      {
        onOk: () => {
          wx.hideLoading()
        },
        onError: () => {
          wx.hideLoading()
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
    const c = (this.data.joinCode || this.data.roomCode || '')
      .toString()
      .replace(/\D/g, '')
      .slice(0, 6)
    if (c.length !== 6) {
      this._opBusy = false
      this.setData({ opBusy: false })
      wx.showToast({ title: '6位', icon: 'none' })
      return
    }
    wx.showLoading({ title: '进房' })
    callUndercoverService(
      { action: 'join', roomCode: c, nickName: this.data.nick || '参与者' },
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
          this.setData({ roomId: r.roomId, roomCode: c })
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
  doStart() {
    const st = this.data.state || {}
    const n = (st.publicPlayers && st.publicPlayers.length) || 0
    const need = (st.maxPlayers | 0) || SIZ[this.data.sizeIndex | 0] || 6
    const v = this.data.view || {}
    const ctx = { playerCount: n, needPlayers: need }
    const checks = []
    if (!v.isHost) {
      checks.push({ fail: true, title: '无权限', content: '只有组长可以发牌开始。' })
    }
    if (n < 3) {
      const box = explainUndercoverStartFail('至少 3 人', ctx)
      checks.push({ fail: true, title: box.title, content: box.content })
    }
    if (need > 0 && n < need) {
      const box = explainUndercoverStartFail('人未满' + need, ctx)
      checks.push({ fail: true, title: box.title, content: box.content })
    }
    runStartAction({
      kind: 'undercover',
      ctx,
      localChecks: checks,
      callService: callUndercoverService,
      payload: { action: 'startGame', roomId: this.data.roomId },
      loadingTitle: '发牌',
      onSuccess: () => {
        this.loadView()
      }
    })
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
          const path = {
            view: v,
            rzh: roleZh(v && v.myRole),
            voteList: (v && v.voteOptions) || [],
            hostRoles: (v && v.allRoles) || [],
            inVote: st === 'vote' || st === 'vote_tie',
            inVoteTie: st === 'vote_tie',
            inDiscuss: st === 'discuss',
            inWord: st === 'word',
            inWaiting: st === 'waiting' || st === 'lobby' || !st
          }
          const prevSt = this.data.state || {}
          const players = v.publicPlayers || prevSt.publicPlayers || []
          const mp = (v.maxPlayers | 0) || (prevSt.maxPlayers | 0) || 0
          const si = mp > 0 ? SIZ.indexOf(mp) : -1
          if (si >= 0) {
            path.sizeIndex = si
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
          path.memberCountLine =
            '当前 ' + players.length + ' / ' + needN + ' 人'
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
          const mp = d.maxPlayers | 0
          const si = mp > 0 ? SIZ.indexOf(mp) : -1
          const cph = d.currentPhase || ''
          const needN = (mp | 0) || SIZ[si >= 0 ? si : 2] || 6
          this.setData({
            state: d,
            logText: (d.publicLog || []).join('\n'),
            sizeIndex: si >= 0 ? si : 2,
            memberCountLine: '当前 ' + pl.length + ' / ' + needN + ' 人',
            inVote: cph === 'vote' || cph === 'vote_tie',
            inVoteTie: cph === 'vote_tie',
            inDiscuss: cph === 'discuss',
            inWord: cph === 'word',
            inWaiting: cph === 'waiting' || cph === 'lobby' || !cph
          })
          if (sig !== this._lastUcWatchSig) {
            this._lastUcWatchSig = sig
            this.loadView()
          }
        },
        onError: (err) => {
          console.error('[uc_state watch]', err)
        }
      })
  },
})
