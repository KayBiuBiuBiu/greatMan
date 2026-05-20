#!/usr/bin/env node
/**
 * 本地冒烟 hostAgent（不替代微信 Console 真机验证）
 * 用法：在项目根目录执行 node scripts/verify-host-agent-local.js
 * 云端验证：需在微信开发者工具 Console 粘贴文档中的脚本
 */
const path = require('path')

process.chdir(path.join(__dirname, '../cloudfunctions/hostAgent'))

async function run() {
  const main = require(path.join(__dirname, '../cloudfunctions/hostAgent/index.js')).main

  console.log('--- 1. ping ---')
  const ping = await main({ action: 'ping' }, {})
  console.log(JSON.stringify(ping, null, 2))
  const pingOk = ping && ping.ok && ping.hasAi
  console.log(pingOk ? '✅ ping 逻辑 OK' : '⚠️ ping 异常（云端部署后 Console 再测）')

  console.log('\n--- 2. hostNarrate（会调 AI，需云环境凭证或可能失败）---')
  try {
    const narr = await main(
      {
        action: 'hostNarrate',
        gameKind: 'undercover',
        roomId: 'test-room',
        scene: 'opening'
      },
      {}
    )
    console.log(JSON.stringify(narr, null, 2))
    const ok = narr && (narr.speakText || narr.text) && !narr.errMsg
    console.log(ok ? '✅ hostNarrate OK' : '⚠️ ' + (narr.errMsg || '无 speakText'))
  } catch (e) {
    console.log('⚠️ hostNarrate 本地失败（正常，请在微信 Console 测）:', e.message)
  }
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
