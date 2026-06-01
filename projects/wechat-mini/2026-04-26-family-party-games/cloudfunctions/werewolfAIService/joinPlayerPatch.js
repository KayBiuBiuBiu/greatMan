/** 与 werewolfService 一致的进房字段合并 */
function withProfileReadyFlag(player) {
  const p = player || {}
  return {
    openId: p.openId,
    nickName: p.nickName,
    avatarUrl: p.avatarUrl || '',
    profileReady: !!p.profileReady
  }
}

module.exports = { withProfileReadyFlag }
