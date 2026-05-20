/**
 * hostAgent / aiPlayer 云函数调用
 */
const { getCallFunctionConfig } = require('./cloudInit')

function ensure() {
  const { ensureCloudInit } = require('./cloudInit')
  return ensureCloudInit()
}

function callHostAgent(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud || !ensure()) {
    onError && onError(new Error('no cloud'))
    return
  }
  wx.cloud.callFunction({
    name: 'hostAgent',
    config: getCallFunctionConfig(),
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg).slice(0, 20), icon: 'none' })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: 'hostAgent 未部署', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

function callAiPlayer(data, opts) {
  const { onOk, onError, silent } = opts || {}
  if (!wx.cloud || !ensure()) {
    onError && onError(new Error('no cloud'))
    return
  }
  wx.cloud.callFunction({
    name: 'aiPlayer',
    config: getCallFunctionConfig(),
    data,
    success: (res) => {
      const r = (res && res.result) || {}
      if (r.errMsg) {
        if (!silent) {
          wx.showToast({ title: String(r.errMsg).slice(0, 20), icon: 'none' })
        }
        onError && onError(new Error(String(r.errMsg)), { result: r })
        return
      }
      onOk && onOk(res)
    },
    fail: (err) => {
      if (!silent) {
        wx.showToast({ title: 'aiPlayer 未部署', icon: 'none' })
      }
      onError && onError(err)
    }
  })
}

module.exports = { callHostAgent, callAiPlayer }
