const {
  truthQuestions,
  dareQuestions,
  drawWords,
  storyStarts,
  gardens,
  helperGames
} = require('../../data/game-data')
const { pickOne } = require('../../utils/random')
const { callRoomService } = require('../../utils/roomCloud')
const {
  memberCountLine,
  runStartAction,
  buildStartChecks
} = require('../../utils/roomUi')
const { patchMemberDisplay } = require('../../utils/roomMemberUi')
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
  showShareGuide
} = require('../../utils/aiUnlock')
const { runAi, SYSTEM_PARTY, SYSTEM_TRUTH_DARE, SYSTEM_STORY } = require('../../utils/aiHelper')
const { onRoomEntered, onRoomLeft } = require('../../utils/partyAiRoomHooks')

Page({
  data: {
    title: '',
    mode: 'random',
    roomCode: '',
    prompt: null,
    showAnswer: false,
    scoreA: 0,
    scoreB: 0,
    count: 0,
    seconds: 30,
    timerRunning: false,
    numberTarget: 0,
    numberLow: 1,
    numberHigh: 100,
    numberMessage: '',
    questionType: 'truth',
    storyLines: [],
    // 同场同步·真心话大冒险
    tdIsHost: false,
    tdIsTarget: false,
    tdTargetName: '',
    tdPhase: 'none',
    tdTruth: 0,
    tdDare: 0,
    tdMyChoice: '',
    tdLastTally: null,
    tdShowQuestion: false,
    tdRound: 0,
    tdRoomPlayers: [],
    tdMyOpenId: '',
    displayPlayers: [],
    statusHint: '',
    memberCountLine: '',
    aiBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {}
  },

  timer: null,
  _tdPoll: null,

  onLoad(query) {
    tryRedeemShareFromQuery(query || {})
    const title = decodeURIComponent(query.title || '')
    let config = {}
    try {
      config = query.config ? JSON.parse(decodeURIComponent(query.config)) : {}
    } catch (e) {
      config = {}
    }
    this.setData({ title })
    const rc = (config.roomCode && String(config.roomCode).replace(/\D/g, '')) || ''
    enableShareMenus()
    if (title === '真心话大冒险' && rc.length === 4) {
      this.setData({ mode: 'truthDareRoom', roomCode: rc })
      onRoomEntered(this, 'td_' + rc, 'truthDare')
      this._tdPoll = setInterval(() => {
        this.refreshTdState()
        this.refreshRoomPlayers()
      }, 2000)
      this.refreshTdState()
      this.refreshRoomPlayers()
      return
    }
    this.initGame(title)
  },

  onHide() {
    onPageHideUnlock(this)
  },

  onShow() {
    enableShareMenus()
    onPageShowUnlock(this)
    if (this.data.mode === 'truthDareRoom' && this.data.roomCode) {
      this.refreshTdState()
      this.refreshRoomPlayers()
    }
  },

  _shareCtx() {
    return { roomCode: this.data.roomCode }
  },

  onShareAppMessage() {
    if (this.data.mode === 'truthDareRoom') {
      return handleShareAppMessage(this, 'truthDare', this._shareCtx())
    }
    return handleShareAppMessage(this, 'index', {})
  },

  onShareTimeline() {
    if (this.data.mode === 'truthDareRoom') {
      return handleShareTimeline(this, 'truthDare', this._shareCtx())
    }
    return handleShareTimeline(this, 'index', {})
  },

  onCloseAiShareModal() {
    closeAiShareModal(this)
  },

  onAiShareTimeline() {
    closeAiShareModal(this)
    showShareGuide()
  },

  onUnload() {
    onPageHideUnlock(this)
    this.stopTimer()
    if (this._tdPoll) {
      clearInterval(this._tdPoll)
      this._tdPoll = null
    }
  },

  refreshTdState() {
    if (!this.data.roomCode) {
      return
    }
    callRoomService(
      { action: 'tdGetState', roomCode: this.data.roomCode },
      { silent: true, onOk: (res) => this.applyTdState(res.result || {}), onError: () => {} }
    )
  },

  applyTdState(s) {
    if (!s || typeof s !== 'object') {
      return
    }
    const cur = s.currentOpenId
    const target = s.targetOpenId
    const isTarget = !!cur && !!target && cur === target
    this.setData({
      tdIsHost: !!s.isHost,
      tdIsTarget: isTarget,
      tdTargetName: s.targetNickName || '',
      tdPhase: s.phase || 'none',
      tdTruth: s.truthCount != null ? s.truthCount : 0,
      tdDare: s.dareCount != null ? s.dareCount : 0,
      tdMyChoice: s.myChoice || '',
      tdLastTally: s.lastTally,
      tdRound: s.round || 0,
      tdMyOpenId: cur || ''
    })
    if (s.phase === 'voting' || s.phase === 'none') {
      this.setData({ tdShowQuestion: false, prompt: null })
    }
    if (s.phase === 'resolved' && s.lastTally && s.lastTally.tie) {
      this.setData({ tdShowQuestion: false, prompt: null })
    }
    this.refreshRoomPlayers()
  },

  refreshRoomPlayers() {
    if (!this.data.roomCode || this.data.mode !== 'truthDareRoom') {
      return
    }
    callRoomService(
      { action: 'get', roomCode: this.data.roomCode },
      {
        silent: true,
        onOk: (res) => {
          const r = res.result || {}
          const pl = r.players || []
          const patch = {
            tdRoomPlayers: pl,
            memberCountLine: memberCountLine(pl.length, 0, '至少 2 人可开始')
          }
          const ph = this.data.tdPhase === 'none' ? 'waiting' : 'playing'
          patchMemberDisplay(patch, {
            players: pl.map((p) => ({
              openId: p.openId,
              nickName: p.nickName,
              isHost: !!p.isHost
            })),
            phase: ph,
            maxPlayers: 0,
            isHost: this.data.tdIsHost,
            fallbackNeed: 2,
            hostWaiting: '⏳ 点击「开始本轮」',
            guestWaiting: '👥 等待主持人开始'
          })
          this.setData(patch)
        },
        onError: () => {}
      }
    )
  },

  tdAbdicateHost() {
    if (!this.data.tdIsHost) {
      return
    }
    wx.showModal({
      title: '移交主持',
      content: '将把主持移交给进组最早的一位其他成员，确定吗？',
      success: (r) => {
        if (!r.confirm) {
          return
        }
        wx.showLoading({ title: '…' })
        callRoomService(
          { action: 'abdicateHost', roomCode: this.data.roomCode },
          {
            onOk: () => {
              wx.hideLoading()
              wx.showToast({ title: '已移交', icon: 'success' })
              this.refreshTdState()
              this.refreshRoomPlayers()
            },
            onError: (err, hint) => {
              wx.hideLoading()
              wx.showToast({ title: (hint && hint.text) || '失败', icon: 'none' })
            }
          }
        )
      }
    })
  },

  tdShowTransferSheet() {
    if (!this.data.tdIsHost) {
      return
    }
    if (!this.data.tdMyOpenId) {
      wx.showToast({ title: '正在同步身份，请稍候', icon: 'none' })
      this.refreshTdState()
      return
    }
    const my = this.data.tdMyOpenId
    const ps = (this.data.tdRoomPlayers || []).filter(function (p) {
      return p.openId && p.openId !== my
    })
    if (!ps.length) {
      wx.showToast({ title: '暂无其他成员', icon: 'none' })
      return
    }
    wx.showActionSheet({
      itemList: ps.map(function (p) {
        return p.nickName || '参与者'
      }),
      success: (res) => {
        const i = res.tapIndex
        if (i < 0 || i >= ps.length) {
          return
        }
        const targetOpenId = ps[i].openId
        wx.showLoading({ title: '…' })
        callRoomService(
          {
            action: 'transferHost',
            roomCode: this.data.roomCode,
            targetOpenId: targetOpenId
          },
          {
            onOk: () => {
              wx.hideLoading()
              wx.showToast({ title: '已移交主持', icon: 'success' })
              this.refreshTdState()
              this.refreshRoomPlayers()
            },
            onError: (err, hint) => {
              wx.hideLoading()
              wx.showToast({ title: (hint && hint.text) || '移交失败', icon: 'none' })
            }
          }
        )
      }
    })
  },

  tdStartRound() {
    const n = (this.data.tdRoomPlayers || []).length
    const ctx = { playerCount: n }
    const checks = buildStartChecks({
      isHost: this.data.tdIsHost,
      playerCount: n,
      minPlayers: 2,
      kind: 'truthDare',
      ctx,
      hostLabel: '主持人',
      startVerb: '开始新轮'
    })
    const callTd = (payload, opts) => callRoomService(payload, opts)
    runStartAction({
      kind: 'truthDare',
      ctx,
      localChecks: checks,
      callService: callTd,
      payload: { action: 'tdStart', roomCode: this.data.roomCode },
      loadingTitle: '开始',
      onSuccess: () => {
        wx.showToast({ title: '已随机选人', icon: 'success' })
        this.refreshTdState()
      }
    })
  },

  tdCastVote(e) {
    const choice = e.currentTarget.dataset.choice
    if (choice !== 'truth' && choice !== 'dare') {
      return
    }
    callRoomService(
      { action: 'tdVote', roomCode: this.data.roomCode, choice: choice },
      {
        onOk: () => {
          this.refreshTdState()
          wx.showToast({ title: '已投票', icon: 'success' })
        }
      }
    )
  },

  tdFinish() {
    if (!this.data.tdIsHost) {
      return
    }
    wx.showLoading({ title: '…' })
    callRoomService(
      { action: 'tdTally', roomCode: this.data.roomCode },
      {
        onOk: (res) => {
          wx.hideLoading()
          this.refreshTdState()
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  tdDrawQuestion() {
    const lt = this.data.tdLastTally
    if (!lt || lt.tie || !lt.winner) {
      return
    }
    const list = lt.winner === 'truth' ? truthQuestions : dareQuestions
    this.setData({
      tdShowQuestion: true,
      questionType: lt.winner,
      prompt: {
        title: lt.winner === 'truth' ? '真心话' : '大冒险',
        detail: pickOne(list)
      }
    })
  },

  tdNextRound() {
    this.tdStartRound()
  },

  initGame(title) {
    if (title === '真心话大冒险') {
      this.setData({ mode: 'truthDare', prompt: { title: '真心话', detail: '点下面标签选真心话/大冒险，再点「换一题」抽题。' } })
      return
    }
    if (title.indexOf('你画我猜') >= 0) {
      this.setData({ mode: 'draw', prompt: { title: pickOne(drawWords), detail: '给表演者看词，其他人猜。' } })
      return
    }
    if (title === '故事接龙') {
      this.setData({ mode: 'story', prompt: { title: pickOne(storyStarts), detail: '每人轮流接一句。' } })
      return
    }
    if (title === '逛三园') {
      const garden = pickOne(gardens)
      this.setData({ mode: 'garden', prompt: { title: garden.name, detail: '示例：' + garden.examples.join('、') }, seconds: 5 })
      return
    }
    if (title === '猜数字') {
      this.resetNumber()
      return
    }

    const config = helperGames[title] || { mode: 'random', prompts: [{ title, detail: '主持人持机，亲友口头互动。' }] }
    this.config = config
    this.setData({
      mode: config.mode,
      prompt: pickOne(config.prompts),
      seconds: config.mode === 'traffic' || config.mode === 'reverse' ? 5 : 30
    })
  },

  nextPrompt() {
    if (this.data.mode === 'truthDare') {
      const list = this.data.questionType === 'truth' ? truthQuestions : dareQuestions
      this.setData({ prompt: { title: this.data.questionType === 'truth' ? '真心话' : '大冒险', detail: pickOne(list) } })
      return
    }
    if (this.data.mode === 'draw') {
      this.setData({ prompt: { title: pickOne(drawWords), detail: '给表演者看词，其他人猜。' } })
      return
    }
    if (this.data.mode === 'story') {
      this.setData({ prompt: { title: pickOne(storyStarts), detail: '每人轮流接一句。' }, storyLines: [] })
      return
    }
    if (this.data.mode === 'garden') {
      const garden = pickOne(gardens)
      this.setData({ prompt: { title: garden.name, detail: '示例：' + garden.examples.join('、') }, seconds: 5 })
      return
    }
    const prompts = this.config ? this.config.prompts : []
    this.setData({ prompt: pickOne(prompts), showAnswer: false })
  },

  switchQuestionType(event) {
    this.setData({ questionType: event.currentTarget.dataset.type })
    this.nextPrompt()
  },

  toggleAnswer() {
    this.setData({ showAnswer: !this.data.showAnswer })
  },

  addScore(event) {
    const key = event.currentTarget.dataset.key
    this.setData({ [key]: this.data[key] + 1 })
  },

  clearScore() {
    this.setData({ scoreA: 0, scoreB: 0, count: 0, storyLines: [] })
  },

  addStoryLine() {
    const lines = this.data.storyLines.concat(['第 ' + (this.data.storyLines.length + 1) + ' 句'])
    this.setData({ storyLines: lines })
  },

  toggleTimer() {
    if (this.timer) {
      this.stopTimer()
      return
    }
    this.setData({ timerRunning: true })
    this.timer = setInterval(() => {
      const seconds = this.data.seconds - 1
      if (seconds <= 0) {
        this.stopTimer()
        this.setData({ seconds: 0 })
        wx.vibrateShort()
        wx.showToast({ title: '时间到', icon: 'none' })
        return
      }
      this.setData({ seconds })
    }, 1000)
  },

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    this.setData({ timerRunning: false })
  },

  resetTimer() {
    this.stopTimer()
    this.setData({ seconds: this.data.mode === 'garden' || this.data.mode === 'traffic' || this.data.mode === 'reverse' ? 5 : 30 })
  },

  resetNumber() {
    this.setData({
      mode: 'number',
      numberTarget: Math.floor(1 + Math.random() * 100),
      numberLow: 1,
      numberHigh: 100,
      count: 0,
      numberMessage: '数字已生成，请输入参与者猜测。'
    })
  },

  askNumber() {
    wx.showModal({
      title: '输入猜测数字',
      editable: true,
      placeholderText: this.data.numberLow + '-' + this.data.numberHigh,
      success: (result) => {
        if (!result.confirm) {
          return
        }
        this.checkNumber(Number(result.content))
      }
    })
  },

  onAiSpicePrompt() {
    const p = this.data.prompt
    if (!p || !p.detail) {
      return
    }
    const kind = this.data.questionType === 'dare' ? '大冒险' : '真心话'
    runAi(this, {
      cacheTag: 'play-spice-' + this.data.questionType,
      system: SYSTEM_TRUTH_DARE,
      postProcess: { maxLen: 50 },
      buildPrompt: () => '原' + kind + '题：「' + p.detail + '」。请改写成更幽默的版本。',
      onOk: (text) => {
        const patch = {
          prompt: { title: p.title || kind, detail: text }
        }
        if (this.data.mode === 'truthDareRoom') {
          patch.tdShowQuestion = true
        }
        this.setData(patch)
      }
    })
  },
  onAiGenTruthDare() {
    const kind = this.data.questionType === 'dare' ? '大冒险' : '真心话'
    runAi(this, {
      cacheTag: 'play-gen-' + this.data.questionType,
      system: SYSTEM_TRUTH_DARE,
      postProcess: { maxLen: 50 },
      buildPrompt: () => '生成1条' + kind + '。',
      onOk: (text) => {
        const patch = { prompt: { title: kind, detail: text } }
        if (this.data.mode === 'truthDareRoom') {
          patch.tdShowQuestion = true
        }
        this.setData(patch)
      }
    })
  },
  onAiStoryLine() {
    const lines = this.data.storyLines || []
    runAi(this, {
      cacheTag: 'play-story',
      round: lines.length,
      system: SYSTEM_STORY,
      postProcess: { maxLen: 80 },
      buildPrompt: () => {
        const prev = lines.length ? lines.join('') : this.data.prompt.title || ''
        return '故事接龙，已有：「' + prev + '」。'
      },
      onOk: (text) => {
        const lines2 = this.data.storyLines.concat([text])
        this.setData({ storyLines: lines2 })
      }
    })
  },
  onAiTdComment() {
    const lt = this.data.tdLastTally
    if (!lt) {
      return
    }
    runAi(this, {
      cacheTag: 'play-td-comment',
      round: this.data.tdRound | 0,
      system: SYSTEM_PARTY,
      resultTitle: 'AI 点评',
      postProcess: { maxLen: 120 },
      buildPrompt: () =>
        '真心话大冒险投票：' +
        this.data.tdTargetName +
        ' 得真心话' +
        (lt.truthCount | 0) +
        '票、大冒险' +
        (lt.dareCount | 0) +
        '票。' +
        (lt.tie ? '平票。' : '胜出：' + (lt.winner === 'truth' ? '真心话' : '大冒险')) +
        '。'
    })
  },
  checkNumber(guess) {
    if (!guess || guess < this.data.numberLow || guess > this.data.numberHigh) {
      this.setData({ numberMessage: '请输入当前范围内的数字。' })
      return
    }
    const count = this.data.count + 1
    if (guess === this.data.numberTarget) {
      this.setData({ count, numberMessage: '猜中了！答案就是 ' + guess })
    } else if (guess > this.data.numberTarget) {
      this.setData({ count, numberHigh: guess - 1, numberMessage: guess + ' 大了。' })
    } else {
      this.setData({ count, numberLow: guess + 1, numberMessage: guess + ' 小了。' })
    }
  }
})
