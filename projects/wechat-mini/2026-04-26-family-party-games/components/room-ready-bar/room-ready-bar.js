Component({
  properties: {
    ready: {
      type: Boolean,
      value: false
    }
  },
  methods: {
    onTap() {
      if (this.data.ready) {
        return
      }
      this.triggerEvent('tapready')
    }
  }
})
