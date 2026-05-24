/**
 * 进房 / join 统一反馈（避免 errMsg 静默、分享链接未 join）
 */
const { withJoinProfile } = require('../../utils/userProfile')

function toastErr(msg) {
  wx.showToast({
    title: String(msg || '操作失败').slice(0, 24),
    icon: 'none'
  })
}

function parseResult(res) {
  return (res && res.result) || {}
}

/**
 * 调用各玩法云函数 join，带 loading 与错误提示
 */
function joinRoomWithUi(callService, payload, handlers) {
  const h = handlers || {}
  if (!wx.cloud) {
    toastErr('请先开通云开发')
    if (h.onFail) {
      h.onFail()
    }
    return
  }
  const data = withJoinProfile(
    Object.assign({ action: 'join' }, payload || {})
  )
  wx.showLoading({ title: h.loadingTitle || '加入中', mask: true })
  callService(data, {
    silent: true,
    onOk: (res) => {
      wx.hideLoading()
      const r = parseResult(res)
      if (r.errMsg) {
        toastErr(r.errMsg)
        if (h.onFail) {
          h.onFail(r)
        }
        return
      }
      if (!r.roomId) {
        toastErr('进组失败')
        if (h.onFail) {
          h.onFail(r)
        }
        return
      }
      if (h.onOk) {
        h.onOk(r)
      }
      if (r.playerCount > 1 && !h.silentJoinToast) {
        wx.showToast({
          title: '已进组，共 ' + (r.playerCount | 0) + ' 人',
          icon: 'none'
        })
      }
    },
    onError: (err) => {
      wx.hideLoading()
      toastErr((err && err.message) || '进组失败，请检查网络')
      if (h.onFail) {
        h.onFail(err)
      }
    }
  })
}

/**
 * 分享/跳转带 roomId+roomCode 时：先 join 写入玩家表，再进入房内 UI
 */
function enterCloudRoomOnLoad(page, opts) {
  const roomId = String((opts && opts.roomId) || '').trim()
  const roomCode = String((opts && opts.roomCode) || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  const callService = opts && opts.callService
  const onReady = opts && opts.onReady
  if (!callService || !onReady) {
    return
  }
  if (roomCode.length === 6) {
    joinRoomWithUi(callService, { roomCode: roomCode }, {
      silentJoinToast: !!(opts && opts.silentJoinToast),
      onOk: (r) => {
        const rid = String(r.roomId || roomId)
        page.setData({
          roomId: rid,
          roomCode: roomCode,
          joinCode: roomCode
        })
        onReady(rid, r)
      },
      onFail: () => {
        if (roomId) {
          page.setData({
            joinCode: roomCode,
            roomCode: roomCode,
          })
        }
      }
    })
    return
  }
  if (roomId) {
    onReady(roomId, null)
  }
}

module.exports = {
  toastErr,
  parseResult,
  joinRoomWithUi,
  enterCloudRoomOnLoad
}
