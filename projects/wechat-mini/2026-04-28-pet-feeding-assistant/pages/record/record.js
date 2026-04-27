const { call } = require('../../utils/cloud')
const { formatDateTime } = require('../../utils/format')

const KIND = [
  { k: 'all', t: '全部' },
  { k: 'feed', t: '喂养' },
  { k: 'water', t: '饮水' },
  { k: 'vaccine', t: '疫苗' },
  { k: 'deworm', t: '驱虫' },
  { k: 'exam', t: '体检' },
  { k: 'med', t: '用药' }
]
const TMAP = { feed: '喂养', water: '饮水', vaccine: '疫苗', deworm: '驱虫', exam: '体检', med: '用药' }

Page({
  data: {
    typeNames: KIND.map((p) => p.t),
    typeIdx: 0,
    typeKey: 'all',
    rangeNames: ['近7天', '近30天', '全部'],
    rangeIdx: 0,
    rangeKey: 7,
    list: [],
    timeline: false,
    showAdd: false,
    addKinds: ['喂养', '饮水', '疫苗', '驱虫', '体检', '用药'],
    addKindIdx: 0,
    petNames: [],
    petIds: [],
    addPetIdx: 0,
    addTitle: '',
    addDet: ''
  },

  onShow () {
    this.loadPets()
    this.loadList()
  },

  async loadPets () {
    const r = (await call('getPetList')) || {}
    const list = (r.list || []).filter((p) => !p.archived)
    this.setData({
      petNames: list.map((p) => p.name),
      petIds: list.map((p) => p._id)
    })
  },

  onTypeF (e) {
    const i = parseInt(e.detail.value, 10) || 0
    const k = KIND[i] ? KIND[i].k : 'all'
    this.setData({ typeIdx: i, typeKey: k }, () => this.loadList())
  },

  onRangeF (e) {
    const i = parseInt(e.detail.value, 10) || 0
    const m = [7, 30, 'all']
    this.setData({ rangeIdx: i, rangeKey: m[i] }, () => this.loadList())
  },

  async loadList () {
    const t = this.data.typeKey
    const rng = this.data.rangeKey
    const r0 = (await call('getRecordList', { type: t, range: rng })) || {}
    const list0 = (r0.list || []).map((r) => ({
      ...r,
      kLabel: TMAP[r.kind] || r.kind,
      timeL: formatDateTime(r.recordTime)
    }))
    this.setData({ list: list0 })
  },

  onViewSwitch () {
    this.setData({ timeline: !this.data.timeline })
  },

  onOpenAdd () {
    const pr = wx.getStorageSync('record_prefill') || {}
    const j = ['feed', 'water', 'vaccine', 'deworm', 'exam', 'med']
    let kidx = 0
    if (pr.kind && j.indexOf(pr.kind) >= 0) {
      kidx = j.indexOf(pr.kind)
    }
    this.setData({ showAdd: true, addTitle: '', addDet: '', addKindIdx: kidx })
    wx.removeStorageSync('record_prefill')
  },

  onCloseAdd () {
    this.setData({ showAdd: false })
  },

  onAddKind (e) {
    this.setData({ addKindIdx: parseInt(e.detail.value, 10) || 0 })
  },

  onAddPetP (e) {
    this.setData({ addPetIdx: parseInt(e.detail.value, 10) || 0 })
  },

  onAddTitle (e) {
    this.setData({ addTitle: (e.detail && e.detail.value) || '' })
  },

  onAddDet (e) {
    this.setData({ addDet: (e.detail && e.detail.value) || '' })
  },

  async onSubmitAdd () {
    const ids = this.data.petIds
    const pidx = this.data.addPetIdx
    const petId = ids[pidx] || (ids[0] || '')
    if (!petId) {
      wx.showToast({ title: '请先在「宠物」页添加档案', icon: 'none' })
      return
    }
    const j = ['feed', 'water', 'vaccine', 'deworm', 'exam', 'med']
    const kind = j[this.data.addKindIdx] || 'feed'
    await call('addRecord', {
      petId,
      kind,
      title: this.data.addTitle || (TMAP[kind] + '记录'),
      detail: this.data.addDet || '',
      recordTime: Date.now()
    })
    wx.showToast({ title: '已保存' })
    this.setData({ showAdd: false })
    this.loadList()
  },

  onDel (e) {
    const id = e.currentTarget.dataset.id
    wx.showModal({
      title: '删除此条？',
      success: async (m) => {
        if (m.confirm) {
          await call('addRecord', { _deleteId: id })
          this.loadList()
        }
      }
    })
  }
})
