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
    tdRound: 0
  },

  timer: null,
  _tdPoll: null,

  onLoad(query) {
    const title = decodeURIComponent(query.title || '')
    let config = {}
    try {
      config = query.config ? JSON.parse(decodeURIComponent(query.config)) : {}
    } catch (e) {
      config = {}
    }
    this.setData({ title })
    const rc = (config.roomCode && String(config.roomCode).replace(/\D/g, '')) || ''
    if (title === '真心话大冒险' && rc.length === 4) {
      this.setData({ mode: 'truthDareRoom', roomCode: rc })
      this._tdPoll = setInterval(() => {
        this.refreshTdState()
      }, 2000)
      this.refreshTdState()
      return
    }
    this.initGame(title)
  },

  onUnload() {
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
      tdRound: s.round || 0
    })
    if (s.phase === 'voting' || s.phase === 'none') {
      this.setData({ tdShowQuestion: false, prompt: null })
    }
    if (s.phase === 'resolved' && s.lastTally && s.lastTally.tie) {
      this.setData({ tdShowQuestion: false, prompt: null })
    }
  },

  tdStartRound() {
    if (!this.data.tdIsHost) {
      return
    }
    wx.showLoading({ title: '…' })
    callRoomService(
      { action: 'tdStart', roomCode: this.data.roomCode },
      {
        onOk: () => {
          wx.hideLoading()
          wx.showToast({ title: '已随机选人', icon: 'success' })
          this.refreshTdState()
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
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

    const config = helperGames[title] || { mode: 'random', prompts: [{ title, detail: '面对面辅助玩法。' }] }
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
