/**
 * 同房成员列表同步：轮询兜底 + 合并 state / getView 成员数据
 */
const LOBBY_POLL_MS = 3000

function mergePublicPlayers(listA, listB) {
  const map = {}
  function addEach(arr) {
    ;(arr || []).forEach((p) => {
      if (!p || !p.openId) {
        return
      }
      const prev = map[p.openId] || {}
      map[p.openId] = Object.assign({}, prev, p, {
        profileReady: !!(prev.profileReady || p.profileReady)
      })
    })
  }
  addEach(listA)
  addEach(listB)
  return Object.keys(map).map((k) => map[k])
}

function startLobbyPoll(page, refreshFn) {
  stopLobbyPoll(page)
  if (!page || typeof refreshFn !== 'function') {
    return
  }
  page._lobbyPollTimer = setInterval(() => {
    if (!page.data || !page.data.roomId) {
      return
    }
    refreshFn.call(page)
  }, LOBBY_POLL_MS)
}

function stopLobbyPoll(page) {
  if (page && page._lobbyPollTimer) {
    clearInterval(page._lobbyPollTimer)
    page._lobbyPollTimer = null
  }
}

/** 等待大厅阶段持续拉取 gameState（watch 失效时仍能看见新成员） */
function syncLobbyPollByPhase(page, phaseOrStatus, refreshFn) {
  const ph = String(phaseOrStatus || '').trim()
  if (ph === 'waiting' || ph === 'lobby' || !ph) {
    startLobbyPoll(page, refreshFn)
  } else {
    stopLobbyPoll(page)
  }
}

module.exports = {
  LOBBY_POLL_MS,
  mergePublicPlayers,
  startLobbyPoll,
  stopLobbyPoll,
  syncLobbyPollByPhase
}
