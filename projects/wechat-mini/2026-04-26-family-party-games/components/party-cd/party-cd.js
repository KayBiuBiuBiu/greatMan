/**
 * 倒计时展示（可嵌入趣味抽签等页面）
 * 与 drink-party 主逻辑同规则：以 endAt 为截止，显示 3/2/1/Go
 */
Component({
  properties: {
    endAt: { type: Number, value: 0 },
    active: { type: Boolean, value: false }
  },
  data: { label: '3' },
  observers: {
    'endAt, active' () {
      this.bump()
    }
  },
  methods: {
    bump() {
      if (this._it) {
        clearInterval(this._it)
        this._it = null
      }
      if (!this.data.active || !this.data.endAt) {
        this.setData({ label: '3' })
        return
      }
      const e = this.data.endAt
      this._it = setInterval(() => {
        const remS = (e - Date.now()) / 1000
        if (remS > 0) {
          const s = Math.min(3, Math.max(1, Math.ceil(remS)))
          const m = { 1: '1', 2: '2', 3: '3' }
          this.setData({ label: m[s] || String(s) })
        } else {
          this.setData({ label: 'Go！' })
        }
      }, 100)
    }
  },
  detached() {
    if (this._it) {
      clearInterval(this._it)
    }
  }
})
