/**
 * Minium 测试：向房间注入虚拟玩家（需 event._test === true）
 */
function assertTestAction(e) {
  if (!e || !e._test) {
    throw new Error('test action denied')
  }
}

module.exports = {
  assertTestAction
}
