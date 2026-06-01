const { callDontdoit } = require('../../utils/dontdoitCloud')
const { enterCloudRoomOnLoad, joinRoomWithUi } = require('../utils/roomJoin')
const { withJoinProfile, getFallbackNickName } = require('../../utils/userProfile')
const { memberCountLine, buildStartChecks, runStartAction } = require('../utils/roomUi')
const { mergeLocalProfileIntoPlayers, patchLobbyUi } = require('../utils/roomMemberUi')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const {
  tryRedeemShareFromQuery,
  onPageShowUnlock,
  onPageHideUnlock,
  closeAiShareModal,
  showShareGuide
} = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const {
  storeMyOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')
const lobbyReady = require('../utils/roomLobbyReady')
const { overlayLobbyProfileReady } = lobbyReady

const DDI_OPENID_KEY = 'ddi_my_open_id'
const DDI_BUILD_ID = 'dontdoit-repo-v2'
const DIFFICULTY_VALUES = ['easy', 'medium', 'hard']
const DIFFICULTY_LABELS = ['简单', '中等', '困难']
function idxOf(arr, val, fallback) {
  const i = arr.indexOf(val)
  return i >= 0 ? i : fallback
}

/** 成员列表 UI：淘汰样式、禁止动作展示 */
function enrichDdiPlayers(players, myOpenId, hostOpenId, phase, view) {
  const merged = mergeLocalProfileIntoPlayers(players || [], myOpenId)
  const st = phase || 'waiting'
  const es = (view && view.eliminatedOpenIds) || []
  return merged.map((p) => {
    const nick = (p.nickName || '参与者').trim()
    const isSelf = !!(myOpenId && p.openId === myOpenId)
    const out = !!p.isEliminated || es.indexOf(p.openId) >= 0
    const raw = String(p.displayAction || '').trim()
    const act = raw === '？？？' || raw === '???' ? '保密' : raw || '—'
    let subLabel = ''
    if (out) {
      subLabel = '已淘汰'
    } else if (st === 'waiting') {
      const host = p.isHost || (hostOpenId && p.openId === hostOpenId)
      if (host) {
        subLabel = '组长'
      } else {
        subLabel = p.profileReady ? '已准备' : '未准备'
      }
    } else if (st === 'playing') {
      subLabel = isSelf ? '你的禁止动作：保密' : '禁止：' + act
    } else if (st === 'finished') {
      subLabel = '动作：' + act
    }
    return {
      openId: p.openId,
      nickName: nick,
      avatarUrl: p.avatarUrl || '',
      isHost: !!p.isHost || !!(hostOpenId && p.openId === hostOpenId),
      isEliminated: out,
      displayAction: act,
      subLabel: subLabel,
      avatarText: nick.slice(0, 1) || '参'
    }
  })
}

Page({
  data: {
    opBusy: false,
    roomId: '',
    roomCode: '',
    joinCode: '',
    nick: '',
    view: {},
    isHost: false,
    inWaiting: true,
    inPlaying: false,
    inFinished: false,
    iAmEliminated: false,
    aliveCount: 0,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    canStart: false,
    canRestart: false,
    playerProgressPct: 0,
    difficultyLabels: DIFFICULTY_LABELS,
    difficultyIdx: 0,
    myAction: '',
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    showUserInfoModal: false,
    lobbySelfReady: false,
    shareCopy: {}
  },

  onLoad(query) {
    enableShareMenus()
    tryRedeemShareFromQuery(query || {})
    this.setData({
      nick: (wx.getStorageSync('ddi_nick') || '').toString() || getFallbackNickName()
    })
    const cfg = this._parseCfg(query)
    if (cfg.roomId) {
      const rid = String(cfg.roomId)
      const code = String(cfg.roomCode || '')
        .replace(/\D/g, '')
        .slice(0, 6)
      this.setData({ roomId: rid, roomCode: code, joinCode: code })
      if (code.length === 6) {
        enterCloudRoomOnLoad(this, {
          roomId: rid,
          roomCode: code,
          callService: callDontdoit,
          silentJoinToast: true,
          onReady: (id, jr) => {
            this.setData({ roomId: String(id), roomCode: code })
            onRoomEntered(this, String(id), 'dontdoit')
            this._bootInRoom(jr)
          }
        })
      } else {
        onRoomEntered(this, rid, 'dontdoit')
        this._bootInRoom()
      }
    } else if (cfg.roomCode && cfg.roomCode.length === 6) {
      this.setData({ joinCode: cfg.roomCode })
    }
  },

  onUnload() {
    onRoomLeft(this)
    stopInRoomPoll(this)
  },

  onHide() {
    onPageHideUnlock(this)
    stopInRoomPoll(this)
  },

  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.roomId) {
      resumeInRoomPollOnShow(this, this._refreshView)
      this._refreshView()
    }
  },

  _parseCfg(query) {
    try {
      if (query.config) {
        return JSON.parse(decodeURIComponent(query.config))
      }
    } catch (e) {}
    return {
      roomId: query.roomId || '',
      roomCode: String(query.roomCode || '').replace(/\D/g, '').slice(0, 6)
    }
  },

  _shareCtx() {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.view && this.data.view.roomCode)
    }
  },

  onShareAppMessage() {
    return handleShareAppMessage(this, 'dontdoit', this._shareCtx())
  },

  onShareTimeline() {
    return handleShareTimeline(this, 'dontdoit', this._shareCtx())
  },

  _lobbyReadyCtx() {
    return {
      callService: callDontdoit,
      roomId: this.data.roomId,
      roomCode: (this.data.view && this.data.view.roomCode) || this.data.roomCode,
      onSynced: () => this._refreshView()
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

  _storeMyOpenId(oid) {
    storeMyOpenId(DDI_OPENID_KEY, oid)
  },

  _bootInRoom(joinResult) {
    const r = joinResult || {}
    if (r.myOpenId) {
      this._storeMyOpenId(r.myOpenId)
    }
    if (r.view) {
      this._applyView(r.view, r.myOpenId)
    }
    ensureInRoomPoll(this, this._refreshView)
    this._refreshView()
  },

  _refreshView() {
    if (!this.data.roomId || !wx.cloud) {
      return
    }
    callDontdoit(
      { action: 'syncState', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            return
          }
          if (!retrySyncIfNotInRoom(this, r, this._refreshView, {
            callService: callDontdoit
          })) {
            return
          }
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          if (r.view) {
            this._applyView(r.view, r.myOpenId || r.view.myOpenId)
          }
        }
      }
    )
  },

  _applyView(v, myOpenId) {
    if (!v) {
      return
    }
    const st = v.status || 'waiting'
    const waiting = st === 'waiting'
    const playing = st === 'playing'
    const finished = st === 'finished'
    const isHost = !!(v.isHost || (v.hostOpenId && v.hostOpenId === myOpenId))
    const n = (v.players && v.players.length) || v.playerCount | 0
    const alive = v.aliveCount | 0
    const es = v.eliminatedOpenIds || []
    const iAmEliminated = es.indexOf(myOpenId) >= 0
    const cfg = v.config || {}
    const patch = {
      view: v,
      isHost: isHost,
      inWaiting: waiting,
      inPlaying: playing,
      inFinished: finished,
      iAmEliminated: iAmEliminated,
      aliveCount: alive,
      difficultyIdx: idxOf(DIFFICULTY_VALUES, cfg.difficulty, 0)
    }

    if (waiting) {
      const pl = overlayLobbyProfileReady(v.players || [], myOpenId, this)
      patchLobbyUi(patch, {
        view: v,
        players: pl,
        phase: 'waiting',
        minPlayers: 2,
        maxPlayers: 0,
        isHost: isHost,
        myOpenId: myOpenId,
        hostOpenId: v.hostOpenId,
        hostWaiting: '⏳ 人齐后点「开始挑战」发动作牌',
        guestWaiting: '👥 请点「准备」，等待组长开始'
      }, this)
      patch.statusBannerWarn = n < 2
      patch.displayPlayers = enrichDdiPlayers(pl, myOpenId, v.hostOpenId, 'waiting', v)
    } else if (playing) {
      patch.statusHint =
        '🎮 进行中：诱导别人犯规，别做自己的禁止动作（当前 ' + alive + ' 人存活）'
      patch.memberCountLine = '当前 ' + alive + ' 人'
      patch.playerProgressPct = n > 0 ? Math.round((alive / n) * 100) : 0
      patch.displayPlayers = enrichDdiPlayers(v.players, myOpenId, v.hostOpenId, 'playing', v)
    } else {
      patch.statusHint = v.survivorNames
        ? '🏆 幸存者：' + v.survivorNames + ' · 可再来一盘'
        : '本局已结束 · 可再来一盘'
      patch.memberCountLine = memberCountLine(n, 0, '至少 2 人可开新局')
      patch.canRestart = isHost && n >= 2
      patch.displayPlayers = enrichDdiPlayers(v.players, myOpenId, v.hostOpenId, 'finished', v)
    }

    this.setData(patch)
  },

  _syncConfigToCloud(done) {
    if (!this.data.isHost || !this.data.roomId) {
      if (typeof done === 'function') {
        done()
      }
      return
    }
    callDontdoit(
      {
        action: 'setConfig',
        roomId: this.data.roomId,
        difficulty: DIFFICULTY_VALUES[this.data.difficultyIdx]
      },
      {
        silent: true,
        onOk: () => {
          if (typeof done === 'function') {
            done()
          }
        },
        onError: () => {
          if (typeof done === 'function') {
            done()
          }
        }
      }
    )
  },

  onNick(e) {
    this.setData({ nick: String((e && e.detail && e.detail.value) || '').slice(0, 12) })
  },

  onCode(e) {
    this.setData({
      joinCode: String((e && e.detail && e.detail.value) || '')
        .replace(/\D/g, '')
        .slice(0, 6)
    })
  },

  onDifficultyPick(e) {
    const i = (e && e.detail && e.detail.value) | 0
    this.setData({ difficultyIdx: i }, () => this._syncConfigToCloud())
  },

  onMyActionInput(e) {
    const action = (e && e.detail && e.detail.value) || ''
    this.setData({ myAction: action })
  },

  onCopyRoomCode() {
    copyRoomCodeToClipboard(this.data.view.roomCode || this.data.roomCode)
  },

  doCreate() {
    if (!wx.cloud) {
      wx.showToast({ title: '需开通云开发', icon: 'none' })
      return
    }
    const n = (this.data.nick || getFallbackNickName()).trim().slice(0, 12) || getFallbackNickName()
    wx.setStorageSync('ddi_nick', n)
    this.setData({ opBusy: true })
    callDontdoit(withJoinProfile({ action: 'create', nickName: n }), {
      onOk: (res) => {
        this.setData({ opBusy: false })
        const r = (res && res.result) || {}
        if (!r.roomId) {
          return
        }
        if (r.myOpenId) {
          this._storeMyOpenId(r.myOpenId)
        }
        this.setData({
          roomId: String(r.roomId),
          roomCode: r.roomCode,
          joinCode: r.roomCode
        })
        onRoomEntered(this, String(r.roomId), 'dontdoit')
        this._bootInRoom(r)
      },
      onError: () => {
        this.setData({ opBusy: false })
      }
    })
  },

  doJoin() {
    const c = (this.data.joinCode || '').replace(/\D/g, '').slice(0, 6)
    if (c.length !== 6) {
      wx.showToast({ title: TOAST_ROOM_CODE_6, icon: 'none' })
      return
    }
    const n = (this.data.nick || getFallbackNickName()).trim().slice(0, 12) || getFallbackNickName()
    wx.setStorageSync('ddi_nick', n)
    this.setData({ opBusy: true })
    joinRoomWithUi(
      callDontdoit,
      { roomCode: c, nickName: n },
      {
        onOk: (r) => {
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          this.setData({ opBusy: false, roomId: String(r.roomId), roomCode: c, joinCode: c })
          onRoomEntered(this, String(r.roomId), 'dontdoit')
          this._bootInRoom(r)
        },
        onFail: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },

  _ensureCloudBuild(onReady) {
    callDontdoit(
      { action: 'ping' },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.buildId === DDI_BUILD_ID) {
            onReady && onReady()
            return
          }
          wx.showModal({
            title: '云函数版本不对',
            content:
              '请部署 dontdoitRoomService（buildId=' +
              DDI_BUILD_ID +
              '）：云端安装依赖。',
            showCancel: false
          })
        },
        onError: () => {
          wx.showModal({
            title: '云函数不可用',
            content: '请先部署 dontdoitRoomService',
            showCancel: false
          })
        }
      }
    )
  },

  onStartGame() {
    this._runStartRound({ rematch: false })
  },

  onPlayAgain() {
    this._runStartRound({ rematch: true })
  },

  _runStartRound(opts) {
    const rematch = !!(opts && opts.rematch)
    const v = this.data.view || {}
    const n = (v.players && v.players.length) || 0

    // 验证玩家是否输入了禁止动作
    if (!rematch && !this.data.myAction.trim()) {
      wx.showToast({ title: '请先输入你的禁止动作', icon: 'none' })
      return
    }

    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'headband',
      players: v.players || [],
      hostOpenId: v.hostOpenId || '',
      hostLabel: '组长',
      startVerb: rematch ? '再来一盘' : '开始挑战'
    })
    const fail = checks.find((c) => c.fail)
    if (fail) {
      wx.showModal({ title: fail.title, content: fail.content, showCancel: false })
      return
    }

    this._ensureCloudBuild(() => {
      this.setData({ opBusy: true })
      this._syncConfigToCloud(() => {
        runStartAction({
          kind: 'headband',
          ctx: { playerCount: n },
          localChecks: [],
          callService: callDontdoit,
          payload: {
            action: 'startGame',
            roomId: this.data.roomId,
            playerAction: rematch ? '' : this.data.myAction.trim()
          },
          loadingTitle: rematch ? '正在开局…' : '正在随机分配动作…',
          onSuccess: (res) => {
            const r = (res && res.result) || {}
            wx.showToast({
              title: rematch ? '新一局开始' : '动作分配完成',
              icon: 'success'
            })
            this._refreshView()
          },
          onFinally: () => {
            this.setData({ opBusy: false })
          }
        })
      })
    })
  },

  onSelfTrigger() {
    if (this.data.iAmEliminated || !this.data.inPlaying) {
      return
    }
    wx.showModal({
      title: '确认犯规？',
      content: '承认自己做了禁止动作，将被淘汰',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        this.setData({ opBusy: true })
        callDontdoit(
          { action: 'submitAction', roomId: this.data.roomId },
          {
            onOk: (res) => {
              this.setData({ opBusy: false })
              const body = (res && res.result) || {}
              if (body.finished) {
                wx.showModal({
                  title: '游戏结束',
                  content: '幸存者：' + ((body.view && body.view.survivorNames) || '—'),
                  showCancel: false,
                  success: () => this._applyView(body.view, body.view && body.view.myOpenId)
                })
                return
              }
              wx.showToast({ title: '你已淘汰', icon: 'none' })
              if (body.view) {
                this._applyView(body.view, body.view.myOpenId)
              } else {
                this._refreshView()
              }
            },
            onError: () => {
              this.setData({ opBusy: false })
            }
          }
        )
      }
    })
  },

  onEliminatePlayer(e) {
    if (!this.data.isHost || !this.data.inPlaying) {
      return
    }
    const oid = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.oid) || ''
    const nick = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.nick) || '该玩家'
    if (!oid) {
      return
    }
    wx.showModal({
      title: '淘汰 ' + nick,
      content: '确定将该玩家判为淘汰吗？',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        this.setData({ opBusy: true })
        callDontdoit(
          { action: 'eliminatePlayer', roomId: this.data.roomId, targetOpenId: oid },
          {
            onOk: (res) => {
              this.setData({ opBusy: false })
              const body = (res && res.result) || {}
              if (body.finished) {
                wx.showModal({
                  title: '游戏结束',
                  content: '幸存者：' + ((body.view && body.view.survivorNames) || '—'),
                  showCancel: false,
                  success: () => this._applyView(body.view, body.view && body.view.myOpenId)
                })
                return
              }
              wx.showToast({ title: nick + ' 已淘汰', icon: 'none' })
              if (body.view) {
                this._applyView(body.view, body.view.myOpenId)
              } else {
                this._refreshView()
              }
            },
            onError: () => {
              this.setData({ opBusy: false })
            }
          }
        )
      }
    })
  },

  onEndGame() {
    if (!this.data.isHost) {
      return
    }
    wx.showModal({
      title: '结束游戏',
      content: '按当前存活人数结算',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        this.setData({ opBusy: true })
        callDontdoit(
          { action: 'endGame', roomId: this.data.roomId },
          {
            onOk: (res) => {
              this.setData({ opBusy: false })
              const body = (res && res.result) || {}
              if (body.view) {
                this._applyView(body.view, body.view.myOpenId)
              } else {
                this._refreshView()
              }
            },
            onError: () => {
              this.setData({ opBusy: false })
            }
          }
        )
      }
    })
  }
})
