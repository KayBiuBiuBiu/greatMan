/**
 * 用户头像昵称：点击游戏入口时检查/补全资料（非启动自动拉取）
 * 官方能力：chooseAvatar + input type="nickname"
 */
const { ensureCloudInit } = require('./cloudInit')

/** 与需求一致的本地缓存键 */
const STORAGE_KEY = 'userInfo'
/** 兼容旧版缓存键 */
const LEGACY_STORAGE_KEY = 'user_profile_cache'

function ensureCloud() {
  return ensureCloudInit() && !!wx.cloud
}

/** 资料是否完整：头像 fileID 与昵称均非空 */
function isProfileComplete(profile) {
  const p = profile || {}
  return !!(
    String(p.avatarUrl || '').trim() && String(p.nickName || '').trim()
  )
}

function readLocalUserInfo() {
  try {
    const u = wx.getStorageSync(STORAGE_KEY)
    if (u && (u.avatarUrl || u.nickName)) {
      return u
    }
    return wx.getStorageSync(LEGACY_STORAGE_KEY) || null
  } catch (e) {
    return null
  }
}

function writeLocalUserInfo(profile) {
  const p = profile || {}
  const row = {
    openId: p.openId || '',
    avatarUrl: p.avatarUrl || '',
    nickName: p.nickName || '',
    updatedAt: p.updatedAt | 0
  }
  try {
    wx.setStorageSync(STORAGE_KEY, row)
    wx.setStorageSync(LEGACY_STORAGE_KEY, row)
  } catch (e) {
    /* ignore */
  }
  return row
}

function callUserService(payload) {
  if (!ensureCloud()) {
    return Promise.reject(new Error('请先开通云开发'))
  }
  return new Promise((resolve, reject) => {
    wx.cloud.callFunction({
      name: 'userService',
      data: payload || {},
      success(res) {
        const r = (res && res.result) || {}
        if (r.errMsg) {
          reject(new Error(String(r.errMsg)))
          return
        }
        resolve(r)
      },
      fail(err) {
        let msg =
          (err && err.errMsg) ||
          (err && err.message) ||
          '网络异常，请检查网络后重试'
        if (msg.indexOf('users') >= 0 && msg.indexOf('集合') >= 0) {
          msg =
            '请先在云开发控制台创建集合 users，并重新部署 userService（见 docs/USERS_DB.md）'
        }
        reject(new Error(msg))
      }
    })
  })
}

/**
 * 从云端拉取用户信息，并返回是否已完整填写
 */
function getUserInfo(options) {
  const opts = options || {}
  const silent = !!opts.silent
  if (!silent) {
    wx.showLoading({ title: '加载中', mask: true })
  }
  return callUserService({ action: 'getUserInfo' })
    .then((r) => {
      const profile = r.userInfo || r.profile || {}
      writeLocalUserInfo(profile)
      const isComplete =
        r.isComplete != null ? !!r.isComplete : isProfileComplete(profile)
      return { profile, isComplete }
    })
    .catch((err) => {
      const cached = readLocalUserInfo()
      if (cached && isProfileComplete(cached)) {
        return { profile: cached, isComplete: true }
      }
      throw err
    })
    .finally(() => {
      if (!silent) {
        wx.hideLoading()
      }
    })
}

/**
 * 保存头像 URL 与昵称到 users 集合
 */
function updateUserInfo(patch) {
  return callUserService({
    action: 'updateUserInfo',
    nickName: patch.nickName,
    avatarUrl: patch.avatarUrl
  }).then((r) => {
    const profile = r.userInfo || r.profile || {}
    writeLocalUserInfo(profile)
    return profile
  })
}

/**
 * 上传临时头像到云存储：avatars/{openId}_{timestamp}.png
 */
function uploadAvatarTemp(tempFilePath, openId) {
  if (!ensureCloud()) {
    return Promise.reject(new Error('请先开通云开发'))
  }
  if (!tempFilePath) {
    return Promise.reject(new Error('未选择头像'))
  }
  const oid = String(openId || 'user').trim() || 'user'
  const cloudPath = 'avatars/' + oid + '_' + Date.now() + '.png'
  return new Promise((resolve, reject) => {
    wx.cloud.uploadFile({
      cloudPath,
      filePath: tempFilePath,
      success(up) {
        const fileID = (up && up.fileID) || ''
        if (!fileID) {
          reject(new Error('头像上传失败，请重试'))
          return
        }
        resolve(fileID)
      },
      fail(err) {
        reject(
          new Error(
            (err && err.errMsg) || '头像上传失败，请重试'
          )
        )
      }
    })
  })
}

/**
 * 选择头像后：先取 openId，再上传，返回 fileID（不自动写库，确认时一并保存）
 */
function uploadChosenAvatar(tempFilePath) {
  return getUserInfo({ silent: true }).then((res) => {
    const openId = (res.profile && res.profile.openId) || 'user'
    return uploadAvatarTemp(tempFilePath, openId)
  })
}

/**
 * 确认保存：头像 fileID + 昵称
 */
function saveUserInfo(avatarUrl, nickName) {
  const nick = String(nickName || '').trim()
  const av = String(avatarUrl || '').trim()
  if (!av) {
    return Promise.reject(new Error('请先选择头像'))
  }
  if (!nick) {
    return Promise.reject(new Error('请输入昵称'))
  }
  return updateUserInfo({ avatarUrl: av, nickName: nick })
}

/**
 * 进房参数（供 withJoinProfile 等复用）
 */
function getJoinPayload() {
  const c = readLocalUserInfo() || {}
  const nick = String(c.nickName || '').trim()
  return {
    nickName: nick ? nick.slice(0, 12) : '匿名',
    avatarUrl: c.avatarUrl || ''
  }
}

/**
 * 检查用户资料；不完整则打开页面上的 user-info-modal，完整则直接执行 callback
 * @param {Object} context 页面实例（需有 data.showUserInfoModal）
 * @param {Function} callback 资料齐全或保存成功后的回调（如跳转）
 */
function ensureUserInfo(context, callback) {
  if (!context || typeof context.setData !== 'function') {
    if (typeof callback === 'function') {
      callback()
    }
    return
  }
  if (!ensureCloud()) {
    wx.showToast({ title: '请先开通云开发', icon: 'none' })
    return
  }

  const local = readLocalUserInfo()
  if (local && isProfileComplete(local)) {
    if (typeof callback === 'function') {
      callback()
    }
    return
  }

  context.setData({ userInfoChecking: true })
  getUserInfo({ silent: true })
    .then((res) => {
      context.setData({ userInfoChecking: false })
      if (res.isComplete) {
        if (typeof callback === 'function') {
          callback()
        }
        return
      }
      // 仅游戏点击等入口调用 ensureUserInfo 时才会打开弹窗
      context._pendingUserInfoCallback = callback
      context.setData({ showUserInfoModal: true })
    })
    .catch((err) => {
      context.setData({ userInfoChecking: false })
      wx.showToast({
        title: (err && err.message) || '网络异常，请稍后重试',
        icon: 'none'
      })
    })
}

/** 弹窗保存成功后由页面调用 */
function completePendingAction(context) {
  if (!context) {
    return
  }
  const cb = context._pendingUserInfoCallback
  context._pendingUserInfoCallback = null
  context.setData({ showUserInfoModal: false })
  if (typeof cb === 'function') {
    cb()
  }
}

function cancelPendingAction(context) {
  if (!context) {
    return
  }
  context._pendingUserInfoCallback = null
  context.setData({ showUserInfoModal: false })
}

module.exports = {
  STORAGE_KEY,
  isProfileComplete,
  readLocalUserInfo,
  writeLocalUserInfo,
  getUserInfo,
  updateUserInfo,
  uploadAvatarTemp,
  uploadChosenAvatar,
  saveUserInfo,
  getJoinPayload,
  ensureUserInfo,
  completePendingAction,
  cancelPendingAction
}
