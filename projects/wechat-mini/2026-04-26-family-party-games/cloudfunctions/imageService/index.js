/**
 * 聚会战报海报生图（混元生图，返回 success / imageUrl / revised_prompt）
 */
const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const IMAGE_MODEL = 'hunyuan-image'
const PROVIDER = 'cloudbase'

async function generatePoster(event) {
  const prompt = String((event && event.prompt) || '').trim()
  if (!prompt) {
    return {
      success: false,
      code: 'MISSING_PROMPT',
      message: '缺少 prompt'
    }
  }
  if (!cloud.extend || !cloud.extend.AI || !cloud.extend.AI.createModel) {
    return {
      success: false,
      code: 'NO_AI',
      message: '云函数环境未支持 extend.AI，请升级 wx-server-sdk 3.x 并重新部署'
    }
  }
  const model = cloud.extend.AI.createModel(PROVIDER)
  if (!model || typeof model.generateImage !== 'function') {
    return {
      success: false,
      code: 'NO_IMAGE_API',
      message: '当前环境不支持 generateImage，请在云开发控制台开通混元生图'
    }
  }
  const fullPrompt =
    '家庭聚会游戏战报海报，温馨喜庆插画风格，无文字水印，无饮酒元素：' + prompt.slice(0, 200)
  const res = await model.generateImage({
    model: IMAGE_MODEL,
    prompt: fullPrompt
  })
  const imageUrl =
    (res && res.data && res.data[0] && res.data[0].url) ||
    (res && res.images && res.images[0] && res.images[0].url) ||
    (res && res.url) ||
    (res && res.imageUrl) ||
    ''
  if (!imageUrl) {
    return {
      success: false,
      code: 'NO_URL',
      message: '生图未返回图片地址'
    }
  }
  const revised =
    (res && res.revised_prompt) ||
    (res && res.data && res.data[0] && res.data[0].revised_prompt) ||
    ''
  return {
    success: true,
    imageUrl: String(imageUrl),
    url: String(imageUrl),
    revised_prompt: String(revised || ''),
    note: '图片 URL 有效期约 24 小时，请及时预览或保存'
  }
}

exports.main = async function (event) {
  const action = (event && event.action) || 'poster'
  try {
    if (action === 'poster' || !action) {
      return await generatePoster(event)
    }
    return {
      success: false,
      code: 'UNKNOWN_ACTION',
      message: '未知 action ' + action
    }
  } catch (e) {
    return {
      success: false,
      code: 'ERROR',
      message: (e && e.message) || String(e)
    }
  }
}
