#!/usr/bin/env node

/**
 * 调用 initGestureDatabase 云函数来初始化数据库
 */

const fs = require('fs')
const path = require('path')

const configPath = path.join(__dirname, '..', 'cloudbaserc.json')
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
const envId = config.envId

console.log(`📦 环境: ${envId}\n`)
console.log('调用 initGestureDatabase 云函数来创建数据库集合...\n')

// 使用 tcb CLI 调用云函数
const { exec } = require('child_process')

const cmd = `npx -p @cloudbase/cli@3.4.0 tcb fn invoke -f initGestureDatabase --json`

exec(cmd, (error, stdout, stderr) => {
  if (error) {
    console.error('❌ 调用失败:', error.message)
    if (stderr) console.error(stderr)
    process.exit(1)
  }

  try {
    const result = JSON.parse(stdout)
    console.log('✅ 云函数执行完成！\n')
    console.log('返回结果:')
    console.log(JSON.stringify(result, null, 2))

    if (result.code === 0 && result.results) {
      console.log('\n✅ 数据库集合已成功创建:')
      result.results.forEach(r => {
        const icon = r.status === 'success' ? '✅' : '❌'
        console.log(`  ${icon} ${r.collection}: ${r.message}`)
      })
      console.log('\n🎉 初始化完成！现在可以删除 initGestureDatabase 云函数了。')
    }

    process.exit(0)
  } catch (err) {
    console.error('❌ 解析返回结果失败:', err.message)
    console.log('原始输出:', stdout)
    process.exit(1)
  }
})
