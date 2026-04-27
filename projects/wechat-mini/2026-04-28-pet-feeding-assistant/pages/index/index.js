const { call } = require('../../utils/cloud')
const { formatDate, startOfDay, endOfDay } = require('../../utils/format')

function todayRange () {
  const n = new Date()
  return { t0: startOfDay(n), t1: endOfDay(n) }
}

const KINDS = { feed: '喂养', water: '饮水', vaccine: '疫苗', deworm: '驱虫', med: '用药' }

Page({
  data: {
    pets: [],
    todos: []
  },

  onShow () {
    this.loadAll()
  },

  async loadAll () {
    const p = (await call('getPetList')) || {}
    const pets = (p.list || []).filter((x) => !x.archived).slice(0, 6)
    const m0 = (await call('getReminderList')) || {}
    const reminders = m0.list || []
    const { t0, t1 } = todayRange()
    const todos = []
    const doneKey = 'todo_mark_' + formatDate(t0)
    const store0 = wx.getStorageSync(doneKey)
    const markObj =
      store0 && typeof store0 === 'object' && store0.marks
        ? store0.marks
        : {}

    reminders.forEach((m) => {
      if (m.enabled === false) {
        return
      }
      const next = m.nextAt || m.remindTime || 0
      if (next < t0 || next > t1) {
        return
      }
      const id = m._id
      todos.push({
        id: 'm_' + id,
        mid: id,
        title: (KINDS[m.kind] || m.kind || '提醒') + '：' + (m.title || ''),
        desc: '对应宠物可至提醒页查看',
        done: !!markObj['m' + id]
      })
    })
    this.setData({ pets, todos })
  },

  onOpenPet (e) {
    const p = (e.detail && e.detail.pet) || {}
    if (!p || !p._id) {
      return
    }
    wx.setStorageSync('pet_detail_id', p._id)
    wx.switchTab({ url: '/pages/pet/pet' })
  },

  onQuick (e) {
    const k = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.kind) || 'feed'
    wx.setStorageSync('record_prefill', { kind: k })
    wx.switchTab({ url: '/pages/record/record' })
  },

  onGoReminder () {
    wx.switchTab({ url: '/pages/reminder/reminder' })
  },

  onToggleTodo (e) {
    const d = (e.currentTarget && e.currentTarget.dataset) || {}
    const { t0 } = todayRange()
    const key = 'todo_mark_' + formatDate(t0)
    const o = wx.getStorageSync(key) || { marks: {} }
    o.marks = o.marks || {}
    const mk = 'm' + d.mid
    o.marks[mk] = !o.marks[mk]
    wx.setStorageSync(key, o)
    this.loadAll()
  }
})
