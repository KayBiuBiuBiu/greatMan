const userProfile = require('../../utils/userProfile')

const DEFAULT_AVATAR_PLACEHOLDER = ''

Component({
  properties: {
    /** compact：仅头像+昵称一行；card：带说明的卡片 */
    mode: {
      type: String,
      value: 'card'
    },
    title: {
      type: String,
      value: '我的聚会形象'
    },
    hint: {
      type: String,
      value: '点击头像更换；昵称将用于同场成员列表'
    }
  },

  data: {
    loading: true,
    saving: false,
    errorMsg: '',
    nickName: '',
    avatarUrl: '',
    avatarDisplay: DEFAULT_AVATAR_PLACEHOLDER,
    hasAvatar: false
  },

  lifetimes: {
    attached() {
      this.reload()
    }
  },

  methods: {
    reload() {
      this.setData({ loading: true, errorMsg: '' })
      return userProfile
        .fetchProfile({ silent: true })
        .then((p) => {
          this._applyProfile(p)
          this.setData({ loading: false })
          this.triggerEvent('loaded', { profile: p })
        })
        .catch((err) => {
          const cached = userProfile.readCache()
          if (cached) {
            this._applyProfile(cached)
            this.setData({
              loading: false,
              errorMsg: ''
            })
            return
          }
          this.setData({
            loading: false,
            errorMsg: (err && err.message) || '加载失败，请下拉重试'
          })
        })
    },

    _applyProfile(p) {
      const profile = p || {}
      const avatarUrl = profile.avatarUrl || ''
      this.setData({
        nickName: profile.nickName || '',
        avatarUrl,
        avatarDisplay: avatarUrl || DEFAULT_AVATAR_PLACEHOLDER,
        hasAvatar: !!avatarUrl,
        errorMsg: ''
      })
    },

    onChooseAvatar(e) {
      const detail = (e && e.detail) || {}
      const temp = detail.avatarUrl || ''
      if (!temp) {
        return
      }
      this.setData({ saving: true, errorMsg: '' })
      userProfile
        .uploadAvatarFile(temp)
        .then((profile) => {
          this._applyProfile(profile)
          wx.showToast({ title: '头像已更新', icon: 'none' })
          this.triggerEvent('change', { profile })
        })
        .catch((err) => {
          this.setData({
            errorMsg: (err && err.message) || '头像上传失败'
          })
          wx.showToast({
            title: (err && err.message) || '上传失败',
            icon: 'none'
          })
        })
        .finally(() => {
          this.setData({ saving: false })
        })
    },

    onNicknameBlur(e) {
      const v = String((e.detail && e.detail.value) || '').trim()
      const prev = String(this.data.nickName || '').trim()
      if (v === prev) {
        return
      }
      this._saveNick(v)
    },

    onNicknameConfirm(e) {
      const v = String((e.detail && e.detail.value) || '').trim()
      this._saveNick(v)
    },

    _saveNick(nick) {
      this.setData({ saving: true, errorMsg: '' })
      userProfile
        .saveNickName(nick)
        .then((profile) => {
          this._applyProfile(profile)
          wx.showToast({ title: '昵称已保存', icon: 'none' })
          this.triggerEvent('change', { profile })
        })
        .catch((err) => {
          this.setData({
            errorMsg: (err && err.message) || '保存失败'
          })
          wx.showToast({
            title: (err && err.message) || '保存失败',
            icon: 'none'
          })
        })
        .finally(() => {
          this.setData({ saving: false })
        })
    },

    onRetry() {
      this.reload()
    }
  }
})
