/**
 * 主持语音：优先云开发 TTS（若环境支持），否则由小程序端朗读
 */
const cloud = require('wx-server-sdk')

async function textToVoice(text, options) {
  const o = options || {}
  const content = String(text || '').trim()
  if (!content) {
    return { voiceUrl: null, text: '', useClientTTS: true }
  }

  try {
    if (cloud.extend && cloud.extend.AI && cloud.extend.AI.createModel) {
      const model = cloud.extend.AI.createModel('cloudbase')
      if (model && typeof model.speech === 'function') {
        const res = await model.speech({
          text: content,
          speed: o.speed != null ? o.speed : 4,
          voiceType: o.voiceType != null ? o.voiceType : 0
        })
        const body = (res && res.data) || res || {}
        const voiceUrl = body.audioUrl || body.url || body.voiceUrl || null
        if (voiceUrl) {
          return {
            voiceUrl: String(voiceUrl),
            duration: body.duration || null,
            text: content,
            useClientTTS: false
          }
        }
      }
    }
  } catch (e) {
    console.warn('[hostAgent TTS]', e.message || e)
  }

  return {
    voiceUrl: null,
    text: content,
    useClientTTS: true
  }
}

module.exports = { textToVoice }
