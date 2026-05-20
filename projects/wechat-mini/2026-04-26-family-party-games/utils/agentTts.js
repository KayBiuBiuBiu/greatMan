/**
 * 主持播报：优先展示文案；后续可接腾讯云 TTS 返回 audioUrl
 */
function agentSpeak(text, opts) {
  const o = opts || {}
  const s = String(text || '').trim()
  if (!s) {
    return
  }
  if (o.vibrate !== false) {
    try {
      wx.vibrateShort({ type: 'light' })
    } catch (e) {}
  }
  const url = o.audioUrl || o.voiceUrl
  if (url) {
    try {
      const inner = wx.createInnerAudioContext()
      inner.src = url
      inner.play()
      return
    } catch (e) {}
  }
  if (o.useClientTTS) {
    wx.showToast({
      title: s.length > 24 ? s.slice(0, 24) + '…' : s,
      icon: 'none',
      duration: o.duration || 3500
    })
    return
  }
  wx.showToast({
    title: s.length > 24 ? s.slice(0, 24) + '…' : s,
    icon: 'none',
    duration: o.duration || 3500
  })
}

/** 播放 hostNarrate / tick 返回的语音字段 */
function playHostVoice(result) {
  const r = result || {}
  agentSpeak(r.speakText || r.text || '', {
    voiceUrl: r.voiceUrl,
    useClientTTS: r.useClientTTS !== false && !r.voiceUrl
  })
}

module.exports = { agentSpeak, playHostVoice }
