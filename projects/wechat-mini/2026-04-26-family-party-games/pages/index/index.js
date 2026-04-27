const { gameGroups } = require('../../data/game-data')
const { callRoomService } = require('../../utils/roomCloud')
const { callWerewolfService } = require('../../utils/werewolfCloud')
const { callUndercoverService } = require('../../utils/undercoverRoomCloud')
const { callGameStats } = require('../../utils/gameStatsCloud')
const { callMusic } = require('../../utils/musicRoomCloud')
const { callDraw } = require('../../utils/drawRoomCloud')
const { callDrink } = require('../../utils/drinkRoomCloud')

const meta = {
  趣味抽签: ['🎫', '同场同步', 'drinkParty', '趣味抽签', '6 位聚会组：倒计时、响铃、投票、趣味小任务记数，同屏同步。'],
  '谁是卧底': ['探', '同场同步', 'undercover', '谁是卧底', '6 位+同场同步，本机词与票。'],
  '真心话大冒险': ['🎲', '抽题', 'play', '真心话', '随机问答题，同场可大家投票。'],
  '海龟汤': ['🧩', '推理', 'play', '海龟汤', '看汤面，推理汤底。'],
  '优点轰炸': ['🌟', '夸夸', 'play', '优点轰炸', '轮流夸人，记录金句。'],
  '大瞎话': ['🙈', '指令', 'play', '大瞎话', '随机抽搞怪任务。'],
  '猜数字': ['🔢', '竞猜', 'play', '猜数字', '范围提示，猜中记一分。'],
  '十五二十': ['✋', '互动', 'play', '十五二十', '双人喊数计分。'],
  '你画我猜轮流传词版': ['🎨', '传词', 'drawGuess', '你画我猜', '6 位+同场同步画布抢答。'],
  '疯狂猜歌': ['🎵', '听歌', 'songGuess', '猜歌', '6 位+同场，随机主持外放、他人抢答。'],
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
  '秘密身份推理（聚会版）': ['🎭', '同场同步', 'werewolf', '身份推理', '6 位口令进聚会组，本机看身份。']
}

/** 首页同场同步类互动优先排序；数字越小越靠前。 */
const SORT_TIER = {
  趣味抽签: 0,
  你画我猜轮流传词版: 0,
  疯狂猜歌: 0,
  '秘密身份推理（聚会版）': 1,
  谁是卧底: 1
}
const ONLINE_SCREEN = (s) => s === 'werewolf' || s === 'undercover' || s === 'songGuess' || s === 'drawGuess' || s === 'drinkParty'

Page({
  data: {
    games: [],
    /** 全站各互动开始次数，用于热门排序 { [title: string]: number } */
    clickRanks: {}
  },

  buildGameList () {
    return gameGroups.reduce((list, group) => {
      return list.concat(group.games.map((game) => {
        const item = meta[game.title] || ['🎮', '聚会玩法', 'play', game.title, game.summary]
        return {
          title: game.title,
          icon: item[0],
          tag: item[1],
          screen: item[2],
          displayTitle: item[3],
          displaySummary: item[4]
        }
      }))
    }, [])
  },

  applyGameSort () {
    const base = this.buildGameList()
    const ranks = (this.data && this.data.clickRanks) || {}
    const withOrder = base.map((g, i) => Object.assign({ _i: i }, g))
    withOrder.sort((a, b) => {
      const ta = (SORT_TIER[a.title] != null) ? SORT_TIER[a.title] : (ONLINE_SCREEN(a.screen) ? 2 : 3)
      const tb = (SORT_TIER[b.title] != null) ? SORT_TIER[b.title] : (ONLINE_SCREEN(b.screen) ? 2 : 3)
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

  fetchClickRanks () {
    if (!wx.cloud) {
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

  onLoad () {
    this.applyGameSort()
    this.fetchClickRanks()
  },

  onShow () {
    this.fetchClickRanks()
  },

  startGame(event) {
    const ds = (event.currentTarget && event.currentTarget.dataset) || {}
    const title = (ds.title != null && ds.title !== '') ? String(ds.title) : ''
    const screen = (ds.screen != null && ds.screen !== '') ? String(ds.screen) : ''
    if (!title && !screen) {
      return
    }
    if (title && wx.cloud) {
      callGameStats(
        { action: 'bumpStart', title },
        { silent: true, onOk: () => {}, onError: () => {} }
      )
    }
    if (screen === 'werewolf') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=werewolf'
      })
      return
    }
    if (screen === 'songGuess') {
      wx.navigateTo({
        url: '/pages/setup/setup?title=' + encodeURIComponent(title) + '&screen=songGuess'
      })
      return
    }
    if (screen === 'drawGuess') {
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
    wx.navigateTo({
      url:
        '/pages/setup/setup?title=' +
        encodeURIComponent(title) +
        '&screen=' +
        encodeURIComponent(screen || 'play')
    })
  },

  joinRoom() {
    wx.showModal({
      title: '输入口令',
      editable: true,
      placeholderText: '4 位如 1333 或 6 位进身份推理',
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
    wx.showToast({ title: '请输入 4 位或 6 位数字', icon: 'none' })
  },

  joinSixDigitRoom(digits) {
    wx.showLoading({ title: '加入中' })
    callUndercoverService(
      { action: 'join', roomCode: digits, nickName: '参与者' },
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
              '/pages/undercover/undercover?config=' + encodeURIComponent(JSON.stringify(cfg1))
          })
        },
        onError: (e) => {
          this.handleUndercoverJoinError(digits, e)
        }
      }
    )
  },

  handleUndercoverJoinError(digits, e) {
    const msg = (e && e.message) || ''
    if (/组不存在|找不到|房间不存在/.test(msg)) {
      this.joinWerewolfByCode(digits, true)
      return
    }
    wx.hideLoading()
    wx.showToast({ title: msg || '进组失败', icon: 'none' })
  },

  joinWerewolfByCode (roomCode, fromUcChain) {
    if (!fromUcChain) {
      wx.showLoading({ title: '加入中' })
    }
    callWerewolfService(
      { action: 'join', roomCode, nickName: '参与者' },
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
              '/pages/werewolf/werewolf?config=' + encodeURIComponent(JSON.stringify(config2))
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
    const nick = (wx.getStorageSync('music_nick') || '参与者').toString()
    callMusic(
      { action: 'join', roomCode, nickName: nick.slice(0, 12) || '参与者' },
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
              '/pages/song-guess/song-guess?roomId=' +
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
    if (!fromChain) {
      wx.showLoading({ title: '加入中' })
    }
    const nick = (wx.getStorageSync('draw_nick') || '参与者').toString()
    callDraw(
      { action: 'join', roomCode, nickName: nick.slice(0, 12) || '参与者' },
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
              '/pages/draw-guess/draw-guess?roomId=' +
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
    const nick = (wx.getStorageSync('drink_nick') || '参与者').toString()
    callDrink(
      { action: 'join', roomCode, nickName: nick.slice(0, 12) || '参与者' },
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
              '/pages/drink-party/drink-party?roomId=' +
              encodeURIComponent(String(r.roomId)) +
              '&roomCode=' +
              encodeURIComponent(String(roomCode))
          })
        },
        onError: (e) => {
          wx.hideLoading()
          const m2 = (e && e.message) || ''
          if (fromChain) {
            if (/组|房间|不存在|无效/.test(m2)) {
              wx.showToast({
                title: '该 6 位非本程序已开同场聚会组',
                icon: 'none'
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
      { action: 'join', roomCode, nickName: '参与者' },
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
      url: `/pages/${page}/${page}?title=${encodeURIComponent(game.title)}&config=${encodeURIComponent(JSON.stringify(game.config || {}))}`
    })
  }
})
