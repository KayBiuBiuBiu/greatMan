const { gameGroups } = require('../../data/game-data')
const {
  isDrawGuessEnabled,
  isHomeGameEnabled,
  isWerewolfEnabled,
  isMysteryReasonEnabled
} = require('../../data/feature-flags')
const { callRoomService } = require('../../utils/roomCloud')
const { callWerewolfService } = require('../../utils/werewolfCloud')
const { callUndercoverService } = require('../../utils/undercoverRoomCloud')
const { callGameStats } = require('../../utils/gameStatsCloud')
const { shouldSkipGameStatsInDevtools } = require('../../utils/cloudRealtime')
const { callMusic } = require('../../utils/musicRoomCloud')
const { callDraw } = require('../../utils/drawRoomCloud')
const { callDrink } = require('../../utils/drinkRoomCloud')
const { callHeadband } = require('../../utils/headbandCloud')
const { callDontdoit } = require('../../utils/dontdoitCloud')
const { callMysteryReason } = require('../../utils/mysteryReasonCloud')
const { callGesture } = require('../../utils/gestureRoomCloud')
const {
  enableShareMenus,
  handleShareAppMessage,
  handleShareTimeline
} = require('../../utils/shareHelper')
const { withJoinProfile } = require('../../utils/userProfile')
const {
  ensureUserInfo,
  completePendingAction,
  cancelPendingAction
} = require('../../utils/userHelper')
const {
  refreshAiUnlockPage,
  showShareGuide,
  tryRedeemShareFromQuery,
  onPageShowUnlock,
  onPageHideUnlock,
  closeAiShareModal
} = require('../../utils/aiUnlock')

const meta = {
  趣味抽签: ['🎫', '同场同步', 'drinkParty', '趣味抽签', '至少 2 人；随机响铃、喝 1～10 口。'],
  你比划我猜: ['🎭', '同场同步', 'gesture', '你比划我猜', '6 位口令；一人表演肢体，多人猜词。'],
  贴头猜词: ['🎯', '同场同步', 'headband', '贴头猜词', '6 位口令；自己词卡保密，猜对自己获胜。'],
  不要做挑战: ['🚫', '同场同步', 'dontdoit', '不要做挑战', '6 位口令；禁止动作保密，坚持到最后。'],
  AI迷雾推理局: ['🌫️', '同场同步', 'mysteryReason', 'AI迷雾推理', '至少 3 人；AI 剧本，线下口头推理，本机看剧本。'],
  '谁是卧底': ['探', '同场同步', 'undercover', '谁是卧底', '至少 3 人；本机看词与投票。'],
  '真心话大冒险': ['🎲', '同场投票', 'play', '真心话', '4 位口令同房，每人用自己手机投票。'],
  '海龟汤': ['🧩', '推理', 'play', '海龟汤', '看汤面，推理汤底。'],
  '优点轰炸': ['🌟', '夸夸', 'play', '优点轰炸', '轮流夸人，记录金句。'],
  '大瞎话': ['🙈', '指令', 'play', '大瞎话', '随机抽搞怪任务。'],
  '猜数字': ['🔢', '竞猜', 'play', '猜数字', '范围提示，猜中记一分。'],
  '十五二十': ['✋', '互动', 'play', '十五二十', '双人喊数计分。'],
  '你画我猜轮流传词版': ['🎨', '传词', 'drawGuess', '你画我猜', '至少 2 人；同屏画布抢答。'],
  '疯狂猜歌': ['🎵', '听歌', 'songGuess', '猜歌', '组长主持外放、他人抢答。'],
  '倒着说': ['🔁', '反应', 'play', '倒着说', '短句倒序挑战。'],
  '默契大考验': ['💞', '默契', 'play', '默契考验', '同时指人看默契。'],
  '故事接龙': ['📖', '接龙', 'play', '故事接龙', '随机开头一起编。'],
  '逛三园': ['🌳', '限时', 'play', '逛三园', '限时接词不重复。'],
  '123木头人/红绿灯': ['🚦', '户外', 'play', '红绿灯', '随机口令和暂离记录。'],
  '网鱼': ['🐟', '户外', 'play', '网鱼', '随机初始网。'],
  '画一画长卷': ['🧻', '创作', 'play', '长卷画', '随机主题轮流画。'],
  '成语接龙 / 飞花令': ['🌙', '诗词', 'play', '成语飞花', '起始字和提示。'],
  '蒙眼贴五官': ['👀', '亲子', 'play', '贴五官', '难度和计时辅助。'],
  '躲猫猫 / 找影子': ['🫣', '探索', 'play', '找影子', '规则和手影挑战。'],
  '揪尾巴': ['🐒', '运动', 'play', '揪尾巴', '揪到尾巴就加分。'],
  '袋鼠跳跳跳': ['🦘', '运动', 'play', '袋鼠跳', '秒表记录成绩。'],
  '爱心接力 / 齐心协力': ['💗', '合作', 'play', '爱心接力', '随机协作难度。'],
  '我是影帝': ['🎭', '表演', 'play', '我是影帝', '抽场景即兴表演。'],
  '秘密身份推理（聚会版）': ['🎭', '同场同步', 'werewolf', '身份推理', '选 6/8/10/12 人局；本机看身份。']
}

/** 已开放游戏排序；数字越小越靠前。 */
const SORT_TIER = {
  趣味抽签: 0,
  疯狂猜歌: 1,
  真心话大冒险: 2,
  海龟汤: 3,
  贴头猜词: 4,
  不要做挑战: 5,
  AI迷雾推理局: 6
}
/** 开发中卡片统一靠后；数字越小在「开发中」区块内越靠前。 */
const DEV_SORT_TIER = 10

Page({
  data: {
    games: [],
    /** 全站各互动开始次数，用于热门排序 { [title: string]: number } */
    clickRanks: {},
    agentBusy: false,
    aiUnlock: { level: 0, canGen: false, canAssist: false, canRecap: false, nextHint: '' },
    showAiShareModal: false,
    shareCopy: {},
    /** 点击游戏时若未填资料则弹出 */
    showUserInfoModal: false,
    userInfoChecking: false
  },

  buildGameList () {
    return gameGroups.reduce((list, group) => {
      return list.concat(
        group.games
          .map((game) => {
            const item = meta[game.title] || ['🎮', '聚会玩法', 'play', game.title, game.summary]
            return {
              title: game.title,
              icon: item[0],
              tag: item[1],
              screen: item[2],
              displayTitle: item[3],
              displaySummary: item[4],
              devLocked: !isHomeGameEnabled(game.title)
            }
          })
          .filter((g) => g.screen !== 'drawGuess' || isDrawGuessEnabled())
          .filter((g) => g.screen !== 'werewolf' || isWerewolfEnabled())
          .filter((g) => g.screen !== 'mysteryReason' || isMysteryReasonEnabled())
      )
    }, [])
  },

  applyGameSort () {
    const base = this.buildGameList()
    const ranks = (this.data && this.data.clickRanks) || {}
    const withOrder = base.map((g, i) => Object.assign({ _i: i }, g))
    withOrder.sort((a, b) => {
      if (a.devLocked !== b.devLocked) {
        return a.devLocked ? 1 : -1
      }
      const ta = a.devLocked
        ? DEV_SORT_TIER
        : (SORT_TIER[a.title] != null ? SORT_TIER[a.title] : 5)
      const tb = b.devLocked
        ? DEV_SORT_TIER
        : (SORT_TIER[b.title] != null ? SORT_TIER[b.title] : 5)
      if (ta !== tb) {
        return ta - tb
      }
      const ca = ranks[a.title] | 0
      const cb = ranks[b.title] | 0
      if (cb !== ca) {
        return cb - ca
      }
      return a._i - b._i
    })
    const games = withOrder.map((row) => {
      const o = Object.assign({}, row)
      delete o._i
      return o
    })
    this.setData({ games })
  },

  fetchClickRanksDebounced () {
    const now = Date.now()
    if (this._ranksFetchAt && now - this._ranksFetchAt < 60000) {
      return
    }
    this._ranksFetchAt = now
    this.fetchClickRanks()
  },

  fetchClickRanks () {
    if (!wx.cloud) {
      this.applyGameSort()
      return
    }
    if (shouldSkipGameStatsInDevtools()) {
      this.applyGameSort()
      return
    }
    callGameStats(
      { action: 'listRanks' },
      {
        silent: true,
        onOk: (res) => {
          const r = (res && res.result) || {}
          if (r.errMsg) {
            this.applyGameSort()
            return
          }
          const next = r.ranks && typeof r.ranks === 'object' ? r.ranks : {}
          this.setData({ clickRanks: next }, () => this.applyGameSort())
        },
        onError: () => {
          this.applyGameSort()
        }
      }
    )
  },

  refreshAiUnlock () {
    refreshAiUnlockPage(this)
  },

  onCloseAiShareModal () {
    closeAiShareModal(this)
  },

  onAiShareTimeline () {
    closeAiShareModal(this)
    showShareGuide()
  },

  onAiRecommend () {
    const { runPartyRecommend } = require('../../utils/agentHelper')
    runPartyRecommend(this)
  },

  /** 延后非首屏必须的云调用，避免 onLoad/onShow 与冷启动云函数争抢导致 timeout */
  _scheduleIndexCloudWork () {
    if (this._indexCloudTimer) {
      clearTimeout(this._indexCloudTimer)
    }
    this._indexCloudTimer = setTimeout(() => {
      this._indexCloudTimer = null
      if (!this._indexCloudAlive) {
        return
      }
      this.fetchClickRanksDebounced()
      onPageShowUnlock(this)
    }, 400)
  },

  _clearIndexCloudWork () {
    this._indexCloudAlive = false
    if (this._indexCloudTimer) {
      clearTimeout(this._indexCloudTimer)
      this._indexCloudTimer = null
    }
  },

  onLoad (q) {
    enableShareMenus()
    tryRedeemShareFromQuery(q || {})
    // 禁止首页自动弹出聚会形象弹窗
    this.setData({ showUserInfoModal: false })
    this._pendingUserInfoCallback = null
    this._pendingGameEvent = null
    this._indexCloudAlive = true
    this.applyGameSort()
    this.refreshAiUnlock()
    this._scheduleIndexCloudWork()
  },

  onShow () {
    enableShareMenus()
    this._indexCloudAlive = true
    this._scheduleIndexCloudWork()
  },

  onUserInfoModalSuccess () {
    completePendingAction(this)
  },

  onUserInfoModalCancel () {
    this._pendingGameEvent = null
    cancelPendingAction(this)
  },

  onHide () {
    this._clearIndexCloudWork()
    onPageHideUnlock(this)
  },

  onShareAppMessage () {
    return handleShareAppMessage(this, 'index', {})
  },

  onShareTimeline () {
    return handleShareTimeline(this, 'index', {})
  },

  onDevLockedTap() {
    wx.showToast({ title: '正在开发中', icon: 'none' })
  },

  startGame(event) {
    if (this.data.userInfoChecking) {
      return
    }
    const ds = (event.currentTarget && event.currentTarget.dataset) || {}
    const title = (ds.title != null && ds.title !== '') ? String(ds.title) : ''
    if (title && !isHomeGameEnabled(title)) {
      wx.showToast({ title: '正在开发中', icon: 'none' })
      return
    }
    // 保存点击事件，供弹窗「确认并继续」后执行跳转
    this._pendingGameEvent = event
    ensureUserInfo(this, () => {
      const ev = this._pendingGameEvent
      this._pendingGameEvent = null
      if (ev) {
        this._startGameAfterProfile(ev)
      }
    })
  },

  /** 资料已齐全或弹窗保存成功后执行原跳转逻辑 */
  _startGameAfterProfile(event) {
    const ds = (event.currentTarget && event.currentTarget.dataset) || {}
    const title = (ds.title != null && ds.title !== '') ? String(ds.title) : ''
    const screen = (ds.screen != null && ds.screen !== '') ? String(ds.screen) : ''
    if (!title && !screen) {
      return
    }
    if (screen === 'werewolf') {
      if (!isWerewolfEnabled()) {
        wx.showToast({ title: '身份推理暂未开放', icon: 'none' })
        return
      }
      if (title && wx.cloud) {
        callGameStats(
          { action: 'bumpStart', title },
          { silent: true, onOk: () => {}, onError: () => {} }
        )
      }
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=werewolf'
      })
      return
    }
    if (title && !isHomeGameEnabled(title)) {
      wx.showToast({ title: '正在开发中', icon: 'none' })
      return
    }
    if (title && wx.cloud) {
      callGameStats(
        { action: 'bumpStart', title },
        { silent: true, onOk: () => {}, onError: () => {} }
      )
    }
    if (screen === 'songGuess') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=songGuess'
      })
      return
    }
    if (screen === 'drawGuess') {
      if (!isDrawGuessEnabled()) {
        wx.showToast({ title: '你画我猜暂未开放', icon: 'none' })
        return
      }
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=drawGuess'
      })
      return
    }
    if (screen === 'drinkParty') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=drinkParty'
      })
      return
    }
    if (screen === 'headband') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=headband'
      })
      return
    }
    if (screen === 'gesture') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=gesture'
      })
      return
    }
    if (screen === 'dontdoit') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=dontdoit'
      })
      return
    }
    if (screen === 'mysteryReason') {
      if (!isMysteryReasonEnabled()) {
        wx.showToast({ title: 'AI迷雾推理局暂未开放', icon: 'none' })
        return
      }
      wx.navigateTo({
        url:
          '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=mysteryReason'
      })
      return
    }
    wx.navigateTo({
      url:
        '/pages/setup/setup?title=' +
        encodeURIComponent(title) +
        '&screen=' +
        encodeURIComponent(screen || 'play')
    })
  },

  joinRoom() {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    wx.showModal({
      title: '输入口令',
      editable: true,
      placeholderText: '4 位或 6 位数字口令',
      success: (result) => {
        if (!result.confirm) return
        this.joinRoomByCode(result.content)
      }
    })
  },

  joinRoomByCode(raw) {
    if (!wx.cloud) {
      wx.showToast({ title: '请先开通云开发', icon: 'none' })
      return
    }
    const digits = String(raw || '')
      .replace(/\D/g, '')
      .trim()
    if (digits.length === 6) {
      this.joinSixDigitRoom(digits)
      return
    }
    if (digits.length === 4) {
      this.joinCommonRoomByCode(digits)
      return
    }
    wx.showToast({ title: '请输入 4 位或 6 位数字口令', icon: 'none' })
  },

  joinSixDigitRoom(digits) {
    this.joinHeadbandByCode(digits)
  },

  joinHeadbandByCode(digits) {
    wx.showLoading({ title: '加入中' })
    callHeadband(
      withJoinProfile({ action: 'join', roomCode: digits }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            this.handleHeadbandJoinError(digits, { message: r.errMsg })
            return
          }
          if (!r.roomId) {
            this.joinUndercoverByCode(digits, true)
            return
          }
          const cfg = { roomId: r.roomId, roomCode: digits }
          wx.navigateTo({
            url: '/packageGames/headband/headband?config=' + encodeURIComponent(JSON.stringify(cfg))
          })
        },
        onError: (e) => {
          this.handleHeadbandJoinError(digits, e)
        }
      }
    )
  },

  handleHeadbandJoinError(digits, e) {
    const msg = (e && e.message) || ''
    if (/FUNCTION_NOT_FOUND|未部署|502001|headbandRoomService/i.test(msg)) {
      wx.hideLoading()
      wx.showModal({
        title: '贴头猜词未就绪',
        content:
          '云函数 headbandRoomService 未部署或未选对环境。\n\n请在开发者工具：cloudfunctions/headbandRoomService → 上传并部署（云端安装依赖）。',
        showCancel: false
      })
      return
    }
    if (/组不存在|找不到|房间不存在|无效|不存在|已结束/.test(msg)) {
      this.joinGestureByCode(digits, true)
      return
    }
    wx.hideLoading()
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinGestureByCode(digits, fromChain) {
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callGesture(
      withJoinProfile({ action: 'join', roomCode: digits }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            this.handleGestureJoinError(digits, { message: r.errMsg })
            return
          }
          if (!r.roomId) {
            this.joinDontdoitByCode(digits, true)
            return
          }
          const cfg = { roomId: r.roomId, roomCode: digits }
          wx.navigateTo({
            url: '/packageGames/gesture/gesture?config=' + encodeURIComponent(JSON.stringify(cfg))
          })
        },
        onError: (e) => {
          this.handleGestureJoinError(digits, e)
        }
      }
    )
  },

  handleGestureJoinError(digits, e) {
    const msg = (e && e.message) || ''
    if (/FUNCTION_NOT_FOUND|未部署|502001|gestureRoomService/i.test(msg)) {
      wx.hideLoading()
      wx.showModal({
        title: '你比划我猜未就绪',
        content:
          '云函数 gestureRoomService 未部署或未选对环境。\n\n请在开发者工具：cloudfunctions/gestureRoomService → 上传并部署（云端安装依赖）。',
        showCancel: false
      })
      return
    }
    if (/组不存在|找不到|房间不存在|无效|不存在|已结束/.test(msg)) {
      this.joinDontdoitByCode(digits, true)
      return
    }
    wx.hideLoading()
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinDontdoitByCode(digits, fromChain) {
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callDontdoit(
      withJoinProfile({ action: 'join', roomCode: digits }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            this.handleDontdoitJoinError(digits, { message: r.errMsg }, fromChain)
            return
          }
          if (!r.roomId) {
            this.joinUndercoverByCode(digits, true)
            return
          }
          const cfg = { roomId: r.roomId, roomCode: digits }
          wx.navigateTo({
            url: '/packageGames/dontdoit/dontdoit?config=' + encodeURIComponent(JSON.stringify(cfg))
          })
        },
        onError: (e) => {
          this.handleDontdoitJoinError(digits, e, fromChain)
        }
      }
    )
  },

  handleDontdoitJoinError(digits, e, fromChain) {
    const msg = (e && e.message) || ''
    if (/FUNCTION_NOT_FOUND|未部署|502001|dontdoitRoomService/i.test(msg)) {
      if (fromChain) {
        this.joinUndercoverByCode(digits, true)
        return
      }
      wx.hideLoading()
      wx.showModal({
        title: '不要做挑战未就绪',
        content: '请部署云函数 dontdoitRoomService（云端安装依赖）',
        showCancel: false
      })
      return
    }
    if (/组不存在|找不到|房间不存在|无效|不存在|已结束/.test(msg)) {
      this.joinMysteryReasonByCode(digits, true)
      return
    }
    if (fromChain) {
      wx.hideLoading()
    }
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinMysteryReasonByCode(digits, fromChain) {
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callMysteryReason(
      withJoinProfile({ action: 'join', roomCode: digits }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            this.handleMysteryReasonJoinError(digits, { message: r.errMsg }, fromChain)
            return
          }
          if (!r.roomId) {
            this.joinUndercoverByCode(digits, true)
            return
          }
          const cfg = { roomId: r.roomId, roomCode: digits }
          wx.navigateTo({
            url:
              '/packageGames/mystery-reason/mystery-reason?config=' +
              encodeURIComponent(JSON.stringify(cfg))
          })
        },
        onError: (e) => {
          this.handleMysteryReasonJoinError(digits, e, fromChain)
        }
      }
    )
  },

  handleMysteryReasonJoinError(digits, e, fromChain) {
    const msg = (e && e.message) || ''
    if (/FUNCTION_NOT_FOUND|未部署|502001|mysteryReasonRoomService/i.test(msg)) {
      if (fromChain) {
        this.joinUndercoverByCode(digits, true)
        return
      }
      wx.hideLoading()
      wx.showModal({
        title: 'AI迷雾推理局未就绪',
        content: '请部署云函数 mysteryReasonRoomService（云端安装依赖）',
        showCancel: false
      })
      return
    }
    if (/组不存在|找不到|房间不存在|无效|不存在|已结束/.test(msg)) {
      this.joinUndercoverByCode(digits, true)
      return
    }
    if (fromChain) {
      wx.hideLoading()
    }
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinUndercoverByCode(digits, fromHbChain) {
    if (!fromHbChain) {
      wx.showLoading({ title: '加入中' })
    }
    callUndercoverService(
      withJoinProfile({ action: 'join', roomCode: digits }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          const cfg1 = { roomId: r.roomId, roomCode: digits, mode: 'v2' }
          wx.navigateTo({
            url:
              '/packageGames/undercover/undercover?config=' + encodeURIComponent(JSON.stringify(cfg1))
          })
        },
        onError: (e) => {
          this.handleUndercoverJoinError(digits, e, fromHbChain)
        }
      }
    )
  },

  handleUndercoverJoinError(digits, e, fromHbChain) {
    const msg = (e && e.message) || ''
    if (/组不存在|找不到|房间不存在/.test(msg)) {
      this.joinWerewolfByCode(digits, true)
      return
    }
    if (fromHbChain) {
      wx.hideLoading()
    }
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinWerewolfByCode (roomCode, fromUcChain) {
    if (!isWerewolfEnabled()) {
      if (!fromUcChain) {
        wx.hideLoading()
      }
      wx.showToast({ title: '身份推理暂未开放', icon: 'none' })
      return
    }
    if (!fromUcChain) {
      wx.showLoading({ title: '加入中' })
    }
    callWerewolfService(
      withJoinProfile({ action: 'join', roomCode }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r2 = (res && res.result) || {}
          if (!r2.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          const config2 = { roomId: r2.roomId, roomCode: roomCode }
          wx.navigateTo({
            url:
              '/packageGames/werewolf/werewolf?config=' + encodeURIComponent(JSON.stringify(config2))
          })
        },
        onError: (e) => {
          wx.hideLoading()
          if (fromUcChain) {
            const m = (e && e.message) || ''
            if (/组无效|房间无效|不存在|进组|无法|开始/.test(m)) {
              this.joinMusicByCode(roomCode, true)
              return
            }
            wx.showToast({ title: m.slice(0, 18), icon: 'none' })
          } else {
            const m2 = (e && e.message) || '进组失败'
            wx.showToast({ title: m2, icon: 'none' })
          }
        }
      }
    )
  },

  /** 6 位在卧底、身份推理链之后尝试猜歌聚会组 */
  joinMusicByCode (roomCode, fromChain) {
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callMusic(
      withJoinProfile({ action: 'join', roomCode }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          wx.navigateTo({
            url:
              '/packageGames/song-guess/song-guess?roomId=' +
              encodeURIComponent(String(r.roomId)) +
              '&roomCode=' +
              encodeURIComponent(String(roomCode))
          })
        },
        onError: (e) => {
          wx.hideLoading()
          const m = (e && e.message) || ''
          if (fromChain) {
            if (/组|房间|不存在|无效/.test(m)) {
              this.joinDrawByCode(roomCode, true)
            } else {
              wx.showToast({ title: m.slice(0, 20) || '进猜歌组失败', icon: 'none' })
            }
          } else {
            wx.showToast({ title: m || '进组失败', icon: 'none' })
          }
        }
      }
    )
  },

  joinDrawByCode (roomCode, fromChain) {
    if (!isDrawGuessEnabled()) {
      if (fromChain) {
        this.joinDrinkByCode(roomCode, true)
        return
      }
      wx.hideLoading()
      wx.showToast({ title: '你画我猜暂未开放', icon: 'none' })
      return
    }
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callDraw(
      withJoinProfile({ action: 'join', roomCode }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          wx.navigateTo({
            url:
              '/packageGames/draw-guess/draw-guess?roomId=' +
              encodeURIComponent(String(r.roomId)) +
              '&roomCode=' +
              encodeURIComponent(String(roomCode))
          })
        },
        onError: (e) => {
          wx.hideLoading()
          const m = (e && e.message) || ''
          if (fromChain) {
            if (/组|房间|不存在|无效/.test(m)) {
              this.joinDrinkByCode(roomCode, true)
            } else {
              wx.showToast({ title: m.slice(0, 20) || '进组失败', icon: 'none' })
            }
          } else {
            wx.showToast({ title: m || '进组失败', icon: 'none' })
          }
        }
      }
    )
  },

  joinDrinkByCode (roomCode, fromChain) {
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    callDrink(
      withJoinProfile({ action: 'join', roomCode }),
      {
        silent: true,
        onOk: (res) => {
          wx.hideLoading()
          const r = (res && res.result) || {}
          if (r.errMsg) {
            wx.showToast({ title: String(r.errMsg), icon: 'none' })
            return
          }
          if (!r.roomId) {
            wx.showToast({ title: '进组失败', icon: 'none' })
            return
          }
          wx.navigateTo({
            url:
              '/packageGames/drink-party/drink-party?roomId=' +
              encodeURIComponent(String(r.roomId)) +
              '&roomCode=' +
              encodeURIComponent(String(roomCode))
          })
        },
        onError: (e) => {
          wx.hideLoading()
          const m2 = (e && e.message) || ''
          if (fromChain) {
            if (/组|房间|不存在|无效|找不到/.test(m2)) {
              wx.showToast({
                title: '未找到该口令，请确认房主已开房',
                icon: 'none',
                duration: 2800
              })
            } else {
              wx.showToast({ title: m2.slice(0, 20) || '进组失败', icon: 'none' })
            }
          } else {
            wx.showToast({ title: m2 || '进组失败', icon: 'none' })
          }
        }
      }
    )
  },

  joinCommonRoomByCode(roomCode) {
    wx.showLoading({ title: '加入中' })
    callRoomService(
      withJoinProfile({ action: 'join', roomCode }),
      {
        onOk: (res) => {
          wx.hideLoading()
          const r = res.result || {}
          const game = r.selectedGame
          if (!game) {
            wx.showToast({ title: '聚会组数据异常', icon: 'none' })
            return
          }
          if (r.roomCode) {
            game.config = Object.assign({}, game.config || {}, { roomCode: r.roomCode })
          }
          this.goGame(game)
        },
        onError: () => {
          wx.hideLoading()
        }
      }
    )
  },

  goGame(game) {
    const page = game.screen === 'undercover' ? 'undercover' : 'play'
    wx.navigateTo({
      url: `/packageGames/${page}/${page}?title=${encodeURIComponent(game.title)}&config=${encodeURIComponent(JSON.stringify(game.config || {}))}`
    })
  }
})
