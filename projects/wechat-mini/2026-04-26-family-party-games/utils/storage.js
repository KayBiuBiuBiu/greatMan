function getJSON(key, fallback) {
  try {
    const value = wx.getStorageSync(key)
    return value || fallback
  } catch (error) {
    return fallback
  }
}

function setJSON(key, value) {
  try {
    wx.setStorageSync(key, value)
  } catch (error) {
    wx.showToast({
      title: '保存失败',
      icon: 'none'
    })
  }
}

module.exports = {
  getJSON,
  setJSON
}
