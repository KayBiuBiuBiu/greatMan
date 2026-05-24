/**
 * 等待大厅「准备」：拉取头像昵称并同步到玩法玩家表
 */
const { ensureUserInfo, completePendingAction, cancelPendingAction } = require('../../utils/userHelper')
const { withJoinProfile } = require('../../utils/userProfile')

function resolveLobbyMyOpenId(page, myOpenId) {
  return (
    String(myOpenId || '').trim() ||
    String((page && page.data && page.data.myOpenId) || '').trim() ||
    String((page && page.data && page.data.view && page.data.view.myOpenId) || '').trim() ||
    String((page && page.data && page.data.tdMyOpenId) || '').trim()
  )
}

function resolveSelfProfileReady(fromServer, page) {
  if (page && page._lobbySelfReadySticky === true) {
    return true
  }
  return !!fromServer
}

function syncLobbyStickyWithServer(page, fromServer) {
  if (!page) {
    return
  }
  if (page._lobbySelfReadySticky === true && fromServer) {
    page._lobbySelfReadySticky = null
  }
}

function overlayLobbyProfileReady(players, myOpenId, page) {
  const oid = resolveLobbyMyOpenId(page, myOpenId)
  if (!oid) {
    return players || []
  }
  return (players || []).map((p) => {
    if (!p || p.openId !== oid) {
      return p
    }
    const fromServer = !!p.profileReady
    const nextReady = resolveSelfProfileReady(fromServer, page)
    if (nextReady === fromServer) {
      return p
    }
    return Object.assign({}, p, { profileReady: nextReady })
  })
}

function optimisticLobbyUiPatch(page, ready, myOpenId) {
  if (!page || !page.data) {
    return { lobbySelfReady: !!ready }
  }
  const oid = resolveLobbyMyOpenId(page, myOpenId)
  const dp = page.data.displayPlayers
  const patch = { lobbySelfReady: !!ready }
  if (!dp || !dp.length || !oid) {
    return patch
  }
  patch.displayPlayers = dp.map((p) => {
    if (!p || p.openId !== oid || p.isHost) {
      return p
    }
    return Object.assign({}, p, {
      ready: !!ready,
      readyLabel: ready ? '已准备' : '未准备'
    })
  })
  return patch
}

function markLobbyProfileReady(page, opts, ready) {
  const o = opts || {}
  const callService = o.callService
  if (!callService || !page) {
    return
  }
  const roomId = String(o.roomId || '').trim()
  const rawCode = String(o.roomCode || '').replace(/\D/g, '')
  const payload = withJoinProfile({
    action: 'join',
    profileReady: ready === true
  })
  if (rawCode.length === 6 || rawCode.length === 4) {
    payload.roomCode = rawCode
  }
  if (roomId) {
    payload.roomId = roomId
  }
  wx.showLoading({ title: '提交准备', mask: true })
  if (typeof callService !== 'function') {
    wx.hideLoading()
    return
  }
  callService(payload, {
    silent: true,
    onOk: () => {
      wx.hideLoading()
      page._lobbySelfReadySticky = true
      page.setData(optimisticLobbyUiPatch(page, true, o.myOpenId))
      wx.showToast({
        title: '已准备',
        icon: 'success'
      })
      if (typeof o.onSynced === 'function') {
        o.onSynced()
      }
    },
    onError: (err, hint) => {
      wx.hideLoading()
      wx.showToast({
        title:
          (hint && hint.text) ||
          (err && err.message) ||
          '准备失败，请重试',
        icon: 'none'
      })
    }
  })
}

function tapLobbyReady(page, opts) {
  if (!page) {
    return
  }
  if (page.data && page.data.lobbySelfReady) {
    return
  }
  ensureUserInfo(page, () => {
    markLobbyProfileReady(page, opts || {}, true)
  })
}

function onLobbyUserInfoSuccess(page) {
  if (!page) {
    return
  }
  const cb = page._pendingUserInfoCallback
  if (typeof cb === 'function') {
    completePendingAction(page)
    return
  }
  const o = page._lobbyReadyOpts
  if (o) {
    markLobbyProfileReady(page, o, true)
  }
}

function onLobbyUserInfoCancel(page) {
  if (!page) {
    return
  }
  page._lobbyReadyOpts = null
  cancelPendingAction(page)
}

function bindLobbyReadyTap(page, opts) {
  if (page) {
    page._lobbyReadyOpts = opts || null
  }
  tapLobbyReady(page, opts)
}

function lobbyGuestReadyStats(players, hostOpenId, page, myOpenId) {
  const host = String(hostOpenId || '').trim()
  const list = page
    ? overlayLobbyProfileReady(players, myOpenId, page)
    : players || []
  let guestCount = 0
  let readyCount = 0
  list.forEach((p) => {
    if (!p || !p.openId) {
      return
    }
    if (host && p.openId === host) {
      return
    }
    guestCount += 1
    if (p.profileReady) {
      readyCount += 1
    }
  })
  return {
    guestCount,
    readyCount,
    allReady: guestCount === 0 || readyCount >= guestCount
  }
}

function patchLobbySelfReady(patch, players, myOpenId, inWaiting, page) {
  if (!inWaiting) {
    return patch
  }
  const oid = resolveLobbyMyOpenId(page, myOpenId)
  if (!oid) {
    patch.lobbySelfReady = resolveSelfProfileReady(false, page)
    return patch
  }
  const me = (players || []).find((p) => p && p.openId === oid)
  const fromServer = !!(me && me.profileReady)
  syncLobbyStickyWithServer(page, fromServer)
  patch.lobbySelfReady = resolveSelfProfileReady(fromServer, page)
  return patch
}

module.exports = {
  tapLobbyReady,
  bindLobbyReadyTap,
  markLobbyProfileReady,
  markReadyOnServer: (page, opts) => markLobbyProfileReady(page, opts, true),
  lobbyGuestReadyStats,
  onLobbyUserInfoSuccess,
  onLobbyUserInfoCancel,
  patchLobbySelfReady,
  resolveLobbyMyOpenId,
  overlayLobbyProfileReady,
  resolveSelfProfileReady
}
