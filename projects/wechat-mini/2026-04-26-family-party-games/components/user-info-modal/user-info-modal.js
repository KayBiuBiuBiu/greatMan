/**
 * 聚会形象弹窗：chooseAvatar + nickname
 * 由父页面控制 visible；保存成功 triggerEvent('success')
 */
const userHelper = require('../../utils/userHelper')
const { resolveAvatarDisplayUrl } = require('../../utils/avatarResolve')

Component({
  properties: {
    /** 是否显示（仅游戏点击检查后由 index 设为 true） */
    visible: {
      type: Boolean,
      value: false
    }
  },

  data: {
    nickName: '',
    avatarDisplay: '',
    /** 已上传的云存储 fileID */
    avatarFileId: '',
    saving: false,
    uploading: false,
    errorMsg: '',
    canConfirm: false
  },

  observers: {
    visible(v) {
      if (v) {
        this._onOpen()
      } else {
        this._resetForm()
      }
    }
  },

  methods: {
    noop() {},

    _resetForm() {
      this.setData({
        nickName: '',
        avatarDisplay: '',
        avatarFileId: '',
        saving: false,
        uploading: false,
        errorMsg: '',
        canConfirm: false
      })
    },

    _onOpen() {
      this.setData({ errorMsg: '' })
      const local = userHelper.readLocalUserInfo()
      if (local) {
        const av = local.avatarUrl || ''
        const nick = local.nickName || ''
        this.setData({
          avatarFileId: av,
          nickName: nick
        })
        this._setAvatarPreview(av)
        this._syncCanConfirm()
      }
    },

    _setAvatarPreview(fileIdOrUrl) {
      const raw = String(fileIdOrUrl || '').trim()
      if (!raw) {
        this.setData({ avatarDisplay: '' })
        return
      }
      resolveAvatarDisplayUrl(raw).then((src) => {
        this.setData({ avatarDisplay: src || raw })
      })
    },

    _syncCanConfirm() {
      const ok =
        !!String(this.data.avatarFileId || '').trim() &&
        !!String(this.data.nickName || '').trim()
      this.setData({ canConfirm: ok })
    },

    /**
     * 选择头像 → 立即上传云存储 avatars/{openId}_{ts}.png
     */
    onChooseAvatar(e) {
      const temp = (e.detail && e.detail.avatarUrl) || ''
      if (!temp) {
        return
      }
      this.setData({
        avatarDisplay: temp,
        uploading: true,
        errorMsg: ''
      })
      wx.showLoading({ title: '上传头像', mask: true })
      userHelper
        .uploadChosenAvatar(temp)
        .then((fileID) => {
          wx.hideLoading()
          this.setData({
            avatarFileId: fileID,
            uploading: false
          })
          this._setAvatarPreview(fileID)
          this._syncCanConfirm()
        })
        .catch((err) => {
          wx.hideLoading()
          const msg = (err && err.message) || '头像上传失败，请重试'
          this.setData({
            uploading: false,
            avatarDisplay: '',
            avatarFileId: '',
            errorMsg: msg
          })
          wx.showToast({ title: msg, icon: 'none' })
        })
    },

    /** 昵称仅更新组件内变量，确认时再写库 */
    onNicknameInput(e) {
      const v = String((e.detail && e.detail.value) || '')
      this.setData({ nickName: v })
      this._syncCanConfirm()
    },

    onNicknameBlur(e) {
      const v = String((e.detail && e.detail.value) || '').trim()
      this.setData({ nickName: v })
      this._syncCanConfirm()
    },

    /** 稍后再说：关闭弹窗，不跳转（由父页面 cancel 处理） */
    onCancel() {
      this.triggerEvent('cancel')
    },

    /**
     * 确认：写入 users + wx.setStorageSync('userInfo')
     * 成功 → success 事件，父页面继续游戏跳转
     */
    onConfirm() {
      if (this.data.saving || this.data.uploading) {
        return
      }
      if (!this.data.avatarFileId) {
        wx.showToast({ title: '请先选择头像', icon: 'none' })
        return
      }
      if (!String(this.data.nickName || '').trim()) {
        wx.showToast({ title: '请输入昵称', icon: 'none' })
        return
      }
      this.setData({ saving: true, errorMsg: '' })
      wx.showLoading({ title: '保存中', mask: true })
      userHelper
        .saveUserInfo(this.data.avatarFileId, this.data.nickName)
        .then((profile) => {
          wx.hideLoading()
          this.setData({ saving: false })
          this.triggerEvent('success', { profile })
        })
        .catch((err) => {
          wx.hideLoading()
          const msg = (err && err.message) || '保存失败，请重试'
          this.setData({
            saving: false,
            errorMsg: msg
          })
          wx.showToast({ title: msg, icon: 'none' })
        })
    }
  }
})
