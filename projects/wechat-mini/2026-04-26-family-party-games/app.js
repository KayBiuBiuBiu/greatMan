const { enableShareMenus } = require('./utils/shareHelper')
const { ensureCloudInit, getCloudEnvId } = require('./utils/cloudInit')

App({
  onLaunch() {
    // 必须在任意 Page / 云函数调用之前完成初始化
    if (wx.cloud) {
      const envId = getCloudEnvId()
      if (envId) {
        wx.cloud.init({
          env: envId,
          traceUser: true
        })
      } else {
        ensureCloudInit()
      }
      this.globalData.cloudInited = true
    }
    enableShareMenus()
  },

  globalData: {
    appName: '家庭聚会助手',
    cloudInited: false
  }
})
