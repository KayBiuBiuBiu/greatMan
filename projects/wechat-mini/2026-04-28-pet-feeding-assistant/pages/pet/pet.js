const { call } = require('../../utils/cloud')
const breeds = require('../../data/breeds.js')

const MAP = { 猫: 'cat', 狗: 'dog', 异宠: 'other' }
const MAPR = { cat: '猫', dog: '狗', other: '异宠' }

Page({
  data: {
    view: 'list',
    cat: 'all',
    all: [],
    filtered: [],
    cur: null,
    form: { name: '', category: 'cat', breed: '', birthday: '', gender: '未知', weight: '', neutered: false, note: '', photo: '' },
    formCatIdx: 0,
    formCatLabel: '猫',
    formBreedIdx: 0,
    breedOptions: breeds.cat,
    formGenIdx: 0,
    curType: ''
  },

  onShow () {
    const id = wx.getStorageSync('pet_detail_id')
    if (id) {
      wx.removeStorageSync('pet_detail_id')
      this._openId = id
      this.setData({ view: 'detail' }, () => this.loadDetail())
      return
    }
    if (this.data.view === 'list') {
      this.loadList()
    }
  },

  async loadList () {
    const r = (await call('getPetList')) || {}
    const all = (r.list || []).filter((p) => !p.archived)
    this.setData({ all, view: 'list' }, () => this.filter())
  },

  filter () {
    const { cat, all } = this.data
    const filtered = cat === 'all' ? all : all.filter((p) => p.category === cat)
    this.setData({ filtered })
  },

  onCat (e) {
    const c = e.currentTarget.dataset.c
    this.setData({ cat: c }, () => this.filter())
  },

  onAdd () {
    this.setData({
      view: 'form',
      form: { name: '', category: 'cat', breed: '', birthday: '', gender: '未知', weight: '', neutered: false, note: '', photo: '' },
      formCatIdx: 0,
      formCatLabel: '猫',
      formBreedIdx: 0,
      breedOptions: breeds.cat
    })
  },

  onF (e) {
    const k = e.currentTarget.dataset.k
    this.setData({ ['form.' + k]: (e.detail && e.detail.value) || '' })
  },

  onPickCat (e) {
    const i = parseInt(e.detail.value, 10) || 0
    const labels = ['猫', '狗', '异宠']
    const lab = labels[i] || '猫'
    const key = MAP[lab]
    const b = key === 'cat' ? breeds.cat : key === 'dog' ? breeds.dog : breeds.other
    this.setData({
      'form.category': key,
      formCatIdx: i,
      formCatLabel: lab,
      breedOptions: b,
      formBreedIdx: 0,
      'form.breed': b[0] || ''
    })
  },

  onPickBreed (e) {
    const i = parseInt(e.detail.value, 10) || 0
    const o = this.data.breedOptions || []
    this.setData({ 'form.breed': o[i] || '', formBreedIdx: i })
  },

  onPickGen (e) {
    const i = parseInt(e.detail.value, 10) || 0
    const g = ['未知', '公', '母'][i] || '未知'
    this.setData({ 'form.gender': g, formGenIdx: i })
  },

  onNeu (e) {
    this.setData({ 'form.neutered': e.detail.value })
  },

  onChoosePhoto () {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      success: (res) => {
        const t = (res.tempFiles && res.tempFiles[0] && res.tempFiles[0].tempFilePath) || ''
        if (t) {
          this.setData({ 'form.photo': t })
        }
      }
    })
  },

  async onSave () {
    const f = this.data.form
    if (!f.name || !f.name.trim()) {
      wx.showToast({ title: '请填写昵称', icon: 'none' })
      return
    }
    const payload = Object.assign({}, f, { name: f.name.trim() })
    if (this._editId) {
      payload._id = this._editId
    }
    await call('addPet', payload)
    this._editId = null
    wx.showToast({ title: '已保存', icon: 'success' })
    this.loadList()
  },

  onOpen (e) {
    const p = (e.detail && e.detail.pet) || {}
    this._openId = p._id
    this.setData({ view: 'detail' }, () => this.loadDetail())
  },

  async loadDetail () {
    const r = (await call('getPetList')) || {}
    const p = (r.list || []).find((x) => x._id === this._openId)
    this.setData({
      cur: p,
      curType: p ? MAPR[p.category] || '宠物' : ''
    })
  },

  onEdit () {
    const c = this.data.cur
    if (!c) {
      return
    }
    this._editId = c._id
    const idx = c.category === 'dog' ? 1 : c.category === 'other' ? 2 : 0
    const lab = ['猫', '狗', '异宠'][idx]
    const bopt = c.category === 'cat' ? breeds.cat : c.category === 'dog' ? breeds.dog : breeds.other
    const bi = Math.max(0, bopt.indexOf(c.breed))
    this.setData({
      view: 'form',
      form: {
        name: c.name,
        category: c.category,
        breed: c.breed,
        birthday: c.birthday,
        gender: c.gender || '未知',
        weight: c.weight,
        neutered: !!c.neutered,
        note: c.note,
        photo: c.photo
      },
      formCatIdx: idx,
      formCatLabel: lab,
      formBreedIdx: bi,
      breedOptions: bopt
    })
  },

  async onArchive () {
    const id = (this.data.cur && this.data.cur._id) || ''
    if (!id) {
      return
    }
    await call('addPet', { _id: id, archived: true })
    wx.showToast({ title: '已归档', icon: 'none' })
    this.setData({ view: 'list' }, () => this.loadList())
  },

  onDel () {
    wx.showModal({
      title: '确认删除',
      content: '将删除本档案的本地/云端数据关联（若云已同步）。此操作请谨慎。',
      success: async (m) => {
        if (m.confirm) {
          const id = (this.data.cur && this.data.cur._id) || ''
          await call('addPet', { _id: id, archived: true, deleted: 1 })
          this.setData({ view: 'list' }, () => this.loadList())
        }
      }
    })
  },

  onBackList () {
    this._editId = null
    this.setData({ view: 'list' }, () => this.loadList())
  }
})
