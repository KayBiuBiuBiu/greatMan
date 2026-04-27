const { call } = require('../../utils/cloud')
const { formatDateTime } = require('../../utils/format')

const RMAP = { once: '单次', daily: '每日', weekly: '每周', monthly: '每月' }

Page({
  data: {
    list: [],
    show: false,
    form: { title: '', t: '08:00' },
    petNames: [],
    petIds: [],
    fPetIdx: 0,
    reps: ['单次', '每日', '每周', '每月'],
    fRepIdx: 0
  },

  onShow () {
    this.loadPets()
    this.loadList()
  },

  async loadPets () {
    const r = (await call('getPetList')) || {}
    const list = (r.list || []).filter((p) => !p.archived)
    this.setData({ petNames: list.map((p) => p.name), petIds: list.map((p) => p._id) })
  },

  async loadList () {
    const r0 = (await call('getReminderList')) || {}
    const list = (r0.list || []).map((m) => ({
      ...m,
      titleL: m.title || '提醒',
      sub: `${RMAP[m.repeat] || m.repeat} · 下次/参考：${m.nextAt ? formatDateTime(m.nextAt) : '—'}`,
      enabled: m.enabled !== false
    }))
    this.setData({ list })
  },

  onOpen () {
    this.setData({ show: true, form: { title: '', t: '08:00' } })
  },

  onClose () {
    this.setData({ show: false })
  },

  onFt (e) {
    this.setData({ 'form.title': (e.detail && e.detail.value) || '' })
  },

  onTime (e) {
    this.setData({ 'form.t': e.detail.value || '08:00' })
  },

  onPickPet (e) {
    this.setData({ fPetIdx: parseInt(e.detail.value, 10) || 0 })
  },

  onRep (e) {
    this.setData({ fRepIdx: parseInt(e.detail.value, 10) || 0 })
  },

  onRequestSub () {
    wx.showModal({
      content: '订阅消息仅用于您设置的到点养护提示，不发送与养护无关的推送。请在「微信公众平台」为小程序申请对应模板后，在代码中配置 tmplId 即可启用。',
      showCancel: false
    })
  },

  async onSave () {
    const t = (this.data.form.t || '08:00').split(':')
    const d = new Date()
    d.setHours(parseInt(t[0] || 8, 10), parseInt(t[1] || 0, 10), 0, 0)
    const ids = this.data.petIds
    const pidx = this.data.fPetIdx
    const petId = ids[pidx] || (ids[0] || '')
    if (!petId) {
      wx.showToast({ title: '请先在「宠物」页添加档案', icon: 'none' })
      return
    }
    const rkey = ['once', 'daily', 'weekly', 'monthly']
    const repeat = rkey[this.data.fRepIdx] || 'once'
    await call('addReminder', {
      petId,
      title: (this.data.form.title || '养护').slice(0, 50),
      kind: 'feed',
      remindTime: d.getTime(),
      repeat: repeat
    })
    wx.showToast({ title: '已保存' })
    this.setData({ show: false })
    this.loadList()
  },

  async onToggle (e) {
    const id = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.id) || ''
    const on = (e.detail && e.detail.value) != null ? e.detail.value : true
    if (!id) {
      return
    }
    await call('addReminder', { _id: id, enabled: on })
    this.loadList()
  },

  onDel (e) {
    const id = e.currentTarget.dataset.id
    wx.showModal({
      title: '删除该提醒？',
      success: async (m) => {
        if (m.confirm) {
          await call('addReminder', { _deleteId: id })
          this.loadList()
        }
      }
    })
  }
})
