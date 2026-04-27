App({
  onLaunch() {
    // 云能力见 utils/roomCloud：首次点「输入口令/生成口令」再 wx.cloud.init，减少冷启动时误报
  },

  globalData: {
    appName: '家庭聚会助手',
    // 由 utils/roomCloud 在首次需要「口令」云能力时置 true（避免未开通云时启动就 init 打日志 / timeout）
    cloudInited: false
  }
})
