/**
 * 同场聚会组：成员人数展示、开始前校验、失败弹窗
 */

function showRoomBlockModal(title, content) {
  wx.showModal({
    title: title || '暂时无法开始',
    content: String(content || '请稍后再试'),
    showCancel: false,
    confirmText: '知道了'
  })
}

function errMsgFromCloud(err, extra) {
  if (extra && extra.result && extra.result.errMsg) {
    return String(extra.result.errMsg)
  }
  if (err && err.message) {
    return String(err.message)
  }
  return ''
}

function memberCountLine(n, need, minHint) {
  const c = (n | 0)
  if ((need | 0) > 0) {
    return '当前 ' + c + ' / ' + (need | 0) + ' 人'
  }
  if (minHint) {
    return '当前 ' + c + ' 人（' + minHint + '）'
  }
  return '当前 ' + c + ' 人'
}

function refreshCloudDoc(collection, docId) {
  return new Promise((resolve) => {
    if (!wx.cloud || !docId || !collection) {
      resolve(null)
      return
    }
    wx.cloud
      .database()
      .collection(collection)
      .doc(String(docId))
      .get()
      .then((d) => {
        resolve(d && d.data ? d.data : null)
      })
      .catch(() => {
        resolve(null)
      })
  })
}

function explainDrinkStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const m = String(msg || '')
  if (/至少\s*2/.test(m)) {
    return {
      title: '人数不足',
      content:
        `当前 ${n} 人，开始本轮至少需要 2 人。\n\n请把口令发给同桌，对方在本机「加入互动组」后，成员列表会自动更新。`
    }
  }
  if (/下一轮/.test(m)) {
    return {
      title: '请先进入下一轮',
      content: '上一局还在结果页。请先点「下一轮」回到等待状态，再点「开始本轮」。'
    }
  }
  if (/结束|等待本回合/.test(m)) {
    return {
      title: '本局进行中',
      content: '当前倒计时或投票尚未结束，请等本轮完成后再开新局。'
    }
  }
  if (/仅房主|组长/.test(m)) {
    return { title: '无权限', content: '只有组长可以开始本轮。' }
  }
  return { title: '无法开始本轮', content: m || '请稍后再试' }
}

function explainUndercoverStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const need = (ctx && ctx.needPlayers) | 0
  const m = String(msg || '')
  if (/至少\s*3/.test(m)) {
    return {
      title: '人数不足',
      content:
        `当前 ${n} 人，发牌开始至少需要 3 人。\n\n请邀请好友输入口令进组，成员数会自动刷新。`
    }
  }
  if (/人未满/.test(m) && need > 0) {
    return {
      title: '人未满',
      content:
        `本局设为 ${need} 人，当前 ${n} 人，还差 ${Math.max(0, need - n)} 人。\n\n等人到齐后再点「发牌开始」，或组长改少人数并点「保存人数」。`
    }
  }
  if (/已开局/.test(m)) {
    return { title: '已开始', content: '本局已在进行中，无需重复发牌。' }
  }
  if (/仅房主|组长|主持/.test(m)) {
    return { title: '无权限', content: '只有组长可以发牌开始。' }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

function explainWerewolfStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const need = (ctx && ctx.needPlayers) | 0
  const m = String(msg || '')
  if (/人未满/.test(m) && need > 0) {
    return {
      title: '人未满',
      content:
        `本局 ${need} 人，当前 ${n} 人，还差 ${Math.max(0, need - n)} 人。\n\n请分享口令邀请进组后再发牌。`
    }
  }
  if (/人数与板子/.test(m)) {
    return {
      title: '人数与板子不符',
      content: '请由组长先选择 6/8/10/12 人并点「应用人数」，且进组人数与设定一致后再开始。'
    }
  }
  if (/已开始|不可改/.test(m) && /lobby|等待/.test(m) === false) {
    return { title: '已开始', content: m }
  }
  if (/仅组长/.test(m)) {
    return { title: '无权限', content: '只有组长可以发牌并开始。' }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

function explainDrawStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const m = String(msg || '')
  if (/至少\s*2/.test(m)) {
    return {
      title: '人数不足',
      content:
        `当前 ${n} 人，你画我猜至少需要 2 人（1 人画、其他人猜）。\n\n请分享口令邀请进组，返回本页后人数会自动刷新。`
    }
  }
  if (/词库不足/.test(m)) {
    return {
      title: '词库不足',
      content: '当前分类下没有可用词，请组长换一类词库或选「随机（全部分类）」后保存设置再开始。'
    }
  }
  if (/已开始/.test(m)) {
    return { title: '已开始', content: '本局已在进行中。' }
  }
  if (/仅房主/.test(m)) {
    return { title: '无权限', content: '只有组长可以点击「开始」。' }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

function explainTruthDareStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const m = String(msg || '')
  if (/至少\s*2/.test(m)) {
    return {
      title: '人数不足',
      content:
        `当前 ${n} 人，真心话大冒险至少需要 2 人。\n\n请把 4 位口令发给朋友，对方在首页「输入口令」进组后，成员列表会自动更新。`
    }
  }
  if (/仅主持/.test(m)) {
    return { title: '无权限', content: '只有主持人可以开始新轮。' }
  }
  if (/不存在|过期/.test(m)) {
    return { title: '聚会组无效', content: '口令不对或聚会组已过期，请重新创建或加入。' }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

function explainMusicStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const m = String(msg || '')
  if (/曲库不足/.test(m)) {
    return {
      title: '题数过多',
      content: m + '\n\n请在等待页减少「本局题数」并点「保存题数」后再开始。'
    }
  }
  if (/至少\s*2/.test(m)) {
    return {
      title: '人数不足',
      content:
        `当前 ${n} 人，建议至少 2 人再开始（1 人主持外放、其他人抢答）。\n\n请分享口令邀请进组。`
    }
  }
  if (/已开始/.test(m)) {
    return { title: '已开始', content: '本局已在进行中。' }
  }
  if (/仅房主/.test(m)) {
    return { title: '无权限', content: '只有组长可以点击「开始互动」。' }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

function explainGenericStartFail(msg, ctx) {
  const n = (ctx && ctx.playerCount) | 0
  const need = (ctx && ctx.needPlayers) | 0
  const m = String(msg || '')
  if (/至少\s*2/.test(m) && need <= 0) {
    return {
      title: '人数不足',
      content: `当前 ${n} 人，至少需要 2 人才能开始。请邀请好友进组后重试。`
    }
  }
  if (/至少\s*3/.test(m)) {
    return {
      title: '人数不足',
      content: `当前 ${n} 人，至少需要 3 人才能开始。请邀请好友进组后重试。`
    }
  }
  if (/人未满|未满/.test(m) && need > 0) {
    return {
      title: '人未满',
      content: `需要 ${need} 人，当前 ${n} 人，还差 ${Math.max(0, need - n)} 人。`
    }
  }
  return { title: '无法开始', content: m || '请稍后再试' }
}

const EXPLAINERS = {
  drink: explainDrinkStartFail,
  undercover: explainUndercoverStartFail,
  werewolf: explainWerewolfStartFail,
  draw: explainDrawStartFail,
  music: explainMusicStartFail,
  truthDare: explainTruthDareStartFail
}

function explainStartFail(kind, msg, ctx) {
  const fn = EXPLAINERS[kind] || explainGenericStartFail
  return fn(msg, ctx)
}

function showStartFail(kind, err, extra, ctx) {
  const msg = errMsgFromCloud(err, extra)
  const box = explainStartFail(kind, msg, ctx)
  showRoomBlockModal(box.title, box.content)
}

/**
 * 本地校验 + 静默云调用；失败弹窗，成功走 onSuccess
 */
/**
 * 组装 runStartAction 的 localChecks（与文档 §3.4 一致）
 * @param {object} o
 * @param {boolean} o.isHost
 * @param {number} o.playerCount
 * @param {string} o.kind drink|undercover|werewolf|draw|music|truthDare
 * @param {number} [o.minPlayers] 最少人数（如 2、3）
 * @param {number} [o.needPlayers] 须满员人数（卧底/身份推理）
 * @param {string} [o.hostLabel] 默认「组长」；真心话用「主持人」
 * @param {string} [o.startVerb] 按钮语义，默认「开始」
 * @param {Array} [o.extra] 额外 { fail, title, content }（如趣味抽签阶段）
 */
function buildStartChecks(o) {
  const opts = o || {}
  const checks = []
  const n = opts.playerCount | 0
  const need = opts.needPlayers | 0
  const ctx = opts.ctx || { playerCount: n, needPlayers: need }
  const kind = opts.kind || ''
  const hostLabel = opts.hostLabel || '组长'
  const startVerb = opts.startVerb || '开始'

  if (opts.isHost === false) {
    checks.push({
      fail: true,
      title: '无权限',
      content: '只有' + hostLabel + '可以' + startVerb + '。'
    })
  }

  const min = opts.minPlayers | 0
  if (min > 0 && n < min) {
    const explainers = {
      drink: explainDrinkStartFail,
      undercover: explainUndercoverStartFail,
      werewolf: explainWerewolfStartFail,
      draw: explainDrawStartFail,
      music: explainMusicStartFail,
      truthDare: explainTruthDareStartFail
    }
    const fn = explainers[kind] || explainGenericStartFail
    const box = fn('至少 ' + min, ctx)
    checks.push({ fail: true, title: box.title, content: box.content })
  }

  if (need > 0 && n < need) {
    const fn =
      kind === 'werewolf' ? explainWerewolfStartFail : explainUndercoverStartFail
    const box = fn('人未满' + need, ctx)
    checks.push({ fail: true, title: box.title, content: box.content })
  }

  const extra = opts.extra || []
  for (let i = 0; i < extra.length; i++) {
    const c = extra[i]
    if (c && c.fail) {
      checks.push(c)
    }
  }
  return checks
}

function runStartAction(opts) {
  const {
    kind,
    ctx,
    localChecks,
    callService,
    payload,
    loadingTitle,
    onSuccess,
    onFinally
  } = opts || {}
  const list = localChecks || []
  for (let i = 0; i < list.length; i++) {
    const c = list[i]
    if (c && c.fail) {
      showRoomBlockModal(c.title, c.content)
      onFinally && onFinally(false)
      return
    }
  }
  if (loadingTitle) {
    wx.showLoading({ title: loadingTitle })
  }
  callService(payload, {
    silent: true,
    onOk: (res) => {
      if (loadingTitle) {
        wx.hideLoading()
      }
      const r = (res && res.result) || {}
      if (r.errMsg) {
        const box = explainStartFail(kind, r.errMsg, ctx)
        showRoomBlockModal(box.title, box.content)
        onFinally && onFinally(false)
        return
      }
      onSuccess && onSuccess(res)
      onFinally && onFinally(true)
    },
    onError: (err, extra) => {
      if (loadingTitle) {
        wx.hideLoading()
      }
      showStartFail(kind, err, extra, ctx)
      onFinally && onFinally(false)
    }
  })
}

module.exports = {
  showRoomBlockModal,
  showStartFail,
  memberCountLine,
  refreshCloudDoc,
  buildStartChecks,
  runStartAction,
  explainDrinkStartFail,
  explainUndercoverStartFail,
  explainWerewolfStartFail,
  explainDrawStartFail,
  explainMusicStartFail,
  explainTruthDareStartFail,
  explainStartFail
}
