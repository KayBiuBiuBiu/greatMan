const {
  callWerewolfService,
  ensureWerewolfCloud
} = require('../../utils/werewolfCloud')
const {
  memberCountLine,
  refreshCloudDoc,
  runStartAction,
  explainWerewolfStartFail,
  showRoomBlockModal
} = require('../../utils/roomUi')
const SIZES = [6, 8, 10, 12]
const RZH = {
  werewolf: '暗位成员',
  seer: '线索员',
  witch: '治愈者',
  hunter: '协定者',
  villager: '村民',
  '': '—'
}
const PZH = {
  lobby: '大厅',
  night: '夜间',
  day_announce: '天亮了',
  speak: '发言',
  vote: '投票',
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
    wolfMatesLine: '',
    seerLine: '',
    publicLogText: '',
    lastNightText: '',
    allRolesList: [],
    playerList: [],
    memberCountLine: ''
  },
  onLoad(q) {
    this._justOpened = true
    const title = decodeURIComponent(q.title || '秘密身份推理（聚会版）')
    const nick0 = (wx.getStorageSync('werewolf_nick') || '').toString()
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
    this.setData({
      title,
      nick: nick0,
      joinCode: code
    })
    if (roomId0) {
      this.setData({
        roomId: roomId0,
        roomCode: (config.roomCode || '').toString() || this.data.roomCode
      })
      this.afterHasRoomId(roomId0)
    } else if (code.length === 6) {
      this.setData({ roomId: '', roomCode: code })
    }
  },
  onUnload() {
    this.stopWatch()
  },
  onShow() {
    if (this._justOpened) {
      this._justOpened = false
      return
    }
    if (this.data.roomId) {
      this._refreshRoomState()
    }
  },
  onShareAppMessage() {
    const code = (this.data.roomCode || (this.data.pub && this.data.pub.roomCode) || '')
      .toString()
      .replace(/\D/g, '')
    let path = '/pages/index/index'
    let title = '家庭聚会助手 - 秘密身份推理'
    if (code.length === 6) {
      const cfg = { roomCode: code }
      if (this.data.roomId) {
        cfg.roomId = String(this.data.roomId)
      }
      path =
        '/pages/werewolf/werewolf?config=' + encodeURIComponent(JSON.stringify(cfg))
      title = '一起来玩身份推理！口令 ' + code
    }
    return { title, path, imageUrl: '' }
  },
  _refreshRoomState() {
    const id = this.data.roomId
    if (!id || !wx.cloud || !ensureWerewolfCloud()) {
      this.loadView()
      return
    }
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
  },
  onNickIn(e) {
    const nick = (e.detail.value || '').trim().slice(0, 12) || '参与者'
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
      { action: 'create' },
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = res.result || {}
          this.setData({ roomId: r.roomId, roomCode: r.roomCode || '' })
          this.afterHasRoomId(r.roomId)
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
      wx.showToast({ title: '请填 6 位聚会组口令', icon: 'none' })
      return
    }
    wx.showLoading({ title: '进房' })
    callWerewolfService(
      {
        action: 'join',
        roomCode: c,
        nickName: this.data.nick || '参与者'
      },
      {
        onOk: (res) => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
          const r = res.result || {}
          this.setData({ roomId: r.roomId, roomCode: c })
          this.afterHasRoomId(r.roomId)
        },
        onError: () => {
          wx.hideLoading()
          this._opBusy = false
          this.setData({ opBusy: false })
        }
      }
    )
  },
  onMaxChange(e) {
    const i = parseInt(e.detail.value, 10) || 0
    this.setData({ maxIndex: i })
  },
  doSetSize() {
    const n = SIZES[this.data.maxIndex] || 6
    wx.showLoading({ title: '设人数' })
    callWerewolfService(
      { action: 'setSize', roomId: this.data.roomId, maxPlayers: n },
      {
        onOk: (res) => {
          wx.hideLoading()
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },
  doStart() {
    const pub = this.data.pub || {}
    const n = (pub.players && pub.players.length) || (this.data.playerList && this.data.playerList.length) || 0
    const need = (pub.maxPlayers | 0) || SIZES[this.data.maxIndex | 0] || 6
    const v = this.data.view || {}
    const ctx = { playerCount: n, needPlayers: need }
    if (!v.isHost) {
      showRoomBlockModal('无权限', '只有组长可以发牌并开始。')
      return
    }
    if (need > 0 && n < need) {
      const box = explainWerewolfStartFail('人未满' + need + '人，暂不可开', ctx)
      showRoomBlockModal(box.title, box.content)
      return
    }
    runStartAction({
      kind: 'werewolf',
      ctx,
      callService: callWerewolfService,
      payload: { action: 'start', roomId: this.data.roomId },
      loadingTitle: '发牌',
      onSuccess: () => {
        this.loadView()
      }
    })
  },
  afterHasRoomId(roomId) {
    this.setData({ roomId })
    this.startWatch(String(roomId))
    this.loadView()
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
            this.loadView()
          }
        },
        onError: (e) => {
          console.error('werewolf watch', e)
        }
      })
  },
  stopWatch() {
    if (this._w) {
      this._w.close()
      this._w = null
    }
  },
  syncDisplayText() {
    const p = this.data.pub
    const v = this.data.view || {}
    this.setData({
      wolfMatesLine:
        v.wolfMates && v.wolfMates.length ? v.wolfMates.join('、') : '',
      seerLine: v.seer && v.seer.label ? v.seer.label : '',
      publicLogText:
        p && p.publicLog && p.publicLog.length ? p.publicLog.join('\n') : '',
      lastNightText:
        p && p.lastNightReport && p.lastNightReport.length
          ? p.lastNightReport.join(' ')
          : '',
      allRolesList: v && v.allRoles && v.allRoles.length ? v.allRoles : [],
      playerList: p && p.players ? p.players : []
    })
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
          const v = res.result || {}
          if (!v || !v.roomCode) {
            this.setData({ view: v, rzh: (v && v.myRole) ? roleZh(v.myRole) : '' })
            this.syncDisplayText()
            return
          }
          const myR = v.myRole
          const next = {
            view: v,
            rzh: myR ? roleZh(myR) : '',
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
          const needN = (maxP | 0) || SIZES[next.maxIndex | 0] || 6
          next.memberCountLine = memberCountLine(pn, needN)
          this.setData(next)
          this.syncDisplayText()
        },
        onError: () => {}
      }
    )
  },
  aliveOids() {
    const v = this.data.view || {}
    const pl = v.players || []
    return pl
      .filter((p) => p.isAlive)
      .map((p) => p.openId)
  },
  pickOid(title, oids) {
    const v = this.data.view || {}
    const pl = v.players || []
    return new Promise((resolve) => {
      if (!oids || oids.length === 0) {
        resolve(null)
        return
      }
      const names = oids.map((oid) => {
        const f = pl.find((x) => x.openId === oid)
        return f ? f.nick : oid.slice(-4)
      })
      wx.showActionSheet({
        itemList: names,
        success: (r) => {
          if (r.tapIndex === undefined) {
            resolve(null)
            return
          }
          resolve(oids[r.tapIndex] || null)
        },
        fail: () => resolve(null)
      })
    })
  },
  async wWolfTap() {
    const oid = await this.pickOid('选', this.aliveOids())
    if (!oid) {
      return
    }
    callWerewolfService(
      { action: 'wWolf', roomId: this.data.roomId, targetOpenId: oid },
      { onOk: () => this.loadView() }
    )
  },
  async wSeerTap() {
    const selfO = (this.data.view && this.data.view.myOpenId) || ''
    const os = this.aliveOids().filter((x) => x !== selfO)
    const oid = await this.pickOid('查线索', os)
    if (!oid) {
      return
    }
    callWerewolfService(
      { action: 'wSeer', roomId: this.data.roomId, targetOpenId: oid },
      {
        onOk: (res) => {
          const r = res.result || {}
          wx.showModal({
            title: '查看线索',
            content: (r.isW ? '身份倾向：暗位侧' : '身份倾向：村民侧') + (r.label ? '：' + r.label : ''),
            showCancel: false
          })
          this.loadView()
        }
      }
    )
  },
  wWitchSave() {
    callWerewolfService(
      { action: 'wWitch', roomId: this.data.roomId, save: true },
      { onOk: () => this.loadView() }
    )
  },
  async wWitchPoison() {
    const os = this.aliveOids()
    const oid = await this.pickOid('备用处置', os)
    if (!oid) {
      return
    }
    callWerewolfService(
      { action: 'wWitch', roomId: this.data.roomId, poison: true, targetOpenId: oid },
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
  async doVote() {
    const os = this.aliveOids()
    const oid = await this.pickOid('投', os)
    if (!oid) {
      return
    }
    callWerewolfService(
      { action: 'vote', roomId: this.data.roomId, targetOpenId: oid },
      { onOk: () => this.loadView() }
    )
  },
  async hunterTap() {
    const os = this.aliveOids()
    const oid = await this.pickOid('协', os)
    if (!oid) {
      return
    }
    callWerewolfService(
      { action: 'hunterShot', roomId: this.data.roomId, targetOpenId: oid },
      { onOk: () => this.loadView() }
    )
  },
})
