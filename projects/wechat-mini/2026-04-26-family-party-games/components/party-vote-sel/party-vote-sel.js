/**
 * 投票人列表：点击选中、高亮
 */
Component({
  properties: {
    players: { type: Array, value: [] },
    pick: { type: String, value: '' },
    disabled: { type: Boolean, value: false }
  },
  data: {},
  methods: {
    onTap (e) {
      if (this.data.disabled) {
        return
      }
      const oid = (e && e.currentTarget && e.currentTarget.dataset) ? e.currentTarget.dataset.oid : ''
      if (oid) {
        this.triggerEvent('pick', { toOpenId: oid })
      }
    }
  }
})
