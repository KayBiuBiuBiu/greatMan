/** 各游戏副主持播报模板 */
const HOST_TEMPLATES = {
  undercover: {
    system:
      '你是谁是卧底副主持。用悬疑紧张的语气，简短播报当前局面（30字内）。可以暗示但不要透露卧底身份。',
    styles: {
      opening: '游戏开始，各位观察词卡，卧底请隐藏身份！',
      midgame: '投票时刻，谁的眼神在闪躲？',
      final: '只剩两人，卧底能否逆袭？',
      vote: '{player}被指认，是平民还是卧底？'
    }
  },
  werewolf: {
    system: '你是狼人杀副主持。用神秘低沉的语气控场（30字内）。',
    styles: {
      night: '天黑请闭眼，狼人请睁眼...',
      day: '天亮了，昨晚{deadPlayer}倒牌。',
      vote: '{player}被票出，遗言请发言。',
      hunter: '{player}触发技能，请带走一人。',
      midgame: '各位请冷静分析，投票即将开始。'
    }
  },
  drawguess: {
    system: '你是你画我猜副主持。用活泼轻松的语气鼓励玩家（30字内）。',
    styles: {
      start: '画家请动笔，猜题者准备好！',
      hint: '提示：这个词和{category}有关哦~',
      correct: '{player}猜对了！加{score}分！',
      overtime: '时间到，答案是：{answer}',
      midgame: '画笔动起来，脑洞开起来！'
    }
  },
  draw: {
    system: '你是你画我猜副主持。用活泼轻松的语气鼓励玩家（30字内）。',
    styles: {
      start: '画家请动笔，猜题者准备好！',
      midgame: '画笔动起来，脑洞开起来！'
    }
  },
  truthdare: {
    system: '你是真心话大冒险副主持。用调侃有趣的语气烘托气氛（30字内）。',
    styles: {
      spin: '转盘启动，命运指针指向...',
      selected: '{player}被选中！选真心话还是大冒险？',
      completed: '{player}完成了挑战，全场鼓掌！',
      dareUp: '挑战加码！敢不敢接受？',
      midgame: '气氛升温，下一位准备好了吗？'
    }
  },
  story: {
    system: '你是故事接龙副主持。用富有画面感的语气引导剧情（30字内）。',
    styles: {
      start: '故事开篇：{opening}',
      continue: '{player}接龙，情节走向{direction}...',
      twist: '剧情反转！{twist}',
      end: '故事落幕，{ending}',
      midgame: '轮到下一位，请接下去。'
    }
  },
  drink: {
    system: '你是趣味抽签聚会副主持。语气轻松幽默（30字内）。',
    styles: {
      opening: '新一轮开始，响铃者请藏好！',
      countdown: '倒计时滴答，谁在紧张？',
      voting: '投票进行中，指认响铃者！',
      result: '结果揭晓，看看谁猜对了！',
      midgame: '局面胶着，注意听铃声。'
    }
  }
}

function normalizeGameKind(gameKind) {
  const k = String(gameKind || '')
    .toLowerCase()
    .replace(/-/g, '')
  if (k === 'drawguess' || k === 'draw') return 'drawguess'
  if (k === 'drinkparty') return 'drink'
  return k || 'undercover'
}

function fillPreset(preset, customVars) {
  let s = String(preset || '')
  const vars = customVars && typeof customVars === 'object' ? customVars : {}
  Object.keys(vars).forEach((key) => {
    s = s.split('{' + key + '}').join(String(vars[key] == null ? '' : vars[key]))
  })
  return s
}

function getTemplate(gameKind, scene) {
  const key = normalizeGameKind(gameKind)
  const game = HOST_TEMPLATES[key] || HOST_TEMPLATES.undercover
  const sceneKey = String(scene || 'midgame')
  return {
    system: game.system,
    preset: game.styles[sceneKey] || game.styles.midgame || ''
  }
}

module.exports = { getTemplate, fillPreset, HOST_TEMPLATES, normalizeGameKind }
