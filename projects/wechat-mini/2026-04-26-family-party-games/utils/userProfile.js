/**
 * 兼容层：进房参数等仍使用本模块，底层与 userHelper / userInfo 缓存对齐
 */
const userHelper = require('./userHelper')

const STORAGE_KEY = userHelper.STORAGE_KEY
const DEFAULT_NICK = '匿名'
const DEFAULT_AVATAR = ''

function readCache() {
  return userHelper.readLocalUserInfo()
}

function writeCache(profile) {
  return userHelper.writeLocalUserInfo(profile)
}

function fetchProfile(options) {
  return userHelper.getUserInfo(options).then((r) => r.profile)
}

function updateProfile(patch) {
  return userHelper.updateUserInfo(patch || {})
}

function uploadAvatarFile(tempFilePath) {
  return userHelper.uploadChosenAvatar(tempFilePath).then((fileID) => {
    return userHelper.updateUserInfo({ avatarUrl: fileID })
  })
}

function saveNickName(nickName) {
  return userHelper.updateUserInfo({ nickName: String(nickName || '').trim() })
}

function getJoinPayload() {
  return userHelper.getJoinPayload()
}

function withJoinProfile(data) {
  const j = getJoinPayload()
  const d = data || {}
  return Object.assign({}, d, {
    nickName:
      d.nickName != null && String(d.nickName).trim() !== ''
        ? d.nickName
        : j.nickName,
    avatarUrl: d.avatarUrl != null ? d.avatarUrl : j.avatarUrl
  })
}

function displayNick(profile) {
  const n = String((profile && profile.nickName) || '').trim()
  return n || DEFAULT_NICK
}

function displayAvatar(profile) {
  return (profile && profile.avatarUrl) || ''
}

module.exports = {
  STORAGE_KEY,
  DEFAULT_NICK,
  DEFAULT_AVATAR,
  readCache,
  writeCache,
  fetchProfile,
  updateProfile,
  uploadAvatarFile,
  saveNickName,
  getJoinPayload,
  withJoinProfile,
  displayNick,
  displayAvatar,
  ensureUserInfo: userHelper.ensureUserInfo
}
