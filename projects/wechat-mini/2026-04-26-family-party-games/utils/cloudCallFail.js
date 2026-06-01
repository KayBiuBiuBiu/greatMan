/**
 * wx.cloud.callFunction fail 友好文案（避免新用户看到 cloud.callFunction:fail Error: errCode…）
 */

function extractErrCode(err, msg) {
  if (err && err.errCode != null && err.errCode !== '') {
    return err.errCode
  }
  const m = String(msg || '')
  const hit = m.match(/errCode:\s*(-?\d+)/i)
  return hit ? parseInt(hit[1], 10) : null
}

/**
 * @returns {{ short: string, long: string, isInfra: boolean }}
 */
function formatCloudCallFail(err) {
  const msg = String(
    (err && err.errMsg) || (err && err.message) || err || ''
  ).trim()
  const code = extractErrCode(err, msg)
  const lower = msg.toLowerCase()

  if (
    code === -501000 ||
    /function_not_found|502001|未部署|not found|未上传|没有权限调用/i.test(msg)
  ) {
    return {
      short: '云服务未就绪，请稍后再试',
      long:
        '云函数可能未部署或未选对环境。\n\n开发者：在云开发控制台确认环境 cloud-env.js 的 envId，并上传部署 userService / shareService 等云函数。',
      isInfra: true
    }
  }
  if (
    code === -404011 ||
    code === -501001 ||
    /invalid env|环境|environment|cloud\.init/i.test(lower)
  ) {
    return {
      short: '云环境配置有误',
      long: '请确认小程序与 cloud-env.js 使用同一云开发环境（标准版 envId）。',
      isInfra: true
    }
  }
  if (/timeout|超时|timed out|504|deadline/i.test(lower)) {
    return {
      short: '网络超时，请稍后重试',
      long: '云请求超时，可检查网络或稍后再试。',
      isInfra: true
    }
  }
  if (/cloud\.callFunction:fail/i.test(msg)) {
    return {
      short: '网络或服务暂不可用',
      long: '云调用失败，请检查网络连接；若持续出现请联系管理员检查云开发部署。',
      isInfra: true
    }
  }
  if (msg.indexOf('users') >= 0 && msg.indexOf('集合') >= 0) {
    return {
      short: '用户服务初始化中',
      long: '请在云开发控制台创建 users 集合并部署 userService（见 docs/USERS_DB.md）。',
      isInfra: true
    }
  }
  const short = msg.length > 28 ? msg.slice(0, 28) + '…' : msg || '请求失败'
  return { short, long: msg || '请求失败', isInfra: false }
}

function isCloudInfrastructureError(err) {
  return formatCloudCallFail(err).isInfra
}

function toCloudError(err) {
  const f = formatCloudCallFail(err)
  const e = new Error(f.short)
  e.isInfra = f.isInfra
  e.detail = f.long
  e.raw = err
  return e
}

module.exports = {
  formatCloudCallFail,
  isCloudInfrastructureError,
  toCloudError
}
