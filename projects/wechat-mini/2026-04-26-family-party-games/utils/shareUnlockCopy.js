/**
 * 分享解锁弹窗文案 A/B（按设备稳定分桶）
 */
const STORAGE_KEY = 'ai_share_copy_variant_v1'

const VARIANTS = [
  {
    id: 'A',
    main: '分享给好友，请好友点开链接解锁 AI',
    friendBtn: '分享给好友',
    timelineBtn: '分享到朋友圈'
  },
  {
    id: 'B',
    main: '叫上朋友一起玩，点开你发的链接即可解锁 AI',
    friendBtn: '叫朋友来助力',
    timelineBtn: '发到朋友圈'
  },
  {
    id: 'C',
    main: '还差一步：让好友点开分享链接，AI 功能马上可用',
    friendBtn: '微信发给好友',
    timelineBtn: '分享到朋友圈'
  }
]

function pickVariantIndex() {
  try {
    const saved = wx.getStorageSync(STORAGE_KEY)
    if (saved != null && saved !== '') {
      const i = saved | 0
      if (i >= 0 && i < VARIANTS.length) {
        return i
      }
    }
  } catch (e) {
    /* ignore */
  }
  const i = Math.floor(Math.random() * VARIANTS.length)
  try {
    wx.setStorageSync(STORAGE_KEY, i)
  } catch (e) {
    /* ignore */
  }
  return i
}

function getShareCopyVariant() {
  return VARIANTS[pickVariantIndex()]
}

module.exports = {
  VARIANTS,
  getShareCopyVariant
}
