/**
 * 进房时合并头像昵称（与 dontdoit 等玩法一致）
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
  if (e.profileReady === true) profileReady = true
  if (e.profileReady === false) profileReady = false
  return { nickName, avatarUrl, profileReady }
}

function withProfileReadyFlag(player) {
  const p = player || {}
  const out = {
    openId: p.openId,
    nickName: p.nickName,
    avatarUrl: p.avatarUrl || '',
    profileReady: !!p.profileReady,
    isReady: !!p.isReady
  }
  if (p.roleName) out.roleName = p.roleName
  if (p.displayName) out.displayName = p.displayName
  return out
}

module.exports = { mergeJoinFields, withProfileReadyFlag }
