const TYPE = { cat: '猫', dog: '狗', other: '异宠' }
Component({
  properties: {
    pet: { type: Object, value: {} }
  },
  data: {
    iconText: '🐾',
    typeLabel: ''
  },
  observers: {
    pet (p) {
      const t = (p && p.category) || 'other'
      this.setData({ typeLabel: TYPE[t] || '宠物', iconText: t === 'cat' ? '🐱' : t === 'dog' ? '🐶' : '🐾' })
    }
  },
  methods: {
    onTap () {
      this.triggerEvent('open', { pet: this.data.pet })
    }
  }
})
