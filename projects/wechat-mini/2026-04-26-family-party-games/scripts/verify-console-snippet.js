/**
 * 复制到微信开发者工具 Console 执行（上线前验证）
 */
const VERIFY_CONSOLE_SNIPPET = `
const cfg = { env: 'cloud1-d9g01no7m292bc511' }

wx.cloud.callFunction({
  name: 'hostAgent',
  config: cfg,
  data: { action: 'ping' }
}).then(res => console.log('✅ Agent状态:', res.result))

wx.cloud.callFunction({
  name: 'hostAgent',
  config: cfg,
  data: {
    action: 'hostNarrate',
    gameKind: 'undercover',
    roomId: 'test-room',
    scene: 'opening'
  }
}).then(res => console.log('✅ 播报:', res.result))

// 长按首页标题「家庭聚会助手」→ AI 连通 + Agent ping
`

console.log(VERIFY_CONSOLE_SNIPPET)
