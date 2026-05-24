/**
 * 复制到微信开发者工具 Console 执行（上线前验证）
 */
const VERIFY_CONSOLE_SNIPPET = `
// 微信开发者工具 Console 不支持 require()
const STD_ENV = 'cloud1-d9g01no7m292bc511-d5e875d'
wx.cloud.init({ env: STD_ENV, traceUser: true })

wx.cloud.extend.AI.createModel('hunyuan-v3').generateText({
  model: 'hy3-preview',
  messages: [{ role: 'user', content: '回复一个字：好' }]
}).then(r => {
  if (r.code) return console.error('❌ AI', r)
  const t = r.choices && r.choices[0] && r.choices[0].message && r.choices[0].message.content
  console.log('✅ hunyuan-v3/hy3-preview', t || r)
}).catch(e => console.error('❌ AI', e))

wx.cloud.callFunction({
  name: 'drinkRoomService',
  config: { env: STD_ENV },
  data: { action: 'getOpenId' },
  timeout: 15000
}).then(res => console.log('✅ drink', res.result))
  .catch(err => console.error('❌ drink', err))

wx.cloud.callFunction({
  name: 'hostAgent',
  config: { env: STD_ENV },
  data: { action: 'ping' },
  timeout: 15000
}).then(res => console.log('✅ hostAgent ping', res.result))
`

console.log(VERIFY_CONSOLE_SNIPPET)
