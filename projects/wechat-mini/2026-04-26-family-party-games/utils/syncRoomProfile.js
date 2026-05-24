/**
 * 进房后静默 re-join，把最新头像昵称写入玩法玩家表
 */
const { withJoinProfile } = require('./userProfile')

function silentRejoin(callService, payload, handlers) {
  const data = withJoinProfile(Object.assign({ action: 'join' }, payload || {}))
  const opts = Object.assign({ silent: true }, handlers || {})
  callService(data, opts)
}

module.exports = {
  silentRejoin
}
