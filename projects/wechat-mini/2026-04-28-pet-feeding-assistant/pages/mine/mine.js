Page({
  goK () {
    wx.navigateTo({ url: '/pages/knowledge/knowledge' })
  },
  onPrv () {
    wx.showModal({
      title: '关于隐私',
      content: '本工具主要用于记录与提醒，不会强制收集手机号。若未开通云开发，数据会保存在本机。开通云后仅同步您添加的档案与记录，不用于其他用途。订阅消息需您主动授权，且只用于到点提醒。',
      showCancel: false
    })
  },
  onCache () {
    try {
      wx.clearStorageSync()
    } catch (e) {}
    wx.showToast({ title: '已执行清理', icon: 'none' })
  }
})
