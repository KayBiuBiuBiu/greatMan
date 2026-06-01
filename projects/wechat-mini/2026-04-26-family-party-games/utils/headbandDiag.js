/**
 * 贴头猜词 · 一键连通性诊断（建房失败时先用这个）
 */
const { callHeadband } = require('./headbandCloud')
const { getCloudEnvId, getCallFunctionConfig } = require('./cloudInit')

const HB_BUILD_ID = 'headband-repo-v8'

function step(lines, name, ok, detail) {
  lines.push((ok ? '✅ ' : '❌ ') + name + (detail ? '\n   ' + detail : ''))
}

function showDiagReport(lines) {
  const env = getCloudEnvId() || '(未配置 envId)'
  const body = '环境：' + env + '\n\n' + lines.join('\n\n')
  wx.showModal({
    title: lines.every((l) => l.indexOf('✅') === 0) ? '诊断通过' : '诊断有问题',
    content: body.slice(0, 900),
    showCancel: false
  })
  /* eslint-disable no-console */
  console.log('[headband 诊断]\n' + body)
  /* eslint-enable no-console */
}

/**
 * 依次检测：云环境 → headbandRoomService → 数据库集合 → aiPartyService
 */
function runHeadbandDiag() {
  if (!wx.cloud) {
    showDiagReport(['❌ 未开通云开发'])
    return
  }
  const lines = []
  const env = getCloudEnvId()
  step(lines, 'cloud-env.js envId', !!env, env || '请在 cloud-env.js 填写 envId')

  wx.showLoading({ title: '诊断中', mask: true })

  callHeadband(
    { action: 'ping' },
    {
      silent: true,
      onOk: (res) => {
        const r = (res && res.result) || {}
        if (r.errMsg) {
          step(lines, 'headbandRoomService', false, r.errMsg)
          wx.hideLoading()
          showDiagReport(lines)
          return
        }
        const buildOk = r.buildId === HB_BUILD_ID
        const hbOk = !!(r.ok && r.roomsOk && r.playersOk && buildOk)
        step(
          lines,
          'headbandRoomService',
          hbOk,
          hbOk
            ? 'buildId=' + r.buildId + '，集合可访问'
            : !buildOk
              ? '版本不对（需 buildId=' + HB_BUILD_ID + '），请重传本仓库云函数'
              : [
                r.roomsOk ? '' : 'rooms: ' + (r.roomsErr || '不可访问'),
                r.playersOk ? '' : 'players: ' + (r.playersErr || '不可访问')
              ]
                .filter(Boolean)
                .join('；') || 'ping 未通过'
        )

        wx.cloud.callFunction({
          name: 'aiPartyService',
          config: getCallFunctionConfig(),
          data: {
            action: 'chat',
            system: '你是测试助手，只返回一句话。',
            prompt: '回复：AI 可用'
          },
          success: (res2) => {
            wx.hideLoading()
            const r2 = (res2 && res2.result) || {}
            step(
              lines,
              'aiPartyService',
              !!(r2.text && !r2.errMsg),
              r2.errMsg || (r2.text ? '返回：' + String(r2.text).slice(0, 30) : '未返回 text')
            )
            showDiagReport(lines)
          },
          fail: (err) => {
            wx.hideLoading()
            const m = (err && (err.errMsg || err.message)) || '调用失败'
            step(
              lines,
              'aiPartyService',
              false,
              /NOT_FOUND|未部署/i.test(m)
                ? m + '\n   请在云开发控制台确认该函数已部署到同一环境'
                : m
            )
            showDiagReport(lines)
          }
        })
      },
      onError: (err) => {
        wx.hideLoading()
        const m = (err && err.message) || '调用失败'
        step(
          lines,
          'headbandRoomService',
          false,
          /NOT_FOUND|未部署|502001/i.test(m)
            ? '云函数未部署或未选环境\n   请右键 cloudfunctions/headbandRoomService → 上传并部署'
            : m
        )
        showDiagReport(lines)
      }
    }
  )
}

module.exports = { runHeadbandDiag }
