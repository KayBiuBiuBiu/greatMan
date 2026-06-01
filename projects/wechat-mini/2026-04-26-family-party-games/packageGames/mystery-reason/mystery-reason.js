const { callMysteryReason } = require('../../utils/mysteryReasonCloud')
const { enterCloudRoomOnLoad, joinRoomWithUi } = require('../utils/roomJoin')
const { withJoinProfile, getFallbackNickName } = require('../../utils/userProfile')
const { memberCountLine, buildStartChecks, runStartAction } = require('../utils/roomUi')
const { mergeLocalProfileIntoPlayers, patchLobbyUi } = require('../utils/roomMemberUi')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const { tryRedeemShareFromQuery, onPageShowUnlock, onPageHideUnlock } = require('../../utils/aiUnlock')
const { TOAST_ROOM_CODE_6, copyRoomCodeToClipboard } = require('../utils/roomCopy')
const { onRoomEntered, onRoomLeft } = require('../utils/partyAiRoomHooks')
const {
  storeMyOpenId,
  ensureInRoomPoll,
  stopInRoomPoll,
  resumeInRoomPollOnShow,
  retrySyncIfNotInRoom
} = require('../utils/inRoomCloudSync')

const MR_OPENID_KEY = 'mr_my_open_id'
const MR_SCRIPT_PREFIX = 'mr_script_'
const MR_PRIVATE_PREFIX = 'mr_private_'
const MR_STARS_PREFIX = 'mr_stars_'
const DIFFICULTIES = ['新手', '进阶', '烧脑']
const CODE_SLOTS = [0, 1, 2, 3, 4, 5]
const NUMPAD_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '清空', '0', '删除']

const PHASE_ZH = {
  waiting: '等待开局',
  generate_script: 'AI 生成剧本',
  read_script: '读本',
  public_discuss: '公聊推理',
  get_evidence: '证据派发',
  analyze_clue: '线索辩论',
  final_vote: '投票',
  wait_unlock_review: '解锁复盘',
  ai_review: 'AI 复盘',
  finished: '对局结束'
}

const EVIDENCE_PHASES = { get_evidence: 1, analyze_clue: 1, final_vote: 1 }

function debounce(fn, delay) {
  let timer = null
  return function (...args) {
    if (timer) return
    timer = setTimeout(() => {
      fn.apply(this, args)
      timer = null
    }, delay || 300)
  }
}

function mergePrivateClues(list, starList) {
  const stars = starList || []
  return (list || []).map((c) =>
    Object.assign({}, c, { isStarred: stars.indexOf(c.id) >= 0 })
  )
}

Page({
  data: {
    opBusy: false,
    roomId: '',
    roomCode: '',
    joinCode: '',
    codeSlots: CODE_SLOTS,
    numpadKeys: NUMPAD_KEYS,
    nick: '',
    pub: {},
    view: {},
    isHost: false,
    phase: 'waiting',
    phaseZh: '',
    phaseRemainingSeconds: 0,
    memberCountLine: '',
    displayPlayers: [],
    statusHint: '',
    canStart: false,
    difficultyIdx: 0,
    difficultyLabels: DIFFICULTIES,
    clueTab: 'public',
    myPrivateClues: [],
    myStarList: [],
    showScriptModal: false,
    scriptText: '',
    scriptDetail: {
      roleName: '',
      profile: '',
      relationships: '',
      roleScript: '',
      secret: '',
      timeline: ''
    }
  },

  onLoad(query) {
    enableShareMenus()
    tryRedeemShareFromQuery(query || {})
    this.setData({
      nick: (wx.getStorageSync('mr_nick') || '').toString() || getFallbackNickName()
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
          callService: callMysteryReason,
          silentJoinToast: true,
          onReady: (id, jr) => {
            this.setData({ roomId: String(id), roomCode: code })
            onRoomEntered(this, String(id), 'mysteryReason')
            this._bootInRoom(jr)
          }
        })
      } else {
        onRoomEntered(this, rid, 'mysteryReason')
        this._bootInRoom()
      }
    } else if (cfg.roomCode && cfg.roomCode.length === 6) {
      this.setData({ joinCode: cfg.roomCode })
    }
    this._debouncedVote = debounce((oid) => this._submitVote(oid), 300)
    this._debouncedHostSkip = debounce(() => this._hostSkip(), 300)
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
      resumeInRoomPollOnShow(this, this._sync)
      this._sync()
    }
  },

  _parseCfg(query) {
    try {
      if (query.config) return JSON.parse(decodeURIComponent(query.config))
    } catch (e) {}
    return {
      roomId: query.roomId || '',
      roomCode: String(query.roomCode || '')
        .replace(/\D/g, '')
        .slice(0, 6)
    }
  },

  _shareCtx() {
    return {
      roomId: this.data.roomId,
      roomCode: this.data.roomCode || (this.data.pub && this.data.pub.roomCode)
    }
  },

  onShareAppMessage() {
    const ctx = this._shareCtx()
    if (this.data.phase === 'wait_unlock_review' && this.data.roomId) {
      callMysteryReason(
        { action: 'unlockReview', roomId: this.data.roomId, shareVerify: true },
        { silent: true, onOk: () => this._sync() }
      )
    }
    return handleShareAppMessage(this, 'mysteryReason', ctx)
  },

  onShareTimeline() {
    return handleShareTimeline(this, 'mysteryReason', this._shareCtx())
  },

  _storeOid(oid) {
    storeMyOpenId(MR_OPENID_KEY, oid)
  },

  _bootInRoom(jr) {
    const r = jr || {}
    if (r.myOpenId) this._storeOid(r.myOpenId)
    if (r.state || r.view) this._applySync(r)
    ensureInRoomPoll(this, this._sync)
    this._sync()
  },

  _sync() {
    if (!this.data.roomId) return
    callMysteryReason(
      { action: 'syncState', roomId: this.data.roomId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) return
          if (
            !retrySyncIfNotInRoom(this, r, this._sync, {
              callService: callMysteryReason
            })
          ) {
            return
          }
          if (r.myOpenId) this._storeOid(r.myOpenId)
          this._applySync(r)
          const ph = (r.state && r.state.phase) || ''
          if (EVIDENCE_PHASES[ph]) this._fetchPrivateClues()
        }
      }
    )
  },

  _applySync(r) {
    const st = r.state || {}
    const v = r.view || {}
    const ph = st.phase || 'waiting'
    const myOid = r.myOpenId || v.myOpenId || ''
    const pl = (st.memberList || []).map((m) => {
      const merged = mergeLocalProfileIntoPlayers([m], myOid)[0]
      return Object.assign({}, merged, {
        roleName: m.roleName || merged.roleName || '',
        displayName: m.displayName || m.roleName || merged.nickName
      })
    })
    const n = pl.length
    const isHost = !!(v.isHost || st.hostOpenId === myOid)
    const diffIdx = Math.max(0, DIFFICULTIES.indexOf(st.difficulty || '新手'))
    const patch = {
      pub: st,
      view: v,
      phase: ph,
      phaseZh: PHASE_ZH[ph] || ph,
      phaseRemainingSeconds: st.phaseRemainingSeconds | 0,
      isHost,
      difficultyIdx: diffIdx,
      memberCountLine: memberCountLine(n, Math.max(n, 3)),
      displayPlayers: pl
    }
    const rid = this.data.roomId
    if (rid) {
      const cachedPrivate = wx.getStorageSync(MR_PRIVATE_PREFIX + rid) || []
      const cachedStars = wx.getStorageSync(MR_STARS_PREFIX + rid) || []
      patch.myPrivateClues = mergePrivateClues(cachedPrivate, cachedStars)
      patch.myStarList = cachedStars
    }
    patchLobbyUi(
      patch,
      {
        state: st,
        view: v,
        players: pl,
        phase: ph,
        maxPlayers: Math.max(n, 3),
        minPlayers: 3,
        isHost,
        myOpenId: myOid,
        hostOpenId: st.hostOpenId || ''
      },
      this
    )
    if (ph === 'waiting') {
      patch.canStart = isHost && n >= 3
      patch.statusHint =
        n >= 3 ? '人齐后组长可开始互动' : '至少 3 人才能开始互动（当前 ' + n + ' 人）'
      patch.statusBannerWarn = n < 3
    } else if (ph === 'generate_script') {
      patch.statusHint = 'AI 正在生成专属剧本，请稍候…'
      patch.canStart = false
    } else if (ph === 'wait_unlock_review') {
      patch.statusHint = '分享解锁后可查看 AI 复盘'
      patch.canStart = false
    } else {
      patch.statusHint = (PHASE_ZH[ph] || ph) + ' · 剩余 ' + (st.phaseRemainingSeconds | 0) + ' 秒'
      patch.canStart = false
    }
    this.setData(patch)
  },

  _fetchPrivateClues() {
    const rid = this.data.roomId
    if (!rid) return
    callMysteryReason(
      { action: 'fetchPrivateEvidence', roomId: rid },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (!r.ok) return
          const list = r.list || []
          const starList = r.starList || wx.getStorageSync(MR_STARS_PREFIX + rid) || []
          wx.setStorageSync(MR_PRIVATE_PREFIX + rid, list)
          wx.setStorageSync(MR_STARS_PREFIX + rid, starList)
          this.setData({
            myPrivateClues: mergePrivateClues(list, starList),
            myStarList: starList
          })
        }
      }
    )
  },

  onNumpadTap(e) {
    const key = (e.currentTarget.dataset.key || '').toString()
    let code = this.data.joinCode || ''
    if (key === '清空') {
      code = ''
    } else if (key === '删除') {
      code = code.slice(0, -1)
    } else if (code.length < 6) {
      code += key
    }
    this.setData({ joinCode: code })
  },

  onJoinTap() {
    const code = this.data.joinCode
    if (code.length !== 6) {
      wx.showToast({ title: TOAST_ROOM_CODE_6, icon: 'none' })
      return
    }
    joinRoomWithUi(callMysteryReason, { roomCode: code }, {
      onOk: (res) => {
        if (res.roomId) {
          this.setData({ roomId: res.roomId, roomCode: res.roomCode || code })
          onRoomEntered(this, res.roomId, 'mysteryReason')
          this._bootInRoom(res)
        }
      }
    })
  },

  onCreateRoom() {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })
    callMysteryReason(
      withJoinProfile({
        action: 'create',
        difficulty: DIFFICULTIES[this.data.difficultyIdx | 0]
      }),
      {
        onOk: (res) => {
          const r = (res && res.result) || {}
          this.setData({ opBusy: false })
          if (!r.roomId) return
          const code = r.roomCode || ''
          wx.showModal({
            title: '聚会组口令：' + code,
            content: '请把口令告诉同座亲友，对方点选数字加入。至少 3 人才能开始互动。',
            confirmText: '进入聚会组',
            showCancel: false,
            success: () => {
              this.setData({
                roomId: String(r.roomId),
                roomCode: code,
                joinCode: code
              })
              onRoomEntered(this, String(r.roomId), 'mysteryReason')
              this._bootInRoom(r)
            }
          })
        },
        onError: () => this.setData({ opBusy: false })
      }
    )
  },

  onCopyCode() {
    copyRoomCodeToClipboard(this.data.roomCode || (this.data.pub && this.data.pub.roomCode))
  },

  onDifficultyChange(e) {
    this.setData({ difficultyIdx: e.detail.value | 0 })
  },

  onStartGame() {
    const pub = this.data.pub || {}
    const n = (pub.memberList && pub.memberList.length) || 0
    const checks = buildStartChecks({
      isHost: this.data.isHost,
      playerCount: n,
      minPlayers: 3,
      kind: 'draw',
      hostLabel: '组长',
      startVerb: '开始互动'
    })
    runStartAction(this, {
      localChecks: checks,
      cloudCall: (cb) => {
        this.setData({ opBusy: true })
        callMysteryReason(
          {
            action: 'startGame',
            roomId: this.data.roomId,
            difficulty: DIFFICULTIES[this.data.difficultyIdx | 0]
          },
          {
            onOk: () => {
              this.setData({ opBusy: false })
              cb(null, {})
            },
            onError: (err) => {
              this.setData({ opBusy: false })
              cb(err)
            }
          }
        )
      },
      onSuccess: () => this._sync()
    })
  },

  onOpenScript() {
    const rid = this.data.roomId
    const cached = wx.getStorageSync(MR_SCRIPT_PREFIX + rid) || ''
    if (cached) {
      try {
        const detail = JSON.parse(cached)
        if (detail && detail.roleScript) {
          this.setData({
            showScriptModal: true,
            scriptDetail: detail,
            scriptText: this._formatScriptText(detail)
          })
          return
        }
      } catch (e) {}
    }
    if (this.data.opBusy) return
    this.setData({ opBusy: true })
    callMysteryReason(
      { action: 'getMyScript', roomId: rid },
      {
        onOk: (res) => {
          this.setData({ opBusy: false })
          const r = (res && res.result) || {}
          const detail = {
            roleName: r.roleName || '',
            profile: r.profile || '',
            relationships: r.relationships || '',
            roleScript: r.roleScript || r.script || '',
            secret: r.secret || '',
            timeline: r.timeline || ''
          }
          if (!detail.roleScript) {
            wx.showToast({ title: '剧本生成中，请稍候', icon: 'none' })
            return
          }
          wx.setStorageSync(MR_SCRIPT_PREFIX + rid, JSON.stringify(detail))
          this.setData({
            showScriptModal: true,
            scriptDetail: detail,
            scriptText: r.script || this._formatScriptText(detail)
          })
        },
        onError: () => this.setData({ opBusy: false })
      }
    )
  },

  _formatScriptText(detail) {
    const d = detail || {}
    return [
      '【角色名】\n' + (d.roleName || ''),
      '【人物简介】\n' + (d.profile || ''),
      '【人物关系】\n' + (d.relationships || ''),
      '【个人剧情】\n' + (d.roleScript || ''),
      '【隐藏秘密】\n' + (d.secret || ''),
      '【时间线】\n' + (d.timeline || '')
    ].join('\n\n')
  },

  onCloseScript() {
    this.setData({ showScriptModal: false })
  },

  onMarkReady() {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })
    callMysteryReason(
      { action: 'markReady', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ opBusy: false })
          this._sync()
        },
        onError: () => this.setData({ opBusy: false })
      }
    )
  },

  onHostSkip() {
    if (!this.data.isHost || this.data.opBusy) return
    this._debouncedHostSkip()
  },

  _hostSkip() {
    this.setData({ opBusy: true })
    callMysteryReason(
      { action: 'hostSkipPhase', roomId: this.data.roomId },
      {
        onOk: () => {
          this.setData({ opBusy: false })
          this._sync()
        },
        onError: () => this.setData({ opBusy: false })
      }
    )
  },

  onClueTab(e) {
    const tab = e.currentTarget.dataset.tab || 'public'
    this.setData({ clueTab: tab })
    if (tab === 'private') this._fetchPrivateClues()
  },

  onStarClue(e) {
    const clueId = (e.currentTarget.dataset.id || '').toString()
    if (!clueId || this.data.opBusy) return
    callMysteryReason(
      { action: 'starClue', roomId: this.data.roomId, clueId },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          const stars = r.starList || []
          const rid = this.data.roomId
          wx.setStorageSync(MR_STARS_PREFIX + rid, stars)
          this.setData({
            myStarList: stars,
            myPrivateClues: mergePrivateClues(this.data.myPrivateClues, stars)
          })
        }
      }
    )
  },

  onVoteTap(e) {
    const oid = (e.currentTarget.dataset.oid || '').toString()
    if (!oid || this.data.opBusy) return
    wx.showModal({
      title: '确认投票',
      content: '投给「' + (e.currentTarget.dataset.name || '该对象') + '」？',
      success: (res) => {
        if (res.confirm) this._debouncedVote(oid)
      }
    })
  },

  _submitVote(targetId) {
    if (this.data.opBusy) return
    this.setData({ opBusy: true })
    callMysteryReason(
      { action: 'submitVote', roomId: this.data.roomId, targetId },
      {
        onOk: () => {
          this.setData({ opBusy: false })
          wx.showToast({ title: '投票成功', icon: 'success' })
          this._sync()
        },
        onError: () => this.setData({ opBusy: false })
      }
    )
  },

  onRestart() {
    if (!this.data.isHost || this.data.opBusy) return
    wx.showModal({
      title: '重启对局',
      content: '将清空本局数据并回到等待开局，是否继续？',
      success: (res) => {
        if (!res.confirm) return
        this.setData({ opBusy: true })
        callMysteryReason(
          { action: 'restartGame', roomId: this.data.roomId },
          {
            onOk: () => {
              const rid = this.data.roomId
              wx.removeStorageSync(MR_SCRIPT_PREFIX + rid)
              wx.removeStorageSync(MR_PRIVATE_PREFIX + rid)
              wx.removeStorageSync(MR_STARS_PREFIX + rid)
              this.setData({
                opBusy: false,
                myPrivateClues: [],
                myStarList: [],
                clueTab: 'public',
                scriptText: '',
                scriptDetail: {
                  roleName: '',
                  profile: '',
                  relationships: '',
                  roleScript: '',
                  secret: '',
                  timeline: ''
                }
              })
              this._sync()
            },
            onError: () => this.setData({ opBusy: false })
          }
        )
      }
    })
  },

  /** Minium：注入剧本弹窗内容（云测 tcb 拉取后展示四区块） */
  applyTestScriptDetail(detail) {
    const d = detail || {}
    this.setData({
      showScriptModal: true,
      scriptDetail: {
        roleName: d.roleName || '',
        profile: d.profile || '',
        relationships: d.relationships || '',
        roleScript: d.roleScript || '',
        secret: d.secret || '',
        timeline: d.timeline || ''
      },
      scriptText: this._formatScriptText(d)
    })
  },

  /** Minium：注入房内 UI（云测 tcb 已写好房间数据时使用） */
  applyTestRoomBootstrap(payload) {
    const p = payload || {}
    const st = p.state || {}
    const v = p.view || {}
    const pl = (st.memberList || []).map((m) => ({
      openId: m.openId,
      nickName: m.nickName,
      roleName: m.roleName || '',
      displayName: m.displayName || m.roleName || m.nickName,
      avatarUrl: m.avatarUrl || '',
      isReady: !!m.isReady
    }))
    const n = pl.length
    const isHost = !!v.isHost
    this.setData({
      roomId: String(p.roomId || st.roomId || ''),
      roomCode: String(p.roomCode || st.roomCode || ''),
      joinCode: String(p.roomCode || st.roomCode || ''),
      pub: st,
      view: v,
      phase: st.phase || 'waiting',
      phaseZh: PHASE_ZH[st.phase] || st.phase || '',
      phaseRemainingSeconds: st.phaseRemainingSeconds | 0,
      isHost,
      displayPlayers: pl,
      memberCountLine: '当前 ' + n + ' 人',
      canStart: isHost && n >= 3 && st.phase === 'waiting',
      statusHint:
        st.phase === 'waiting'
          ? n >= 3
            ? '人齐后组长可开始互动'
            : '至少 3 人才能开始互动（当前 ' + n + ' 人）'
          : PHASE_ZH[st.phase] || ''
    })
    if (this.data.roomId) {
      stopInRoomPoll(this)
      // Minium 走 tcb 注入快照，IDE 内 wx.cloud 不可用，勿开轮询避免 _sync 反复报错
      if (!p.skipPoll) {
        onRoomEntered(this, this.data.roomId, 'mysteryReason')
        ensureInRoomPoll(this, this._sync)
      }
    }
  },

  /** Minium：停止房内轮询（避免 IDE 内 wx.cloud 反复失败） */
  stopInRoomPollForTest() {
    stopInRoomPoll(this)
  },

  /** Minium：回到未进组大厅（仅本地 UI，不删云端房间） */
  resetLobbyForTest() {
    stopInRoomPoll(this)
    this.setData({
      roomId: '',
      roomCode: '',
      joinCode: '',
      pub: {},
      view: {},
      phase: 'waiting',
      opBusy: false
    })
  },

  noop() {}
})
