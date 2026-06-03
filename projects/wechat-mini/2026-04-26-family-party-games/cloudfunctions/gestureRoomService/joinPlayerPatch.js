/**
 * 进房 / join 时合并头像昵称与「已准备」标记（各玩法云函数共用）
 *
 * 注意：云函数部署时只会打包本函数目录，所以需要在本目录内提供实现，
 * 不能依赖 ../roomService/ 等兄弟目录。
 */
function mergeJoinFields(event, existing) {
  const e = event || {}
  const ex = existing || {}
  const nickName =
    String(e.nickName || ex.nickName || '参与者')
      .trim()
      .slice(0, 12) || '参与者'
  const avatarUrl = String(
    e.avatarUrl != null ? e.avatarUrl : ex.avatarUrl || ''
  ).trim()
  let profileReady = !!ex.profileReady
  if (e.profileReady === true) {
    profileReady = true
  }
  if (e.profileReady === false) {
    profileReady = false
  }
  return { nickName, avatarUrl, profileReady }
}

function withProfileReadyFlag(player) {
  const p = player || {}
  return {
    openId: p.openId,
    nickName: p.nickName,
    avatarUrl: p.avatarUrl || '',
    profileReady: !!p.profileReady
  }
}

module.exports = {
  mergeJoinFields,
  withProfileReadyFlag
}

