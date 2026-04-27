const { CLOUD_ENV_ID } = require('./cloud-env')

App({
  onLaunch() {
    if (wx.cloud) {
      wx.cloud.init({
        env: CLOUD_ENV_ID || wx.cloud.DYNAMIC_CURRENT_ENV,
        traceUser: true
      })
    }
  },
  globalData: {
    appName: '宠伴日常',
    cloudReady: false
  }
})
