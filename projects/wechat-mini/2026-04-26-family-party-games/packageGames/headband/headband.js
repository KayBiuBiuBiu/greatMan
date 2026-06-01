const { callHeadband } = require('../../utils/headbandCloud')
const { enterCloudRoomOnLoad } = require('../utils/roomJoin')
const { withJoinProfile, getFallbackNickName } = require('../../utils/userProfile')
const { memberCountLine, buildStartChecks } = require('../utils/roomUi')
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
const { joinRoomWithUi } = require('../utils/roomJoin')
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
const HB_OPENID_KEY = 'hb_my_open_id'
const HB_BUILD_ID = 'headband-repo-v8'

const CATEGORY_VALUES = ['history', 'entertainment', 'sports', 'anime', 'movie', 'internet']
const CATEGORY_LABELS = ['历史名人', '娱乐明星', '体育人物', '动漫角色', '影视角色', '网络热门']
const DIFFICULTY_VALUES = ['easy', 'medium', 'hard']
const DIFFICULTY_LABELS = ['简单', '中等', '困难']
const WORD_COUNT_VALUES = [10, 20, 30, 50]
const WORD_COUNT_LABELS = ['10 个', '20 个', '30 个', '50 个']

function idxOf(arr, val, fallback) {
  const i = arr.indexOf(val)
  return i >= 0 ? i : fallback
}

function enrichHbPlayers(players, myOpenId, hostOpenId, phase) {
  const merged = mergeLocalProfileIntoPlayers(players || [], myOpenId)
  const st = phase || 'waiting'
  return merged.map((p) => {
    const nick = (p.nickName || '参与者').trim()
    const isSelf = !!(myOpenId && p.openId === myOpenId)
    const raw = String(p.displayWord || '').trim()
    const word =
      raw === '？？？' || raw === '???' ? '保密' : raw || '—'
    let subLabel = ''
    if (st === 'waiting') {
      const host = p.isHost || (hostOpenId && p.openId === hostOpenId)
      if (host) {
        subLabel = '组长'
      } else {
        subLabel = p.profileReady ? '已准备' : '未准备'
      }
    } else if (st === 'playing') {
      subLabel = isSelf ? '你的词卡：保密' : '词卡：' + word
    } else if (st === 'finished') {
      subLabel = '词卡：' + (word === '保密' && p.myWord ? p.myWord : word)
    }
    return {
      openId: p.openId,
      nickName: nick,
      avatarUrl: p.avatarUrl || '',
      isHost: !!p.isHost || !!(hostOpenId && p.openId === hostOpenId),
      displayWord: word,
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
    guessInput: '',
    isHost: false,
    inWaiting: true,
    inPlaying: false,
    inFinished: false,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    statusBannerWarn: false,
    canStart: false,
    canRestart: false,
    playerProgressPct: 0,
    categoryLabels: CATEGORY_LABELS,
    categoryIdx: 1,
    difficultyLabels: DIFFICULTY_LABELS,
    difficultyIdx: 0,
    wordCountLabels: WORD_COUNT_LABELS,
    wordCountIdx: 1,
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
      nick: (wx.getStorageSync('hb_nick') || '').toString() || getFallbackNickName()
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
          callService: callHeadband,
          silentJoinToast: true,
          onReady: (id, jr) => {
            this.setData({ roomId: String(id), roomCode: code })
            onRoomEntered(this, String(id), 'headband')
            this._bootInRoom(jr)
          }
        })
      } else {
        onRoomEntered(this, rid, 'headband')
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
    return handleShareAppMessage(this, 'headband', this._shareCtx())
  },

  onShareTimeline() {
    return handleShareTimeline(this, 'headband', this._shareCtx())
  },

  _lobbyReadyCtx() {
    return {
      callService: callHeadband,
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
    storeMyOpenId(HB_OPENID_KEY, oid)
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
    callHeadband(
      { action: 'syncState', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            console.warn('[hb sync]', r.errMsg)
            return
          }
          if (!retrySyncIfNotInRoom(this, r, this._refreshView, {
            callService: callHeadband
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
    const cfg = v.config || {}
    const phase = waiting ? 'waiting' : playing ? 'playing' : 'finished'
    const patch = {
      view: v,
      isHost: isHost,
      inWaiting: waiting,
      inPlaying: playing,
      inFinished: finished,
      categoryIdx: idxOf(CATEGORY_VALUES, cfg.category, 1),
      difficultyIdx: idxOf(DIFFICULTY_VALUES, cfg.difficulty, 0),
      wordCountIdx: idxOf(WORD_COUNT_VALUES, cfg.wordCount | 0, 1)
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
        hostWaiting: '⏳ 人齐后点「开始游戏」发牌',
        guestWaiting: '👥 请点「准备」，等待组长开始游戏'
      }, this)
      patch.canRestart = false
      patch.statusBannerWarn = n < 2
      patch.displayPlayers = enrichHbPlayers(pl, myOpenId, v.hostOpenId, 'waiting')
    } else if (playing) {
      patch.statusHint = '🎮 进行中：自己的词卡保密，猜对自己获胜'
      patch.statusBannerWarn = false
      patch.canStart = false
      patch.canRestart = false
      patch.memberCountLine = memberCountLine(n, 0, '')
      patch.playerProgressPct = 100
      patch.displayPlayers = enrichHbPlayers(v.players, myOpenId, v.hostOpenId, 'playing')
    } else {
      patch.statusHint = v.winnerNickName
        ? '🎉 ' + v.winnerNickName + ' 猜对了 · 可再来一局'
        : '本局已结束 · 可再来一局'
      patch.statusBannerWarn = false
      patch.canStart = false
      patch.canRestart = isHost && n >= 2
      patch.memberCountLine = memberCountLine(n, 0, '')
      patch.displayPlayers = enrichHbPlayers(v.players, myOpenId, v.hostOpenId, 'finished')
    }

    this.setData(patch)
  },

  applyTestSyncSnapshot(v) {
    const view = v || {}
    const oid = String(view.myOpenId || '').trim()
    this._applyView(view, oid)
  },

  _syncConfigToCloud(done) {
    if (!this.data.isHost || !this.data.roomId) {
      if (typeof done === 'function') {
        done()
      }
      return
    }
    callHeadband(
      {
        action: 'setConfig',
        roomId: this.data.roomId,
        category: CATEGORY_VALUES[this.data.categoryIdx],
        difficulty: DIFFICULTY_VALUES[this.data.difficultyIdx],
        wordCount: WORD_COUNT_VALUES[this.data.wordCountIdx]
      },
      { silent: true, onOk: () => { if (typeof done === 'function') done() }, onError: () => { if (typeof done === 'function') done() } }
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

  onGuessInput(e) {
    this.setData({ guessInput: String((e && e.detail && e.detail.value) || '') })
  },

  onCategoryPick(e) {
    const i = (e && e.detail && e.detail.value) | 0
    this.setData({ categoryIdx: i }, () => this._syncConfigToCloud())
  },

  onDifficultyPick(e) {
    const i = (e && e.detail && e.detail.value) | 0
    this.setData({ difficultyIdx: i }, () => this._syncConfigToCloud())
  },

  onWordCountPick(e) {
    const i = (e && e.detail && e.detail.value) | 0
    this.setData({ wordCountIdx: i }, () => this._syncConfigToCloud())
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
    wx.setStorageSync('hb_nick', n)
    this.setData({ opBusy: true })
    callHeadband(withJoinProfile({ action: 'create', nickName: n }), {
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
        onRoomEntered(this, String(r.roomId), 'headband')
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
    wx.setStorageSync('hb_nick', n)
    this.setData({ opBusy: true })
    joinRoomWithUi(
      callHeadband,
      { roomCode: c, nickName: n },
      {
        onOk: (r) => {
          if (r.myOpenId) {
            this._storeMyOpenId(r.myOpenId)
          }
          this.setData({ opBusy: false, roomId: String(r.roomId), roomCode: c, joinCode: c })
          onRoomEntered(this, String(r.roomId), 'headband')
          this._bootInRoom(r)
        },
        onFail: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },

  _ensureCloudBuild(onReady) {
    callHeadband(
      { action: 'ping' },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.buildId === HB_BUILD_ID) {
            onReady && onReady()
            return
          }
          wx.showModal({
            title: '云函数版本不对',
            content:
              '当前 headbandRoomService 不是本仓库最新版（ping 未返回 buildId=' +
              HB_BUILD_ID +
              '）。\n\n请在开发者工具打开本项目 → cloudfunctions/headbandRoomService → 右键「上传并部署：云端安装依赖」。',
            showCancel: false
          })
        },
        onError: () => {
          wx.showModal({
            title: '云函数不可用',
            content: '请先部署 headbandRoomService（云端安装依赖）',
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

  /** 组长：云端 startGame 生成词库并发牌（等待中开局 / 结束后再来一局） */
  _runStartRound(opts) {
    const rematch = !!(opts && opts.rematch)
    const v = this.data.view || {}
    const n = (v.players && v.players.length) || 0
    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'headband',
      players: v.players || [],
      hostOpenId: v.hostOpenId || '',
      hostLabel: '组长',
      startVerb: rematch ? '再来一局' : '开始游戏'
    })
    const fail = checks.find((c) => c.fail)
    if (fail) {
      wx.showModal({ title: fail.title, content: fail.content, showCancel: false })
      return
    }

    this._ensureCloudBuild(() => {
      this.setData({ opBusy: true })
      const afterConfig = () => {
          wx.showLoading({ title: rematch ? 'AI 正在开局…' : 'AI 正在出题…', mask: true })
        callHeadband(
          { action: 'startGame', roomId: this.data.roomId },
          {
            onOk: (res) => {
              wx.hideLoading()
              this.setData({ opBusy: false })
              const r = (res && res.result) || {}
              if (r.errMsg) {
                if (/未知 action/.test(r.errMsg) && !/build=/.test(r.errMsg)) {
                  wx.showModal({
                    title: '请重新部署云函数',
                    content:
                      '云端 headbandRoomService 仍是旧版（不支持 startGame）。\n\n请用本项目 cloudfunctions/headbandRoomService/index.js → 上传并部署：云端安装依赖。',
                    showCancel: false
                  })
                } else {
                  wx.showToast({ title: String(r.errMsg).slice(0, 24), icon: 'none' })
                }
                return
              }
              this.setData({ guessInput: '' })
              this._refreshView()
              wx.showToast({
                title: rematch ? 'AI 新一局开始' : 'AI 词库开局',
                icon: 'success'
              })
            },
            onError: () => {
              wx.hideLoading()
              this.setData({ opBusy: false })
            }
          }
        )
      }
      if (rematch) {
        afterConfig()
      } else {
        this._syncConfigToCloud(afterConfig)
      }
    })
  },

  onSubmitGuess() {
    const g = (this.data.guessInput || '').trim()
    if (!g) {
      wx.showToast({ title: '请输入猜测', icon: 'none' })
      return
    }
    this.setData({ opBusy: true })
    callHeadband(
      { action: 'submitGuess', roomId: this.data.roomId, guess: g },
      {
        onOk: (res) => {
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          if (r.correct) {
            wx.showModal({
              title: '恭喜你猜对了！',
              content: '本局结束',
              showCancel: false,
              success: () => this._refreshView()
            })
            return
          }
          wx.showToast({ title: '不对哦，再想想', icon: 'none' })
          this.setData({ guessInput: '' })
        },
        onError: () => {
          this.setData({ opBusy: false })
        }
      }
    )
  },

  onEndGame() {
    if (!this.data.isHost) {
      return
    }
    wx.showModal({
      title: '结束游戏',
      content: '确定结束本局吗？',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        this.setData({ opBusy: true })
        callHeadband(
          { action: 'endGame', roomId: this.data.roomId },
          {
            onOk: () => {
              this.setData({ opBusy: false })
              this._refreshView()
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
