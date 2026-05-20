const { getShareCopyVariant } = require('../../utils/shareUnlockCopy')

Component({
  properties: {
    visible: {
      type: Boolean,
      value: false
    },
    nextHint: {
      type: String,
      value: ''
    },
    shareCopy: {
      type: Object,
      value: {}
    }
  },
  data: {
    copyMain: '分享给好友，请好友点开链接解锁 AI',
    friendBtn: '分享给好友',
    timelineBtn: '分享到朋友圈'
  },
  observers: {
    'shareCopy, visible': function () {
      const c =
        this.properties.shareCopy && Object.keys(this.properties.shareCopy).length
          ? this.properties.shareCopy
          : getShareCopyVariant()
      this.setData({
        copyMain: c.main || this.data.copyMain,
        friendBtn: c.friendBtn || '分享给好友',
        timelineBtn: c.timelineBtn || '分享到朋友圈'
      })
    }
  },
  methods: {
    noop() {},
    onClose() {
      this.triggerEvent('close')
    },
    onTimeline() {
      this.triggerEvent('timeline')
    }
  }
})
