/**
 * 分享卡片：邀请 / 战绩 / 解锁
 * 入参：{ action, data }
 */
const cloud = require('wx-server-sdk')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const db = cloud.database()
const BUILD_ID = 'shareCardGenerator-v1'
const SHARE_COL = 'share_cards'

const GAME_PRESETS = {
  werewolf: {
    title: '秘密身份推理',
    page: 'packageGames/werewolf/werewolf',
    codeLen: 6
  },
  undercover: {
    title: '谁是卧底',
    page: 'packageGames/undercover/undercover',
    codeLen: 6
  },
  draw: {
    title: '你画我猜',
    page: 'packageGames/draw-guess/draw-guess',
    codeLen: 6
  },
  music: {
    title: '疯狂猜歌',
    page: 'packageGames/song-guess/song-guess',
    codeLen: 6
  },
  drink: {
    title: '趣味抽签',
    page: 'packageGames/drink-party/drink-party',
    codeLen: 6
  },
  headband: {
    title: '贴头猜词',
    page: 'packageGames/headband/headband',
    codeLen: 6
  },
  dontdoit: {
    title: '不要做挑战',
    page: 'packageGames/dontdoit/dontdoit',
    codeLen: 6
  },
  play: {
    title: '真心话大冒险',
    page: 'packageGames/play/play',
    codeLen: 4
  }
}

function ok(data) {
  return { ok: true, data: data || {} }
}

function fail(msg) {
  return { ok: false, errMsg: String(msg || 'error'), data: null }
}

function normCode(code, len) {
  const n = len === 4 ? 4 : 6
  return String(code || '')
    .replace(/\D/g, '')
    .slice(0, n)
}

function escapeXml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function buildShareQuery(preset, data) {
  const code = normCode(data.roomCode, preset.codeLen)
  const rid = String(data.roomId || '')
  if (preset.page.indexOf('undercover') >= 0 || preset.page.indexOf('werewolf') >= 0) {
    const cfg = { roomCode: code }
    if (rid) {
      cfg.roomId = rid
    }
    if (preset.page.indexOf('undercover') >= 0) {
      cfg.mode = 'v2'
    }
    return 'config=' + encodeURIComponent(JSON.stringify(cfg))
  }
  if (preset.page.indexOf('headband') >= 0 || preset.page.indexOf('dontdoit') >= 0) {
    const cfg = { roomId: rid, roomCode: code }
    return 'config=' + encodeURIComponent(JSON.stringify(cfg))
  }
  if (preset.page.indexOf('play') >= 0) {
    return 'roomCode=' + encodeURIComponent(code)
  }
  let q = 'roomCode=' + encodeURIComponent(code)
  if (rid) {
    q += '&roomId=' + encodeURIComponent(rid)
  }
  return q
}

function buildSharePath(gameKind, data) {
  const preset = GAME_PRESETS[gameKind] || GAME_PRESETS.undercover
  const query = buildShareQuery(preset, data)
  return preset.page + (query ? '?' + query : '')
}

function buildInviteSvg(opts) {
  const title = escapeXml(opts.title || '家庭聚会助手')
  const subtitle = escapeXml(opts.subtitle || '口令进组，马上开玩')
  const code = escapeXml(opts.code || '')
  const player = escapeXml(opts.playerName || '')
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="400" viewBox="0 0 500 400">' +
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
    '<stop offset="0%" stop-color="#fff4e8"/><stop offset="100%" stop-color="#ffe0c2"/>' +
    '</linearGradient></defs>' +
    '<rect width="500" height="400" fill="url(#g)"/>' +
    '<text x="250" y="72" text-anchor="middle" font-size="28" font-weight="bold" fill="#8a3a0a">' +
    title +
    '</text>' +
    '<text x="250" y="118" text-anchor="middle" font-size="20" fill="#166534">' +
    subtitle +
    '</text>' +
    (player
      ? '<text x="250" y="148" text-anchor="middle" font-size="18" fill="#6b5a4a">来自 ' +
        player +
        ' 的邀请</text>'
      : '') +
    (code
      ? '<rect x="90" y="170" width="320" height="88" rx="12" fill="#fff" stroke="#07c160" stroke-width="4"/>' +
        '<text x="250" y="228" text-anchor="middle" font-size="40" font-weight="bold" fill="#111">' +
        code +
        '</text>' +
        '<text x="250" y="280" text-anchor="middle" font-size="18" fill="#6b5a4a">输入口令进组</text>'
      : '') +
    '<text x="250" y="372" text-anchor="middle" font-size="16" fill="#9ca3af">家庭聚会助手</text>' +
    '</svg>'
  )
}

function buildAchievementSvg(opts) {
  const title = escapeXml(opts.title || '本局战绩')
  const detail = escapeXml(opts.detail || '')
  const player = escapeXml(opts.playerName || '')
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="400" viewBox="0 0 500 400">' +
    '<rect width="500" height="400" fill="#1e3a5f"/>' +
    '<text x="250" y="80" text-anchor="middle" font-size="32" font-weight="bold" fill="#fbbf24">🏆 ' +
    title +
    '</text>' +
    '<text x="250" y="140" text-anchor="middle" font-size="22" fill="#e2e8f0">' +
    player +
    '</text>' +
    '<text x="250" y="220" text-anchor="middle" font-size="20" fill="#cbd5e1">' +
    detail +
    '</text>' +
    '<text x="250" y="360" text-anchor="middle" font-size="16" fill="#94a3b8">家庭聚会助手</text>' +
    '</svg>'
  )
}

function buildUnlockSvg(opts) {
  const title = escapeXml(opts.title || 'AI 功能已解锁')
  const hint = escapeXml(opts.hint || '分享好友即可继续畅玩')
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="400" viewBox="0 0 500 400">' +
    '<rect width="500" height="400" fill="#ecfdf5"/>' +
    '<text x="250" y="120" text-anchor="middle" font-size="30" font-weight="bold" fill="#047857">✨ ' +
    title +
    '</text>' +
    '<text x="250" y="200" text-anchor="middle" font-size="20" fill="#065f46">' +
    hint +
    '</text>' +
    '</svg>'
  )
}

async function tryWxacode(pagePath, scene) {
  try {
    const res = await cloud.openapi.wxacode.getUnlimited({
      scene: String(scene || 'join').slice(0, 32),
      page: pagePath.split('?')[0],
      checkPath: false,
      envVersion: 'release'
    })
    const buf = res && (res.buffer || res.data)
    if (!buf) {
      return ''
    }
    const cloudPath =
      'share-cards/' + Date.now() + '_' + Math.random().toString(36).slice(2, 8) + '.png'
    const up = await cloud.uploadFile({
      cloudPath: cloudPath,
      fileContent: buf
    })
    if (!up.fileID) {
      return ''
    }
    const urlRes = await cloud.getTempFileURL({ fileList: [up.fileID] })
    const item = urlRes.fileList && urlRes.fileList[0]
    return (item && item.tempFileURL) || ''
  } catch (e) {
    console.warn('[shareCardGenerator] wxacode', e.message || e)
    return ''
  }
}

async function saveCardRecord(type, payload, shareUrl) {
  try {
    await db.collection(SHARE_COL).add({
      data: {
        type: type,
        roomId: String(payload.roomId || ''),
        gameKind: String(payload.gameKind || ''),
        shareUrl: shareUrl,
        createdAt: Date.now()
      }
    })
  } catch (e) {
    console.warn('[shareCardGenerator] save record', e.message || e)
  }
}

async function generateInviteCard(data) {
  const gameKind = data.gameKind || 'undercover'
  const preset = GAME_PRESETS[gameKind] || GAME_PRESETS.undercover
  const code = normCode(data.roomCode, preset.codeLen)
  const shareUrl = buildSharePath(gameKind, data)
  const svg = buildInviteSvg({
    title: data.title || preset.title,
    subtitle: data.subtitle || '口令进组，马上开玩',
    code: code,
    playerName: data.playerName || ''
  })
  const scene = code || String(data.roomId || '').slice(0, 32)
  const qrCode = (await tryWxacode(shareUrl.split('?')[0], scene)) || shareUrl
  await saveCardRecord('invite', data, shareUrl)
  return ok({ svg: svg, qrCode: qrCode, shareUrl: shareUrl, roomCode: code })
}

async function generateAchievementCard(data) {
  const gameKind = data.gameKind || 'undercover'
  const preset = GAME_PRESETS[gameKind] || GAME_PRESETS.undercover
  const shareUrl = buildSharePath(gameKind, data)
  const svg = buildAchievementSvg({
    title: data.title || '本局战绩',
    detail: data.detail || data.achievement || '',
    playerName: data.playerName || ''
  })
  const qrCode = shareUrl
  await saveCardRecord('achievement', data, shareUrl)
  return ok({ svg: svg, qrCode: qrCode, shareUrl: shareUrl })
}

async function generateUnlockCard(data) {
  const svg = buildUnlockSvg({
    title: data.title || 'AI 功能已解锁',
    hint: data.hint || data.detail || ''
  })
  return ok({
    svg: svg,
    qrCode: '',
    shareUrl: '/pages/index/index'
  })
}

async function generateGenericCard(data) {
  const kind = data.cardKind || data.type || 'invite'
  if (kind === 'achievement') {
    return generateAchievementCard(data)
  }
  if (kind === 'unlock') {
    return generateUnlockCard(data)
  }
  return generateInviteCard(data)
}

exports.main = async (event) => {
  try {
    const action = String((event && event.action) || '').trim()
    const data =
      event && event.data && typeof event.data === 'object' ? event.data : event || {}
    if (action === 'ping') {
      return ok({ buildId: BUILD_ID })
    }
    if (action === 'generateInviteCard') {
      return await generateInviteCard(data)
    }
    if (action === 'generateAchievementCard') {
      return await generateAchievementCard(data)
    }
    if (action === 'generateUnlockCard') {
      return await generateUnlockCard(data)
    }
    if (action === 'generateGenericCard') {
      return await generateGenericCard(data)
    }
    return fail('未知 action: ' + (action || '(空)'))
  } catch (e) {
    console.error('[shareCardGenerator]', e)
    return fail((e && e.message) || String(e))
  }
}
