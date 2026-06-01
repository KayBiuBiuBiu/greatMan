/**
 * AI迷雾推理局 · 6 位同房
 * 集合：mystery_reason_rooms（权威）、mystery_reason_state（公屏 watch）
 */
const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
const { createRoomTx } = require('./roomTx')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

const R = 'mystery_reason_rooms'
const S = 'mystery_reason_state'
let collectionsReady = false

function isCollectionAlreadyExistsErr(e) {
  const msg = ((e && e.message) || String(e) || '').toLowerCase()
  return (
    msg.indexOf('already exist') >= 0 ||
    msg.indexOf('resourceexist') >= 0 ||
    msg.indexOf('已存在') >= 0 ||
    msg.indexOf('重复') >= 0
  )
}

async function ensureCollections() {
  if (collectionsReady) return
  for (const name of [R, S]) {
    try {
      await db.createCollection(name)
    } catch (e) {
      if (!isCollectionAlreadyExistsErr(e)) {
        console.warn('[mysteryReason] ensureCollections', name, e.message || e)
      }
    }
  }
  collectionsReady = true
}

const PHASE = {
  WAITING: 'waiting',
  GENERATE_SCRIPT: 'generate_script',
  READ_SCRIPT: 'read_script',
  PUBLIC_DISCUSS: 'public_discuss',
  GET_EVIDENCE: 'get_evidence',
  ANALYZE_CLUE: 'analyze_clue',
  FINAL_VOTE: 'final_vote',
  WAIT_UNLOCK_REVIEW: 'wait_unlock_review',
  AI_REVIEW: 'ai_review',
  FINISHED: 'finished'
}

/** 阶段倒计时时长（毫秒） */
const PHASE_DUR_MS = {
  [PHASE.READ_SCRIPT]: 300000,
  [PHASE.PUBLIC_DISCUSS]: 1200000,
  [PHASE.GET_EVIDENCE]: 1200000,
  [PHASE.ANALYZE_CLUE]: 900000,
  [PHASE.FINAL_VOTE]: 300000
}

/** 证据派发：进入 get_evidence 后的偏移（毫秒） */
const EVIDENCE_ROUND_OFFSET_MS = [0, 420000, 840000]

const ENDING_MODES = ['npc', 'single', 'accomplice', 'all_guilty']
const DIFFICULTIES = ['新手', '进阶', '烧脑']

const t = () => Date.now()
const { runRoomTx } = createRoomTx(db, R, t)

async function getOid(event) {
  if (event && event._test === true) {
    return String(event._testOpenId || 'minium_test_host')
  }
  const oid = cloud.getWXContext().OPENID
  if (oid) return oid
  return ''
}

function c6() {
  return String(100000 + ((Math.random() * 900000) | 0))
}

function normCode(code) {
  return String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
}

function nn(list, oid) {
  const m = (list || []).find((p) => p.openId === oid)
  return m ? m.nickName : '参与者'
}

function omitIdDeep(x) {
  if (x == null) return x
  if (Array.isArray(x)) return x.map(omitIdDeep)
  if (typeof x === 'object') {
    if (x instanceof Date) return x
    if (Object.getPrototypeOf(x) !== Object.prototype) return x
    const o = {}
    for (const k of Object.keys(x)) {
      if (k === '_id' || k === '_openid') continue
      o[k] = omitIdDeep(x[k])
    }
    return o
  }
  return x
}

async function getRoom(id) {
  if (!id) return null
  const r = await db.collection(R).doc(String(id)).get()
  return r.data || null
}

async function getRoomByCode(code) {
  const c = normCode(code)
  if (c.length !== 6) return null
  const r = await db
    .collection(R)
    .where({ roomCode: c, phase: _.neq(PHASE.FINISHED) })
    .limit(1)
    .get()
  return r.data[0] || null
}

async function codeTaken(code) {
  const r = await db.collection(R).where({ roomCode: normCode(code) }).limit(1).get()
  return !!(r.data && r.data[0])
}

function alivePlayers(room) {
  return (room.playerList || []).filter((p) => String(p.openId || '').trim())
}

/** 去掉空 openId 键，避免 playerScripts. 写入失败 */
function sanitizeOpenIdMap(map) {
  const out = {}
  if (!map || typeof map !== 'object') return out
  Object.keys(map).forEach((k) => {
    const key = String(k || '').trim()
    if (!key) return
    out[key] = map[k]
  })
  return out
}

/** Minium 云测注入的虚拟玩家（openId 前缀 minium_test_） */
function roomHasTestPlayers(room) {
  return (room.playerList || []).some((p) => /^minium_test_/i.test(String(p.openId || '')))
}

function assertTestAction(event) {
  if (!event || event._test !== true) {
    throw new Error('测试接口未授权')
  }
}

function phaseRemainingMs(room) {
  const end = room.phaseEndsAt | 0
  if (!end) return 0
  return Math.max(0, end - t())
}

function phaseRemainingSec(room) {
  return Math.ceil(phaseRemainingMs(room) / 1000)
}

function setPhaseEnds(room, phase) {
  const dur = PHASE_DUR_MS[phase]
  room.phaseEndsAt = dur ? t() + dur : 0
}

function voteProgress(room) {
  const vr = room.voteRecord || {}
  const total = alivePlayers(room).length
  const voted = Object.keys(vr).filter((k) => vr[k]).length
  return { voted, total }
}

function buildPublicState(room) {
  const vp = voteProgress(room)
  return {
    roomCode: room.roomCode,
    phase: room.phase,
    difficulty: room.difficulty || '新手',
    hostOpenId: room.hostOpenId || '',
    memberList: (room.playerList || []).map((p) => {
      const entry = {
        openId: p.openId,
        nickName: p.nickName,
        avatarUrl: p.avatarUrl || '',
        profileReady: p.profileReady,
        isReady: !!p.isReady
      }
      if (gameShowsRoleNames(room)) {
        const script = resolvePlayerScript(room, p.openId)
        entry.roleName = script.roleName
        entry.displayName = script.roleName
      } else {
        entry.displayName = p.nickName
      }
      return jp.withProfileReadyFlag(entry)
    }),
    publicClue: room.publicClue || [],
    evidenceRoundRecord: room.evidenceRoundRecord || [],
    voteProgress: vp,
    reviewUnlocked: !!room.reviewUnlocked,
    phaseRemainingSeconds: phaseRemainingSec(room),
    phaseEndsAt: room.phaseEndsAt | 0,
    caseTitle: (room.gameMeta && room.gameMeta.caseTitle) || '迷雾庄园疑案',
    caseBackground: String((room.gameMeta && room.gameMeta.background) || '').slice(0, 800),
    publicDiscussHint: room.publicDiscussHint || '',
    analyzeClueHint: room.analyzeClueHint || '',
    evidenceRoundCount: (room.evidenceRoundRecord || []).length,
    updatedAt: room.updateTime || t()
  }
}

function buildTestPlayerInfo(room) {
  const info = {}
  alivePlayers(room).forEach((p) => {
    const oid = String(p.openId || '').trim()
    if (!oid) return
    const script = resolvePlayerScript(room, oid)
    info[oid] = {
      roleName: script.roleName,
      profile: script.profile,
      relationships: script.relationships,
      roleScript: script.roleScript,
      secret: script.secret,
      timeline: script.timeline
    }
  })
  return info
}

/** Minium 专用：公屏快照 + 测试剧本/投票/复盘字段（不写入线上 pub） */
function buildTestState(room) {
  const st = buildPublicState(room)
  st.playerInfo = buildTestPlayerInfo(room)
  st.voteRecord = Object.assign({}, room.voteRecord || {})
  if (room.reviewUnlocked) {
    st.reviewContent = room.reviewContent || ''
  }
  return st
}

async function setPub(room) {
  const doc = omitIdDeep(buildPublicState(room))
  await db.collection(S).doc(String(room._id)).set({ data: doc })
}

async function saveRoom(room) {
  room.updateTime = t()
  const rid = String(room._id)
  const patch = omitIdDeep(Object.assign({}, room))
  delete patch._id
  await db.collection(R).doc(rid).update({ data: patch })
  await setPub(room)
  return getRoom(rid)
}

function buildView(room, viewerOpenId) {
  const pe = (room.playerEvidence && room.playerEvidence[viewerOpenId]) || {}
  const voteTargets = []
  alivePlayers(room).forEach((p) => {
    if (p.openId !== viewerOpenId) {
      voteTargets.push({
        id: p.openId,
        name: memberRoleName(room, p.openId),
        type: 'player'
      })
    }
  })
  const npcs = (room.gameMeta && room.gameMeta.npcSuspects) || []
  npcs.forEach((n) => {
    voteTargets.push({ id: n.id, name: n.name, type: 'npc' })
  })
  return {
    roomId: String(room._id),
    roomCode: room.roomCode,
    phase: room.phase,
    isHost: room.hostOpenId === viewerOpenId,
    myOpenId: viewerOpenId,
    /** 私密证据仅通过 fetchPrivateEvidence 拉取，不在 sync 返回 */
    hasVoted: !!(room.voteRecord && room.voteRecord[viewerOpenId]),
    myVoteTarget: (room.voteRecord && room.voteRecord[viewerOpenId]) || '',
    voteTargets,
    reviewContent: room.reviewUnlocked ? room.reviewContent || '' : '',
    reviewUnlocked: !!room.reviewUnlocked,
    readyCount: (room.readyOpenIds || []).length,
    playerCount: alivePlayers(room).length,
    needReady: room.phase === PHASE.READ_SCRIPT
  }
}

function parseJson(text) {
  const raw = String(text || '').trim()
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch (e) {
    const m = raw.match(/\{[\s\S]*\}/)
    if (m) {
      try {
        return JSON.parse(m[0])
      } catch (e2) {}
    }
  }
  return null
}

/** AI 生成剧本；失败则用模板兜底 */
async function aiGenerateScript(room) {
  const n = alivePlayers(room).length
  const diff = room.difficulty || '新手'
  const ending = ENDING_MODES[(Math.random() * ENDING_MODES.length) | 0]
  const system =
    '你是线下聚会剧本杀出题助手。只返回合法 JSON，不要 markdown。内容适合全年龄亲友聚会，无暴力血腥。' +
    '禁止在剧本中使用玩家真实昵称；必须使用虚构故事角色名。禁止短句与总结式文案，全部大段叙事、细节饱满。'
  const prompt =
    '人数' +
    n +
    '，难度' +
    diff +
    '，结局模式代码' +
    ending +
    '（npc=NPC真凶,single=单人真凶,accomplice=共犯,all_guilty=全员有罪）。' +
    '请为' +
    n +
    '名玩家各生成独立剧本角色，并构建完整人物关系网：每个角色必须写清与场上每一位其他角色的过往交集、恩怨、纠葛。' +
    '返回 JSON：{"caseTitle":"…","background":"案件背景300字以上","npcSuspects":[{"id":"npc1","name":"…"}],"playerScripts":{"p0":{"roleName":"故事角色名","profile":"人物简介180字以上含性格身世","relationships":"与场上每位其他角色的详细关系各150字以上","roleScript":"身世动机+当晚行动轨迹+心理活动350字以上","secret":"隐藏秘密80字以上","timeline":"精确时间线120字以上"}}},"publicIntro":"公聊用背景"}。' +
    'playerScripts 的 key 用 p0,p1…按顺序对应玩家。roleName 必须是故事内人名，不得出现玩家昵称。'

  try {
    const res = await cloud.callFunction({
      name: 'aiPartyService',
      data: { action: 'chat', system, prompt }
    })
    const body = (res && res.result) || {}
    if (body.errMsg) throw new Error(body.errMsg)
    const data = parseJson(body.text)
    if (data && data.caseTitle) return normalizeScript(room, data, ending)
  } catch (e) {
    console.warn('[mysteryReason] AI script fallback', e.message || e)
  }
  return fallbackScript(room, ending)
}

const STORY_ROLE_NAMES = ['林晚歌', '顾沉舟', '沈清岚', '陆听雪', '程怀远', '谢微澜']

const PERSONALITY_TRAITS = [
  '外表温和、言辞谨慎，习惯在人群中保持观察者姿态',
  '性格直率、行动果决，遇到疑点会忍不住追问到底',
  '心思细腻、记性好，对细节与时间点异常敏感',
  '表面随和、实则防备心重，很少在公开场合袒露真实想法',
  '擅长社交、话术圆滑，能在紧张气氛里迅速转移话题',
  '沉默寡言、情绪内敛，但关键时会抛出令人意外的信息'
]

const BACKGROUND_SEEDS = [
  '出身没落书香门第，少年时家道中落，被迫寄居亲戚家中',
  '曾是远洋贸易公司的合伙人，因一场失败投资失去大部分积蓄',
  '长期担任家族企业的财务顾问，熟悉庄园主人的资产与债务',
  '与庄园主有未公开的婚约传闻，多年来在亲友圈引发诸多猜测',
  '十年前曾在同一座庄园担任见习管事，对建筑结构与旧日规矩了如指掌',
  '以自由撰稿人身份出入上流聚会，靠撰写人物特写换取情报与资源'
]

const RELATION_THEMES = [
  ['旧日合伙失败后的互相戒备', '表面客气实则彼此提防'],
  ['被家族强行拆散的旧识', '多年未见却仍有未了心结'],
  ['遗产分配中的直接竞争者', '口头和解但暗地较劲'],
  ['曾互相担保贷款却一方失信', '财务纠葛延续至今'],
  ['共同隐瞒过一段丑闻', '一旦翻旧账两败俱伤'],
  ['互相掌握对方不可告人的把柄', '在晚宴上维持脆弱平衡']
]

function gameShowsRoleNames(room) {
  const ph = room.phase
  return ph && ph !== PHASE.WAITING && ph !== PHASE.GENERATE_SCRIPT
}

function buildRoleNames(pl) {
  const names = []
  const used = new Set()
  pl.forEach((p, i) => {
    let name = STORY_ROLE_NAMES[i % STORY_ROLE_NAMES.length]
    let k = 0
    while (used.has(name) && k < STORY_ROLE_NAMES.length) {
      k += 1
      name = STORY_ROLE_NAMES[(i + k) % STORY_ROLE_NAMES.length]
    }
    if (used.has(name)) name = STORY_ROLE_NAMES[i % STORY_ROLE_NAMES.length] + '·' + (i + 1)
    used.add(name)
    names.push(name)
  })
  return names
}

function memberRoleName(room, openId) {
  if (!gameShowsRoleNames(room)) {
    const m = (room.playerList || []).find((p) => p.openId === openId)
    return m ? m.nickName : '参与者'
  }
  const script = resolvePlayerScript(room, openId)
  return script.roleName || '未知角色'
}

function buildRelationshipBlock(myName, otherName, i, j) {
  const pair = RELATION_THEMES[(i + j) % RELATION_THEMES.length]
  return (
    '【与' +
    otherName +
    '】\n' +
    '你与' +
    otherName +
    '之间并非萍水相逢：' +
    pair[0] +
    '。' +
    '在庄园晚宴之前，你们曾在不同场合多次照面——有时合作，有时争执，有时刻意回避。' +
    '外界看来你们' +
    pair[1] +
    '，但今晚灯光暗下来之后，那些旧账与未说出口的话都可能被重新翻起。' +
    '你记得' +
    otherName +
    '曾在关键时刻做过让你无法释怀的选择，也记得对方偶尔流露出的善意。' +
    '因此你既不能完全信任，也不能彻底否定；这种复杂关系会在公聊与投票阶段持续影响你的判断。'
  )
}

function buildFallbackProfile(roleName, index) {
  const trait = PERSONALITY_TRAITS[index % PERSONALITY_TRAITS.length]
  const bg = BACKGROUND_SEEDS[index % BACKGROUND_SEEDS.length]
  return (
    '【人物简介 · ' +
    roleName +
    '】\n' +
    '你是' +
    roleName +
    '，' +
    trait +
    '。' +
    bg +
    '。' +
    '你受邀来到迷雾庄园，并非单纯为了赴宴——你心中清楚，这场聚会背后牵扯着旧日恩怨、未了债务与可能被公开的秘密。' +
    '你习惯在开口前先评估风险，也明白今晚每一句话都可能成为他人攻击你的把柄。' +
    '你对自己的身份与过往有清晰认知，却也在抵达庄园后察觉到某些细节与记忆不符，这让你对整起事件保持高度警觉。'
  )
}

function buildFallbackRelationships(pl, roleNames, index) {
  const blocks = []
  pl.forEach((p, j) => {
    if (j === index) return
    blocks.push(buildRelationshipBlock(roleNames[index], roleNames[j], index, j))
  })
  return blocks.join('\n\n')
}

function buildFallbackRoleScript(roleName, index, openId) {
  const places = ['西侧长廊', '花厅后门', '图书室暗道', '酒窖台阶', '阳台栏杆', '侧厅屏风']
  const motives = [
    '你真正在意的并非遗产本身，而是多年前被掩盖的真相',
    '你担心某个旧日承诺被公开后会毁掉你苦心维持的形象',
    '你此行是为确认一封神秘来信的真伪，却意外卷入更大漩涡',
    '你需要在众人面前洗清嫌疑，同时保护一个不能曝光的人'
  ]
  const place = places[index % places.length]
  const motive = motives[index % motives.length]
  return (
    '【身世动机与当晚行动 · ' +
    roleName +
    '】\n' +
    motive +
    '。' +
    '晚宴开始前，你独自核对过随身物品，并在心中反复排练可能被追问的说辞。' +
    '20:' +
    (10 + index) +
    ' 前后，你随众人进入主厅，刻意选择了靠近出口却又不显眼的位置。' +
    '21:' +
    (20 + index) +
    ' 左右，你借口透气离开座位，沿' +
    place +
    '缓行，途中听见疑似争执的声响，却因光线昏暗无法确认说话者。' +
    '你当时的第一反应是回避卷入，但回程时仍注意到地面有新鲜水渍与半枚袖扣。' +
    '22:' +
    (5 + index) +
    ' 你回到大厅，发现气氛骤变，主人失踪的消息像一块巨石压下来。' +
    '你强作镇定参与讨论，心里却在计算：若有人追问你的离席时间，你该如何解释才不露出破绽。' +
    '你注意到有人在刻意引导话题，也有人在暗中观察你的反应；你决定先听再说，把每一个矛盾点都记在心里。' +
    '当警报声响起时，你甚至有一瞬间怀疑：这一切是否早在某个人的计划之中。' +
    '（剧情隔离标记 ' +
    openId +
    '_PLOT）'
  )
}

function buildFallbackSecret(roleName, index, openId) {
  return (
    '【隐藏秘密 · 仅' +
    roleName +
    '本人可见】\n' +
    '你在宴席开始前私会了' +
    ['神秘信使', '前任管家', '律师助理', '旧日合伙人', '匿名委托人'][index % 5] +
    '，并取得一件不便示人的物证。' +
    '这份物证若被公开，将直接改变他人对你的判断，甚至让你从旁观者变成众矢之的。' +
    '你原本计划在第三轮证据后再决定是否坦白，但今晚的突发状况打乱了你的节奏。' +
    '你必须在保护秘密与洗清嫌疑之间做出取舍，而任何一次口误都可能致命。' +
    '（隔离令牌 ' +
    openId +
    '_SECRET）'
  )
}

function buildFallbackTimeline(roleName, index) {
  return (
    '【精确时间线 · ' +
    roleName +
    '】\n' +
    '18:35 抵达庄园外院，由侍者引导签到\n' +
    '18:50 在衣帽间短暂停留，整理礼服与随身文件\n' +
    '19:15 进入宴会主厅，与在场众人寒暄\n' +
    '20:' +
    (8 + index) +
    ' 入席就座，留意主人迟迟未到\n' +
    '21:' +
    (18 + index) +
    ' 离席前往' +
    ['酒窖', '阳台', '侧厅', '花厅', '书库', '回廊'][index % 6] +
    '，约 12 分钟\n' +
    '21:' +
    (32 + index) +
    ' 返回大厅，发现主人缺席且众人神色异常\n' +
    '22:05 参与第一轮口头质询，刻意避开敏感话题\n' +
    '22:40 全程留在主厅直至警报响起，未再单独离场'
  )
}

function fallbackScriptForPlayer(pl, roleNames, index, openId, ending) {
  const i = index | 0
  const roleName = roleNames[i]
  return {
    roleName,
    profile: buildFallbackProfile(roleName, i),
    relationships: buildFallbackRelationships(pl, roleNames, i),
    roleScript: buildFallbackRoleScript(roleName, i, openId),
    secret: buildFallbackSecret(roleName, i, openId),
    timeline: buildFallbackTimeline(roleName, i)
  }
}

function ensureScriptObject(raw, pl, roleNames, openId, index, ending) {
  const fb = fallbackScriptForPlayer(pl, roleNames, index, openId, ending)
  if (!raw) return fb
  if (typeof raw === 'string') {
    const text = raw.trim()
    if (text.length >= 120) fb.roleScript = text
    return fb
  }
  if (typeof raw === 'object') {
    const roleName = String(raw.roleName || fb.roleName).trim() || fb.roleName
    const profile = String(raw.profile || raw.intro || fb.profile).trim() || fb.profile
    let relationships = String(raw.relationships || raw.relations || fb.relationships).trim() || fb.relationships
    if (relationships.length < 120) relationships = fb.relationships
    const roleScript = String(raw.roleScript || raw.script || fb.roleScript).trim() || fb.roleScript
    const secret = String(raw.secret || fb.secret).trim() || fb.secret
    const timeline = String(raw.timeline || fb.timeline).trim() || fb.timeline
    return { roleName, profile, relationships, roleScript, secret, timeline }
  }
  return fb
}

function resolvePlayerScript(room, openId) {
  const scripts = room.playerScripts || {}
  const raw = scripts[openId]
  const pl = alivePlayers(room)
  const roleNames = buildRoleNames(pl)
  const idx = pl.findIndex((p) => p.openId === openId)
  const ending = (room.gameMeta && room.gameMeta.endingMode) || 'single'
  return ensureScriptObject(raw, pl, roleNames, openId, idx >= 0 ? idx : 0, ending)
}

function scriptToDisplayText(script) {
  const s = script || {}
  return [
    '【角色名】\n' + (s.roleName || ''),
    '【人物简介】\n' + (s.profile || ''),
    '【人物关系】\n' + (s.relationships || ''),
    '【个人剧情】\n' + (s.roleScript || ''),
    '【隐藏秘密】\n' + (s.secret || ''),
    '【时间线】\n' + (s.timeline || '')
  ].join('\n\n')
}

function normalizeScript(room, data, ending) {
  const pl = alivePlayers(room)
  const roleNames = buildRoleNames(pl)
  const scripts = {}
  const rawScripts = data.playerScripts || {}
  const keys = Object.keys(rawScripts)
  pl.forEach((p, i) => {
    const oid = String(p.openId || '').trim()
    if (!oid) return
    const raw = rawScripts[oid] || rawScripts['p' + i] || rawScripts[keys[i]]
    scripts[oid] = ensureScriptObject(raw, pl, roleNames, oid, i, ending)
  })
  let murdererIds = []
  if (ending === 'npc') murdererIds = ['npc1']
  else if (ending === 'single') murdererIds = [pl[0] && pl[0].openId].filter(Boolean)
  else if (ending === 'accomplice') murdererIds = pl.slice(0, 2).map((p) => p.openId)
  else murdererIds = pl.map((p) => p.openId)

  const fb = fallbackScript(room, ending)
  let background = String(data.background || data.publicIntro || '').trim()
  if (background.length < 200) {
    background = fb.background
  }

  return {
    caseTitle: String(data.caseTitle || '迷雾庄园疑案').slice(0, 40),
    background: background.slice(0, 800),
    npcSuspects: Array.isArray(data.npcSuspects)
      ? data.npcSuspects.map((n, i) => ({
          id: String(n.id || 'npc' + (i + 1)),
          name: String(n.name || '可疑人' + (i + 1)).slice(0, 12)
        }))
      : [{ id: 'npc1', name: '神秘管家' }],
    playerScripts: scripts,
    endingMode: ending,
    murdererIds
  }
}

function fallbackScript(room, ending) {
  const pl = alivePlayers(room)
  const roleNames = buildRoleNames(pl)
  const scripts = {}
  pl.forEach((p, i) => {
    const oid = String(p.openId || '').trim()
    if (!oid) return
    scripts[oid] = fallbackScriptForPlayer(pl, roleNames, i, oid, ending)
  })
  let murdererIds = []
  if (ending === 'npc') murdererIds = ['npc1']
  else if (ending === 'single') murdererIds = [pl[0].openId]
  else if (ending === 'accomplice') murdererIds = pl.slice(0, 2).map((p) => p.openId)
  else murdererIds = pl.map((p) => p.openId)
  return {
    caseTitle: '迷雾庄园疑案',
    background:
      '【案件背景】\n' +
      '庄园主人于晚宴前离奇失踪，留下未完成的遗嘱与一封被撕毁的信。' +
      '受邀到场的亲友各怀心事：有人为遗产，有人为旧情，有人为洗清嫌疑。' +
      '案发当晚停电十分钟后，主厅传来异响，却无人看清全貌。' +
      '三轮证据将逐层揭开公共线索、私人秘密与真假误导，' +
      '请在线下口头辩论中拼出唯一自洽的真相链。' +
      '随着调查深入，每位参与者的时间线、动机与不在场证明都将接受交叉核验。' +
      '旧日恩怨与隐藏关系会在三轮证据中逐步浮出水面，真相比表面看起来更加扑朔迷离。',
    npcSuspects: [{ id: 'npc1', name: '神秘管家' }],
    playerScripts: scripts,
    endingMode: ending,
    murdererIds
  }
}

function clueCard(title, body, source, doubtful) {
  return {
    id: 'c' + t() + '_' + ((Math.random() * 10000) | 0),
    title: String(title || '线索').slice(0, 30),
    body: String(body || '').slice(0, 500),
    source: String(source || '公共线索').slice(0, 20),
    doubtful: !!doubtful,
    round: 0
  }
}

/** 生成单轮证据（AI 失败用模板） */
async function aiGenerateEvidence(room, round) {
  const meta = room.gameMeta || {}
  const pl = alivePlayers(room)
  const publicClue = (room.publicClue || []).slice()
  const playerEvidence = Object.assign({}, room.playerEvidence || {})

  const roundTitles = [
    ['宴会厅脚印', '破碎酒杯', '停电记录'],
    ['旧日恩怨', '不在场口供矛盾'],
    ['隐藏信件', '关键指纹', '误导性口供']
  ]
  const titles = roundTitles[round - 1] || roundTitles[0]
  titles.forEach((title, i) => {
    publicClue.push(
      clueCard(
        '第' + round + '轮·' + title,
        '这是一条公共线索，所有人可见。请结合时间线辩论（' +
          (room.difficulty || '新手') +
          '局）。',
        '公共线索',
        round >= 3 && i % 2 === 1
      )
    )
  })

  pl.forEach((p) => {
    const prev = playerEvidence[p.openId] || { list: [], starList: [], isRead: false }
    const isMurderer =
      (meta.murdererIds || []).indexOf(p.openId) >= 0 && meta.endingMode !== 'npc'
    const privateTitle =
      round === 1
        ? '轻微嫌疑记录'
        : round === 2
          ? isMurderer
            ? '洗白假象'
            : '嫌疑指向'
          : '关键矛盾点'
    prev.list = (prev.list || []).concat([
      clueCard(
        '第' + round + '轮·' + privateTitle,
        '仅你可见的私人线索。底部标注存疑线索的可能是误导。',
        '你的私人线索',
        round >= 2 && !isMurderer
      )
    ])
    playerEvidence[p.openId] = prev
  })

  return { publicClue, playerEvidence }
}

async function refreshEvidenceRound(room, round) {
  const finished = room.evidenceRoundRecord || []
  if (finished.indexOf(round) >= 0) {
    return room
  }
  const gen = await aiGenerateEvidence(room, round)
  const rid = String(room._id)
  try {
    const patched = await runRoomTx(rid, async (r) => {
      const fin = r.evidenceRoundRecord || []
      if (fin.indexOf(round) >= 0) return null
      if (r.phase !== PHASE.GET_EVIDENCE) throw new Error('当前阶段无法刷新证据')
      return {
        publicClue: gen.publicClue,
        playerEvidence: gen.playerEvidence,
        evidenceRoundRecord: fin.concat([round]),
        publicLog: (r.publicLog || []).concat(['第' + round + '轮证据已派发'])
      }
    })
    return patched || (await getRoom(rid))
  } catch (e) {
    const again = await getRoom(rid)
    if ((again.evidenceRoundRecord || []).indexOf(round) >= 0) return again
    throw e
  }
}

async function flushAllEvidence(room) {
  for (let r = 1; r <= 3; r += 1) {
    room = await refreshEvidenceRound(room, r)
  }
  return room
}

async function tickEvidence(room) {
  if (room.phase !== PHASE.GET_EVIDENCE) return room
  const start = room.evidencePhaseStartAt | 0
  if (!start) return room
  const elapsed = t() - start
  for (let i = 0; i < EVIDENCE_ROUND_OFFSET_MS.length; i += 1) {
    const round = i + 1
    if (elapsed >= EVIDENCE_ROUND_OFFSET_MS[i]) {
      room = await refreshEvidenceRound(room, round)
    }
  }
  return room
}

async function advanceToPhase(room, nextPhase) {
  room.phase = nextPhase
  room.readyOpenIds = []
  if (nextPhase === PHASE.GET_EVIDENCE) {
    room.evidencePhaseStartAt = t()
    room.evidenceRoundRecord = []
    setPhaseEnds(room, nextPhase)
  } else if (PHASE_DUR_MS[nextPhase]) {
    setPhaseEnds(room, nextPhase)
  } else {
    room.phaseEndsAt = 0
  }
  if (nextPhase === PHASE.WAIT_UNLOCK_REVIEW) {
    room.reviewUnlocked = false
    room.reviewContent = ''
  }
  room.publicLog = (room.publicLog || []).concat(['进入阶段：' + nextPhase])
  return room
}

async function runGenerateScript(room, isTest) {
  room.phase = PHASE.GENERATE_SCRIPT
  room.updateTime = t()
  await saveRoom(room)
  const ending = ENDING_MODES[(Math.random() * ENDING_MODES.length) | 0]
  const meta = isTest || roomHasTestPlayers(room)
    ? fallbackScript(room, ending)
    : await aiGenerateScript(room)
  room.gameMeta = meta
  room.playerScripts = sanitizeOpenIdMap(meta.playerScripts)
  room.gameResult = JSON.stringify({
    endingMode: meta.endingMode,
    murdererIds: meta.murdererIds
  })
  room.publicClue = []
  room.playerEvidence = {}
  room.evidenceRoundRecord = []
  room.voteRecord = {}
  room.reviewUnlocked = false
  room.reviewContent = ''
  room.publicLog = (room.publicLog || []).concat([
    'AI 已生成剧本：《' + meta.caseTitle + '》'
  ])
  return advanceToPhase(room, PHASE.READ_SCRIPT)
}

/** 公聊/辩论阶段冷场提示（不剧透） */
function maybePushDiscussHint(room) {
  const ph = room.phase
  if (ph !== PHASE.PUBLIC_DISCUSS && ph !== PHASE.ANALYZE_CLUE) return room
  const last = room.lastHintAt | 0
  if (t() - last < 180000) return room
  const hints =
    ph === PHASE.PUBLIC_DISCUSS
      ? [
          '可互相核对时间线，注意谁最早离场。',
          '留意口供矛盾，不必急于定论。',
          '先理清全员关系，再谈动机。'
        ]
      : [
          '可重点辩论标有「存疑线索」的条目真伪。',
          '尝试把三轮线索串联成完整时间线。',
          '对质时关注互相矛盾的证词。'
        ]
  const pick = hints[(Math.random() * hints.length) | 0]
  if (ph === PHASE.PUBLIC_DISCUSS) room.publicDiscussHint = pick
  else room.analyzeClueHint = pick
  room.lastHintAt = t()
  return room
}

async function tickPhase(room) {
  room = await tickEvidence(room)
  room = maybePushDiscussHint(room)
  const ph = room.phase
  if (ph === PHASE.AI_REVIEW && room.reviewUnlocked) {
    const since = (room.reviewUnlockedAt | 0) || room.updateTime | 0
    if (t() - since > 8000) {
      return advanceToPhase(room, PHASE.FINISHED)
    }
  }
  const rem = phaseRemainingMs(room)
  if (PHASE_DUR_MS[ph] && rem <= 0) {
    if (ph === PHASE.READ_SCRIPT) {
      return advanceToPhase(room, PHASE.PUBLIC_DISCUSS)
    }
    if (ph === PHASE.PUBLIC_DISCUSS) {
      return advanceToPhase(room, PHASE.GET_EVIDENCE)
    }
    if (ph === PHASE.GET_EVIDENCE) {
      room = await flushAllEvidence(room)
      return advanceToPhase(room, PHASE.ANALYZE_CLUE)
    }
    if (ph === PHASE.ANALYZE_CLUE) {
      return advanceToPhase(room, PHASE.FINAL_VOTE)
    }
    if (ph === PHASE.FINAL_VOTE) {
      return advanceToPhase(room, PHASE.WAIT_UNLOCK_REVIEW)
    }
  }
  return room
}

function voteTally(room) {
  const vr = room.voteRecord || {}
  const tally = {}
  Object.keys(vr).forEach((k) => {
    const target = vr[k]
    if (target) tally[target] = (tally[target] || 0) + 1
  })
  let top = ''
  let high = 0
  let tie = false
  Object.keys(tally).forEach((k) => {
    if (tally[k] > high) {
      high = tally[k]
      top = k
      tie = false
    } else if (tally[k] === high && high > 0) {
      tie = true
    }
  })
  return { tally, top, high, tie }
}

const ENDING_ZH = {
  npc: 'NPC真凶',
  single: '单人真凶',
  accomplice: '多名共犯',
  all_guilty: '全员凶手'
}

/** AI 复盘七大模块；失败用结构化模板兜底 */
async function aiGenerateReview(room) {
  const meta = room.gameMeta || {}
  const { top, tie } = voteTally(room)
  const topName =
    top.indexOf('npc') === 0
      ? ((meta.npcSuspects || []).find((n) => n.id === top) || {}).name || top
      : nn(room.playerList, top)

  const system =
    '你是线下聚会剧本杀复盘主持。只返回纯文本，分七大模块，不剧透下一局。适合亲友聚会。'
  const prompt =
    '案件《' +
    (meta.caseTitle || '迷雾庄园') +
    '》，结局模式' +
    (ENDING_ZH[meta.endingMode] || meta.endingMode) +
    '，真凶ID列表' +
    JSON.stringify(meta.murdererIds || []) +
    '，投票最高票对象' +
    topName +
    (tie ? '（平票）' : '') +
    '。背景：' +
    (meta.background || '').slice(0, 400) +
    '。请按顺序输出：1结局定性 2作案链条 3全员疑点拆解 4伪证据说明 5隐藏秘密解密 6推理表现点评' +
    (tie ? ' 7平票专项分析' : '')

  try {
    const res = await cloud.callFunction({
      name: 'aiPartyService',
      data: { action: 'chat', system, prompt }
    })
    const body = (res && res.result) || {}
    if (!body.errMsg && body.text && String(body.text).trim().length > 80) {
      return String(body.text).trim().slice(0, 6000)
    }
  } catch (e) {
    console.warn('[mysteryReason] AI review fallback', e.message || e)
  }

  const murdererNames = (meta.murdererIds || [])
    .map((id) =>
      id.indexOf('npc') === 0
        ? ((meta.npcSuspects || []).find((n) => n.id === id) || {}).name || id
        : nn(room.playerList, id)
    )
    .join('、')

  return [
    '【1·本局结局定性】',
    '模式：' + (ENDING_ZH[meta.endingMode] || '—') + '；核心对象：' + (murdererNames || '—'),
    '',
    '【2·作案链条还原】',
    meta.background || '请结合三轮线索回顾时间线与动机。',
    '',
    '【3·全员疑点拆解】',
    '投票焦点：' + (topName || '无人') + '。请对照各轮公共线索与私人线索辩论记录。',
    '',
    '【4·伪证据说明】',
    '标有「存疑线索」的条目可能为误导，需与物证、口供交叉验证。',
    '',
    '【5·隐藏秘密解密】',
    '各人剧本中的不便公开信息，请在线下口头复盘时自愿分享。',
    '',
    '【6·推理表现点评】',
    '感谢参与！建议下一轮尝试更高难度或更换组长开局。',
    tie ? '\n【7·平票专项分析】\n票数相同，真凶可能不在最高票对象中，请重梳第三轮关键证据。' : ''
  ]
    .filter(Boolean)
    .join('\n')
}

// ——— Actions ———

async function doCreate(event) {
  const openId = await getOid(event)
  const diff = DIFFICULTIES.indexOf(event.difficulty) >= 0 ? event.difficulty : '新手'
  const nick = String(event.nickname || event.nickName || '组长').trim().slice(0, 12) || '组长'
  const av = String(event.avatar || event.avatarUrl || '').trim().slice(0, 500)
  for (let k = 0; k < 12; k += 1) {
    const code = c6()
    if (await codeTaken(code)) continue
    const now = t()
    const doc = {
      roomCode: code,
      hostOpenId: openId,
      difficulty: diff,
      phase: PHASE.WAITING,
      playerList: [
        Object.assign(jp.mergeJoinFields(event, {}), {
          openId,
          nickName: nick,
          avatarUrl: av,
          isReady: false
        })
      ],
      voteRecord: {},
      evidenceRoundRecord: [],
      publicClue: [],
      playerEvidence: {},
      playerScripts: {},
      gameMeta: {},
      gameResult: '',
      reviewUnlocked: false,
      reviewContent: '',
      readyOpenIds: [],
      publicLog: ['聚会组已创建，等待至少 3 人开始互动'],
      createTime: now,
      updateTime: now,
      phaseEndsAt: 0,
      evidencePhaseStartAt: 0
    }
    const add = await db.collection(R).add({ data: doc })
    const rid = add._id
    const room = await getRoom(rid)
    await setPub(room)
    return {
      ok: true,
      roomId: String(rid),
      roomCode: code,
      myOpenId: openId
    }
  }
  throw new Error('创建聚会组失败，请重试')
}

async function doJoin(event) {
  const openId = await getOid(event)
  let room = event.roomId ? await getRoom(event.roomId) : await getRoomByCode(event.roomCode)
  if (!room) throw new Error('聚会组不存在或已结束')
  if (room.phase === PHASE.FINISHED) throw new Error('聚会组已结束')
  const list = room.playerList || []
  const exist = list.find((p) => p.openId === openId)
  if (!exist) {
    if (room.phase !== PHASE.WAITING) {
      throw new Error('对局已开始，无法加入')
    }
    list.push(
      Object.assign(jp.mergeJoinFields(event, {}), {
        openId,
        isReady: false
      })
    )
    room.playerList = list
    await saveRoom(room)
  } else {
    const idx = list.findIndex((p) => p.openId === openId)
    list[idx] = Object.assign(list[idx], jp.mergeJoinFields(event, list[idx]))
    room.playerList = list
    await saveRoom(room)
  }
  room = await getRoom(room._id)
  return {
    ok: true,
    roomId: String(room._id),
    roomCode: room.roomCode,
    myOpenId: openId,
    state: buildPublicState(room),
    view: buildView(room, openId)
  }
}

async function doStartGame(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.hostOpenId !== openId) throw new Error('仅组长可操作')
  if (room.phase !== PHASE.WAITING) throw new Error('当前无法开启对局')
  if ((room.playerList || []).length < 3) throw new Error('至少3人才能开始互动')
  const diff = DIFFICULTIES.indexOf(event.difficulty) >= 0 ? event.difficulty : room.difficulty
  if (diff) room.difficulty = diff
  room = await runGenerateScript(room, event._test)
  await saveRoom(room)
  return { ok: true, msg: '对局开始' }
}

async function doMarkReady(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.READ_SCRIPT) throw new Error('当前非读本阶段')
  const ready = room.readyOpenIds || []
  if (ready.indexOf(openId) < 0) ready.push(openId)
  room.readyOpenIds = ready
  const pl = room.playerList || []
  pl.forEach((p) => {
    if (p.openId === openId) p.isReady = true
  })
  room.playerList = pl
  if (ready.length >= pl.length) {
    room = await advanceToPhase(room, PHASE.PUBLIC_DISCUSS)
  }
  await saveRoom(room)
  return { ok: true }
}

async function doHostSkipPhase(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.hostOpenId !== openId) throw new Error('仅组长可操作')
  const ph = room.phase
  if (ph === PHASE.READ_SCRIPT) {
    room = await advanceToPhase(room, PHASE.PUBLIC_DISCUSS)
  } else if (ph === PHASE.PUBLIC_DISCUSS) {
    room = await advanceToPhase(room, PHASE.GET_EVIDENCE)
  } else if (ph === PHASE.GET_EVIDENCE) {
    room = await flushAllEvidence(room)
    room = await advanceToPhase(room, PHASE.ANALYZE_CLUE)
  } else if (ph === PHASE.ANALYZE_CLUE) {
    room = await advanceToPhase(room, PHASE.FINAL_VOTE)
  } else {
    throw new Error('当前阶段不可跳过')
  }
  await saveRoom(room)
  return { ok: true }
}

async function doSubmitVote(event, openId) {
  const roomId = String(event.roomId || '')
  const targetId = String(event.targetId || event.targetOpenId || '')
  if (!targetId) throw new Error('投票失败，请稍后重试')

  await runRoomTx(roomId, async (room) => {
    if (room.phase !== PHASE.FINAL_VOTE) throw new Error('当前非投票阶段')
    const prev = (room.voteRecord || {})[openId]
    if (prev === targetId) return null
    return {
      voteRecord: Object.assign({}, room.voteRecord || {}, { [openId]: targetId })
    }
  })

  const room = await getRoom(roomId)
  if (!room) throw new Error('聚会组无效')
  await setPub(room)
  return { ok: true, msg: '投票成功', data: room.voteRecord || {} }
}

async function doUnlockReview(event, openId) {
  const roomId = String(event.roomId || '')
  let room = await getRoom(roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.WAIT_UNLOCK_REVIEW && room.phase !== PHASE.AI_REVIEW) {
    throw new Error('当前不可解锁复盘')
  }
  if (room.reviewUnlocked && room.reviewContent) {
    return { ok: true, msg: '复盘已解锁', data: room.reviewContent }
  }
  if (!event.shareVerify && !event._test) throw new Error('分享验证失败，请重新分享解锁')

  const content = await aiGenerateReview(room)
  room = await runRoomTx(roomId, async (r) => {
    if (r.reviewUnlocked && r.reviewContent) return null
    return {
      reviewUnlocked: true,
      reviewContent: content,
      reviewUnlockedAt: t(),
      phase: PHASE.AI_REVIEW
    }
  })
  await setPub(room)
  return { ok: true, data: room.reviewContent || content }
}

/** 个人剧本：仅请求者本机获取，不上公屏 state */
async function doGetMyScript(event, openId) {
  const room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  const ph = room.phase
  if (
    ph === PHASE.WAITING ||
    ph === PHASE.GENERATE_SCRIPT ||
    ph === PHASE.FINISHED
  ) {
    throw new Error('当前无法获取剧本')
  }
  const script = resolvePlayerScript(room, openId)
  if (!script.roleScript) throw new Error('剧本生成中，请稍候')
  return {
    ok: true,
    openId,
    script: scriptToDisplayText(script),
    roleName: script.roleName,
    profile: script.profile,
    relationships: script.relationships,
    roleScript: script.roleScript,
    secret: script.secret,
    timeline: script.timeline
  }
}

async function doTestGetMyScript(event) {
  assertTestAction(event)
  const openId = String(event._testOpenId || event.openId || '')
  if (!openId) throw new Error('缺少 _testOpenId')
  return doGetMyScript({ roomId: event.roomId }, openId)
}

async function doStarClue(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  const clueId = String(event.clueId || '')
  if (!clueId) throw new Error('操作失败')
  const pe = room.playerEvidence || {}
  const mine = pe[openId] || { list: [], starList: [], isRead: false }
  const stars = (mine.starList || []).slice()
  const idx = stars.indexOf(clueId)
  if (idx >= 0) stars.splice(idx, 1)
  else stars.push(clueId)
  mine.starList = stars
  pe[openId] = mine
  room.playerEvidence = pe
  await saveRoom(room)
  return { ok: true, starList: stars }
}

async function doFetchPrivateEvidence(event, openId) {
  const room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  const pe = (room.playerEvidence && room.playerEvidence[openId]) || {}
  return {
    ok: true,
    list: pe.list || [],
    starList: pe.starList || []
  }
}

async function doRestartGame(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.hostOpenId !== openId) throw new Error('仅组长可操作')
  room.phase = PHASE.WAITING
  room.voteRecord = {}
  room.evidenceRoundRecord = []
  room.publicClue = []
  room.playerEvidence = {}
  room.playerScripts = {}
  room.gameMeta = {}
  room.gameResult = ''
  room.reviewUnlocked = false
  room.reviewContent = ''
  room.readyOpenIds = []
  room.phaseEndsAt = 0
  room.evidencePhaseStartAt = 0
  room.publicLog = (room.publicLog || []).concat(['对局已重置，等待开始互动'])
  const pl = (room.playerList || []).map((p) =>
    Object.assign({}, p, { isReady: false })
  )
  room.playerList = pl
  await saveRoom(room)
  return { ok: true, msg: '已重置' }
}

async function doSyncState(event, openId) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  const inRoom = (room.playerList || []).some((p) => p.openId === openId)
  if (!inRoom) {
    return { ok: false, inRoom: false, myOpenId: openId }
  }
  if (room.phase === PHASE.GENERATE_SCRIPT) {
    /* 防止卡在生成：超过 90s 强制兜底 */
    if (t() - (room.updateTime | 0) > 90000) {
      room = await runGenerateScript(room)
    }
  }
  room = await tickPhase(room)
  await saveRoom(room)
  room = await getRoom(room._id)
  return {
    ok: true,
    inRoom: true,
    myOpenId: openId,
    advanced: true,
    state: buildPublicState(room),
    view: buildView(room, openId)
  }
}

async function doRefreshEvidence(event) {
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.GET_EVIDENCE) throw new Error('当前阶段无法刷新证据')
  const round = event.round | 0
  if (round < 1 || round > 3) throw new Error('证据刷新失败，请等待下一轮')
  room = await refreshEvidenceRound(room, round)
  await saveRoom(room)
  return { ok: true }
}

const PHASE_NEXT = {
  [PHASE.WAITING]: PHASE.GENERATE_SCRIPT,
  [PHASE.GENERATE_SCRIPT]: PHASE.READ_SCRIPT,
  [PHASE.READ_SCRIPT]: PHASE.PUBLIC_DISCUSS,
  [PHASE.PUBLIC_DISCUSS]: PHASE.GET_EVIDENCE,
  [PHASE.GET_EVIDENCE]: PHASE.ANALYZE_CLUE,
  [PHASE.ANALYZE_CLUE]: PHASE.FINAL_VOTE,
  [PHASE.FINAL_VOTE]: PHASE.WAIT_UNLOCK_REVIEW,
  [PHASE.WAIT_UNLOCK_REVIEW]: PHASE.AI_REVIEW,
  [PHASE.AI_REVIEW]: PHASE.FINISHED
}

async function doTestSeedPlayers(event) {
  assertTestAction(event)
  let room = event.roomId ? await getRoom(event.roomId) : await getRoomByCode(event.roomCode)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.WAITING) throw new Error('对局已开始，无法注入测试玩家')
  const list = (room.playerList || []).slice()
  const incoming = event.players || []
  incoming.forEach((p) => {
    const oid = String(p.openId || '')
    if (!oid || list.some((x) => x.openId === oid)) return
    list.push(
      Object.assign(jp.mergeJoinFields(p, {}), {
        openId: oid,
        nickName: String(p.nickName || '测试玩家').slice(0, 12),
        avatarUrl: String(p.avatarUrl || '').slice(0, 500),
        isReady: false,
        profileReady: true
      })
    )
  })
  room.playerList = list
  await saveRoom(room)
  return { ok: true, playerCount: list.length, roomId: String(room._id), roomCode: room.roomCode }
}

async function doTestAdvanceRound(event) {
  assertTestAction(event)
  let room = event.roomId ? await getRoom(event.roomId) : await getRoomByCode(event.roomCode)
  if (!room) throw new Error('聚会组无效')
  const target = event.phase || PHASE_NEXT[room.phase]
  if (!target) throw new Error('无法推进阶段')
  if (target === PHASE.GENERATE_SCRIPT && room.phase === PHASE.WAITING) {
    room = await runGenerateScript(room, true)
  } else if (room.phase === PHASE.GET_EVIDENCE && target !== PHASE.GET_EVIDENCE) {
    room = await flushAllEvidence(room)
    room = await advanceToPhase(room, target)
  } else if (target !== room.phase) {
    room = await advanceToPhase(room, target)
    if (target === PHASE.GET_EVIDENCE) {
      await saveRoom(room)
      room = await getRoom(String(room._id))
    }
  }
  if (target === PHASE.GET_EVIDENCE && room.phase === PHASE.GET_EVIDENCE) {
    room = await flushAllEvidence(room)
  }
  if (target === PHASE.AI_REVIEW) {
    const content = await aiGenerateReview(room)
    room.reviewUnlocked = true
    room.reviewContent = content
    room.reviewUnlockedAt = t()
    room.phase = PHASE.AI_REVIEW
  }
  await saveRoom(room)
  return { ok: true, phase: room.phase, roomId: String(room._id) }
}

async function doTestStartGame(event) {
  assertTestAction(event)
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.WAITING) throw new Error('当前无法开启对局')
  if ((room.playerList || []).length < 3) throw new Error('至少3人才能开始互动')
  if (event.difficulty) room.difficulty = event.difficulty
  room = await runGenerateScript(room, true)
  await saveRoom(room)
  return { ok: true, phase: room.phase, roomId: String(room._id) }
}

async function doTestSyncSnapshot(event) {
  assertTestAction(event)
  const room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  const oid = (room.playerList && room.playerList[0] && room.playerList[0].openId) || 'minium_test_host'
  return {
    ok: true,
    state: buildTestState(room),
    view: buildView(room, oid),
    roomId: String(room._id),
    roomCode: room.roomCode
  }
}

/** Minium：将房间人数裁剪到目标值（仅 waiting 阶段） */
async function doTestKickExtraPlayers(event) {
  assertTestAction(event)
  const target = event.targetCount | 0
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.WAITING) throw new Error('仅等待阶段可调整人数')
  const pl = (room.playerList || []).slice()
  if (target < 1 || target > pl.length) throw new Error('目标人数无效')
  room.playerList = pl.slice(0, target)
  await saveRoom(room)
  return { ok: true, playerCount: target, roomId: String(room._id) }
}

/** Minium：制造平票（三票各投不同对象 → 1:1:1） */
async function doTestBatchVoteTie(event) {
  assertTestAction(event)
  const roomId = String(event.roomId || '')
  let room = await getRoom(roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.FINAL_VOTE) throw new Error('当前非投票阶段')
  const pl = alivePlayers(room)
  if (pl.length < 3) throw new Error('至少需要3名玩家才能制造平票')
  const a = pl[0].openId
  const b = pl[1].openId
  const c = pl[2].openId
  const npc = ((room.gameMeta && room.gameMeta.npcSuspects) || [])[0]
  const npcId = npc ? npc.id : c
  room.voteRecord = {}
  room.voteRecord[a] = b
  room.voteRecord[b] = c
  room.voteRecord[c] = npcId
  await saveRoom(room)
  const tally = voteTally(room)
  return { ok: true, tie: tally.tie, voteRecord: room.voteRecord }
}

async function doTestMarkAllReady(event) {
  assertTestAction(event)
  let room = await getRoom(event.roomId)
  if (!room) throw new Error('聚会组无效')
  if (room.phase !== PHASE.READ_SCRIPT) throw new Error('当前非读本阶段')
  const pl = room.playerList || []
  room.readyOpenIds = pl.map((p) => p.openId)
  pl.forEach((p) => {
    p.isReady = true
  })
  room.playerList = pl
  room = await advanceToPhase(room, PHASE.PUBLIC_DISCUSS)
  await saveRoom(room)
  return { ok: true, phase: room.phase }
}

exports.main = async (event) => {
  try {
    await ensureCollections()
    const action = event.action
    const openId = await getOid(event)
    if (action === 'create') return await doCreate(event)
    if (action === 'join') return await doJoin(event)
    if (action === 'startGame') return await doStartGame(event, openId)
    if (action === 'markReady') return await doMarkReady(event, openId)
    if (action === 'hostSkipPhase') return await doHostSkipPhase(event, openId)
    if (action === 'submitVote') return await doSubmitVote(event, openId)
    if (action === 'unlockReview') return await doUnlockReview(event, openId)
    if (action === 'restartGame') return await doRestartGame(event, openId)
    if (action === 'syncState') return await doSyncState(event, openId)
    if (action === 'refreshEvidence') return await doRefreshEvidence(event)
    if (action === 'getMyScript') return await doGetMyScript(event, openId)
    if (action === 'starClue') return await doStarClue(event, openId)
    if (action === 'fetchPrivateEvidence') return await doFetchPrivateEvidence(event, openId)
    if (action === 'ping') return { ok: true, service: 'mysteryReasonRoomService' }
    if (action === '__testSeedPlayers') return await doTestSeedPlayers(event)
    if (action === '__testAdvanceRound') return await doTestAdvanceRound(event)
    if (action === '__testMarkAllReady') return await doTestMarkAllReady(event)
    if (action === '__testStartGame') return await doTestStartGame(event)
    if (action === '__testSyncSnapshot') return await doTestSyncSnapshot(event)
    if (action === '__testKickExtraPlayers') return await doTestKickExtraPlayers(event)
    if (action === '__testBatchVoteTie') return await doTestBatchVoteTie(event)
    if (action === '__testGetMyScript') return await doTestGetMyScript(event)
    throw new Error('未知 action: ' + action)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}
