const cloud = require('wx-server-sdk')
const jp = require('./joinPlayerPatch')
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const _ = db.command

/**
 * 云库 doc().set({ data }) 中禁止 _id / _openid（含嵌套）；公屏从 game 等对象拼出来时可能误带入。
 */
function omitIdDeep (x) {
  if (x == null) {
    return x
  }
  if (Array.isArray(x)) {
    return x.map(omitIdDeep)
  }
  if (typeof x === 'object') {
    if (x instanceof Date) {
      return x
    }
    if (Object.getPrototypeOf(x) !== Object.prototype) {
      return x
    }
    const o = {}
    for (const k of Object.keys(x)) {
      if (k === '_id' || k === '_openid') {
        continue
      }
      o[k] = omitIdDeep(x[k])
    }
    return o
  }
  return x
}
const R = 'werewolf_rooms'
const S = 'werewolf_state'
const MAXN = [6, 8, 10, 12]
const MOCK_PREFIX = 'mock:ww:'
const DECK = {
  6: ['werewolf', 'werewolf', 'seer', 'witch', 'villager', 'villager'],
  8: ['werewolf', 'werewolf', 'seer', 'witch', 'hunter', 'villager', 'villager', 'villager'],
  10: ['werewolf', 'werewolf', 'werewolf', 'seer', 'witch', 'hunter', 'villager', 'villager', 'villager', 'villager'],
  12: ['werewolf', 'werewolf', 'werewolf', 'werewolf', 'seer', 'witch', 'hunter', 'villager', 'villager', 'villager', 'villager', 'villager']
}
const now = () => Date.now()
async function getOpenId() {
  return cloud.getWXContext().OPENID
}
function shuf(a) {
  const x = a.slice()
  for (let i = x.length - 1; i > 0; i -= 1) {
    const j = (Math.random() * (i + 1)) | 0
    const t = x[i]
    x[i] = x[j]
    x[j] = t
  }
  return x
}
function mk6() {
  return String(100000 + ((Math.random() * 900000) | 0))
}

function isMockOpenId(id) {
  return String(id || '').startsWith(MOCK_PREFIX)
}

function addOneMockMember(members, rid) {
  const ms = members || []
  const mockCount = ms.filter((m) => isMockOpenId(m.openId)).length
  const mockOid = MOCK_PREFIX + String(rid) + ':' + (mockCount + 1)
  return ms.concat([
    {
      openId: mockOid,
      nickName: '模拟玩家' + (mockCount + 1),
      avatarUrl: '',
      profileReady: true,
      isMock: true,
      joinedAt: now()
    }
  ])
}

async function getRoomById(id) {
  if (!id) {
    return null
  }
  const r = await db.collection(R).doc(String(id)).get()
  return r.data || null
}
async function getRoomByCode(code) {
  const c = String(code || '')
    .replace(/\D/g, '')
    .slice(0, 6)
  if (c.length !== 6) {
    return null
  }
  const r = await db
    .collection(R)
    .where({ roomCode: c, status: _.neq('ended') })
    .limit(1)
    .get()
  return r.data[0] || null
}
function nn(room, oid) {
  const m = (room.members || []).find((u) => u.openId === oid)
  return m ? m.nickName : '参与者'
}
function getRole(room, oid) {
  if (room && room.hostOpenId === oid) {
    return ''
  }
  return (room.playerRoles || {})[oid]
}
function participantsOf(room) {
  const host = String((room && room.hostOpenId) || '')
  return (room.members || []).filter((m) => m && m.openId && m.openId !== host)
}
function roomSeatCap(room) {
  return (room.maxPlayers | 0 || 6) + 1
}
function buildPubFromRoom(room) {
  if (!room || !room._id) {
    return null
  }
  const g = room.game || {}
  const al = g.alive || {}
  return {
    roomCode: room.roomCode,
    status: room.status,
    maxPlayers: room.maxPlayers,
    currentPhase: g.phase || 'lobby',
    day: g.day || 0,
    hostOpenId: room.hostOpenId || '',
    players: (room.members || []).map((m, i) =>
      Object.assign(jp.withProfileReadyFlag(m), {
        isHost: m.openId === room.hostOpenId,
        isAlive:
          m.openId === room.hostOpenId ? true : al[m.openId] !== false,
        seat: i + 1
      })
    ),
    publicLog: g.publicLog || [],
    lastNightReport: g.lastNightReport,
    speakIndex: g.speakIndex | 0,
    speakOrder: g.speakOrder || [],
    voteOpen: !!g.voteOpen,
    currentVotes: g.currentVotes || {},
    gameEnd: g.endReason,
    winSide: g.winSide,
    pendingHunter: g.pendingHunter,
    updatedAt: now()
  }
}
async function setPub(room) {
  const doc = buildPubFromRoom(room)
  if (!doc) {
    return
  }
  const safe = omitIdDeep(doc)
  await db
    .collection(S)
    .doc(String(room._id))
    .set({ data: safe })
}
function buildPlayerView(ro, o) {
  if (!ro) {
    return {}
  }
  const pr = ro.playerRoles || {}
  const myR = pr[o]
  const g = ro.game || {}
  const al = g.alive || {}
  const wm = (ro.members || [])
    .filter((m) => pr[m.openId] === 'werewolf' && m.openId !== o)
    .map((m) => m.nickName)
  return {
    isHost: ro.hostOpenId === o,
    myOpenId: o,
    iAmAlive: ro.hostOpenId === o ? true : al[o] !== false,
    myRole: ro.hostOpenId === o ? '' : myR,
    roomCode: ro.roomCode,
    maxPlayers: ro.maxPlayers,
    roomStatus: ro.status,
    phase: g.phase,
    day: g.day,
    night: g.night,
    alive: g.alive,
    publicLog: g.publicLog,
    lastNightReport: g.lastNightReport,
    gameEnd: g.endReason,
    winSide: g.winSide,
    players: (ro.members || []).map((m, i) =>
      Object.assign(jp.withProfileReadyFlag(m), {
        isAlive:
          m.openId === ro.hostOpenId ? true : al[m.openId] !== false,
        seat: i + 1
      })
    ),
    wolfMates: myR === 'werewolf' ? wm : [],
    seer: myR === 'seer' && g.night && g.night.seer ? g.night.seer : null,
    allRoles:
      ro.hostOpenId === o
        ? participantsOf(ro).map((m) => ({
          o: m.openId,
          n: m.nickName,
          r: pr[m.openId]
        }))
        : null,
    speakIndex: g.speakIndex | 0,
    speakOrder: g.speakOrder || [],
    voteOpen: !!g.voteOpen,
    currentVotes: g.currentVotes || {},
    pendingHunter: g.pendingHunter
  }
}
async function doSyncState(event, o) {
  const rid = String((event && event.roomId) || '')
  if (!rid) {
    throw new Error('无房间')
  }
  const ro = await getRoomById(rid)
  if (!ro) {
    throw new Error('聚会组无效或已结束')
  }
  if (!(ro.members || []).some((m) => m.openId === o)) {
    return { ok: 1, myOpenId: o, inRoom: false }
  }
  const pub = buildPubFromRoom(ro)
  const view = buildPlayerView(ro, o)
  return {
    ok: 1,
    myOpenId: o,
    inRoom: true,
    isHost: ro.hostOpenId === o,
    state: pub,
    view
  }
}
function aggWolfVote(wvote) {
  const c = {}
  let best = 0
  let out = null
  Object.keys(wvote || {}).forEach((k) => {
    const t = wvote[k]
    c[t] = (c[t] || 0) + 1
    if (c[t] > best) {
      best = c[t]
      out = t
    }
  })
  return out
}
function checkWin(room) {
  const g = room.game
  const pr = room.playerRoles
  const al = g.alive || {}
  let w = 0
  let good = 0
  ;(room.members || []).forEach((m) => {
    if (m.openId === room.hostOpenId) {
      return
    }
    if (al[m.openId] === false) {
      return
    }
    if (pr[m.openId] === 'werewolf') {
      w += 1
    } else if (pr[m.openId]) {
      good += 1
    }
  })
  if (w === 0) {
    g.phase = 'end'
    g.endReason = '暗位成员均已暂离，村民侧本环节可收束'
    g.winSide = 'good'
    room.status = 'ended'
    return true
  }
  if (w >= good) {
    g.phase = 'end'
    g.endReason = '暗位人数不少于村民侧，本环节收束'
    g.winSide = 'wolf'
    room.status = 'ended'
    return true
  }
  return false
}
async function saveFullRoom(room) {
  await db
    .collection(R)
    .doc(String(room._id))
    .update({
      data: {
        game: room.game,
        status: room.status,
        playerRoles: room.playerRoles,
        updatedAt: now()
      }
    })
  const fresh = await getRoomById(room._id)
  if (fresh) {
    await setPub(fresh)
  }
}
exports.main = async (event) => {
  try {
    return await run(event)
  } catch (e) {
    return { errMsg: (e && e.message) || String(e) }
  }
}
async function run(event) {
  const action = event.action
  const o = await getOpenId()
  if (action === 'create') {
    let code = mk6()
    for (let i = 0; i < 16; i += 1) {
      const e = await getRoomByCode(code)
      if (!e) {
        break
      }
      code = mk6()
    }
    let maxPlayers = parseInt(event.maxPlayers, 10) || 6
    if (MAXN.indexOf(maxPlayers) < 0) {
      maxPlayers = 6
    }
    const d = {
      roomCode: code,
      hostOpenId: o,
      maxPlayers,
      status: 'waiting',
      members: [
        {
          openId: o,
          nickName:
            event.nickName && String(event.nickName).trim().slice(0, 12)
              ? String(event.nickName).trim().slice(0, 12)
              : '房主',
          avatarUrl: String((event && event.avatarUrl) || '').trim(),
          joinedAt: now()
        }
      ],
      game: { phase: 'lobby', day: 0, publicLog: [] },
      createdAt: now(),
      updatedAt: now()
    }
    const { _id } = await db.collection(R).add({ data: d })
    const room = await getRoomById(_id)
    room._id = _id
    await setPub(room)
    return { roomId: _id, roomCode: code, myOpenId: o }
  }
  if (action === 'join') {
    const ro = event.roomId ? await getRoomById(event.roomId) : await getRoomByCode(event.roomCode)
    if (!ro) {
      throw new Error('聚会组无效或已结束')
    }
    if (ro.status !== 'waiting') {
      throw new Error('已开始，无法加入')
    }
    if ((ro.members || []).length >= roomSeatCap(ro)) {
      throw new Error('聚会组人数已满')
    }
    const ms = ro.members || []
    let next
    if (ms.some((u) => u.openId === o)) {
      next = ms.map((m) =>
        m.openId === o ? Object.assign({}, m, jp.mergeJoinFields(event, m)) : m
      )
    } else {
      next = ms.concat([
        Object.assign({ openId: o, joinedAt: now() }, jp.mergeJoinFields(event, {}))
      ])
    }
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { roomId: String(ro._id), roomCode: ro.roomCode, myOpenId: o }
  }
  if (action === 'setSize') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长/主持可设人数')
    }
    if (ro.status !== 'waiting') {
      throw new Error('本环节中不可改')
    }
    const n = parseInt(event.maxPlayers, 10) || 6
    if (MAXN.indexOf(n) < 0) {
      throw new Error('只支持 6/8/10/12 人')
    }
    if (participantsOf(ro).length > n) {
      throw new Error('参与者已超人数，请调整或另建聚会组')
    }
    await db
      .collection(R)
      .doc(String(event.roomId))
      .update({ data: { maxPlayers: n, updatedAt: now() } })
    await setPub(await getRoomById(event.roomId))
    return { maxPlayers: n }
  }
  if (action === 'addMockPlayer') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长可添加')
    }
    if (ro.status !== 'waiting') {
      throw new Error('仅等待阶段可添加')
    }
    const max = ro.maxPlayers | 0 || 6
    const ms = ro.members || []
    if (participantsOf(ro).length >= max) {
      throw new Error('参与者已满')
    }
    if (ms.length >= roomSeatCap(ro)) {
      throw new Error('已满员')
    }
    const next = addOneMockMember(ms, ro._id)
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { ok: 1, added: next[next.length - 1].openId }
  }
  if (action === 'fillMockPlayers') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长可添加')
    }
    if (ro.status !== 'waiting') {
      throw new Error('仅等待阶段可添加')
    }
    const max = ro.maxPlayers | 0 || 6
    let next = ro.members || []
    let added = 0
    for (let i = 0; i < 12; i += 1) {
      if (participantsOf({ members: next, hostOpenId: ro.hostOpenId }).length >= max) {
        break
      }
      if (next.length >= roomSeatCap(ro)) {
        break
      }
      next = addOneMockMember(next, ro._id)
      added += 1
    }
    await db
      .collection(R)
      .doc(String(ro._id))
      .update({ data: { members: next, updatedAt: now() } })
    await setPub(await getRoomById(ro._id))
    return { ok: 1, added }
  }
  if (action === 'start') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅组长可开始')
    }
    const m = ro.members || []
    const n = ro.maxPlayers || 6
    const players = participantsOf(ro)
    if (players.length !== n) {
      throw new Error('参与者未满' + n + '人，暂不可开')
    }
    if (!DECK[n]) {
      throw new Error('人数与板子未配')
    }
    const deck = shuf(DECK[n].slice(0, n))
    const pr = {}
    const al = {}
    if (ro.hostOpenId) {
      pr[ro.hostOpenId] = ''
      al[ro.hostOpenId] = false
    }
    players.forEach((mem, i) => {
      pr[mem.openId] = deck[i]
      al[mem.openId] = true
    })
    const g = {
      day: 1,
      phase: 'night',
      alive: al,
      publicLog: ['第1夜。暗位选择关注对象、线索员查看、治愈者协助。完成后由主持点【结算入昼】。'],
      night: {
        wvote: {},
        wkill: null,
        seer: null,
        wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }
      },
      lastNightReport: null,
      speakOrder: shuf(players.map((u) => u.openId)),
      speakIndex: 0,
      currentVotes: {},
      voteOpen: 0,
      endReason: '',
      winSide: '',
      pendingHunter: null
    }
    await db
      .collection(R)
      .doc(String(event.roomId))
      .update({
        data: {
          status: 'playing',
          playerRoles: pr,
          game: g,
          updatedAt: now()
        }
      })
    await setPub(await getRoomById(event.roomId))
    return { ok: true }
  }
  if (action === 'wWolf') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'werewolf' || ro.game.alive[o] === false) {
      throw new Error('当前不可选择关注目标')
    }
    const t = String(event.targetOpenId || '')
    if (!t) {
      throw new Error('请选择关注对象 openId')
    }
    if (ro.game.alive[t] === false) {
      throw new Error('请选择在场的参与者')
    }
    const wvote = (ro.game.night && ro.game.night.wvote) || {}
    wvote[o] = t
    const wkill = aggWolfVote(wvote) || t
    ro.game.night = { ...(ro.game.night || {}), wvote, wkill }
    await saveFullRoom(ro)
    return { ok: true, wkill }
  }
  if (action === 'wSeer') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'seer' || ro.game.alive[o] === false) {
      throw new Error('当前不可查看线索')
    }
    const t = String(event.targetOpenId || '')
    if (!t || t === o) {
      throw new Error('请选择他人')
    }
    if (ro.game.alive[t] === false) {
      throw new Error('已暂离')
    }
    const isW = getRole(ro, t) === 'werewolf'
    ro.game.night = ro.game.night || {}
    ro.game.night.seer = { checker: o, target: t, isW, label: isW ? '倾向：暗位侧' : '倾向：村民侧' }
    await saveFullRoom(ro)
    return { isW, label: isW ? '暗位侧' : '村民侧' }
  }
  if (action === 'wWitch') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'night' || getRole(ro, o) !== 'witch' || ro.game.alive[o] === false) {
      throw new Error('当前不可使用治愈者能力')
    }
    const nk = ro.game.night || {}
    const wv = nk.wvote || {}
    const wkill = nk.wkill || aggWolfVote(wv)
    let wts = { ...(nk.wwitch || { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null }) }
    if (event.save && wts.saveLeft) {
      if (wkill) {
        wts.saveOn = wkill
        wts.saveLeft = 0
      }
    }
    if (event.poison) {
      const pt = String(event.targetOpenId || '')
      if (wts.poisonLeft && pt && pt !== o) {
        wts.poisonOn = pt
        wts.poisonLeft = 0
      }
    }
    ro.game.night = { ...nk, wwitch: wts, wkill: wkill || nk.wkill }
    await saveFullRoom(ro)
    return { ok: true, knife: wkill, witch: wts }
  }
  if (action === 'hostWolfSet') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持可补选关注意')
    }
    ro.game.night = { ...(ro.game.night || {}), wkill: String(event.targetOpenId || '') }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostResolveNight') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持可结算入昼')
    }
    if (ro.game.phase !== 'night') {
      throw new Error('非夜间')
    }
    const g = ro.game
    const pr = ro.playerRoles
    const al0 = { ...(g.alive || {}) }
    const nk = g.night || {}
    const wkill = nk.wkill || aggWolfVote(nk.wvote || {})
    const wt = nk.wwitch || { saveOn: null, poisonOn: null, saveLeft: 1, poisonLeft: 1 }
    const logp = []
    if (wkill) {
      if (wt.saveOn && wt.saveOn === wkill) {
        logp.push(nn(ro, wkill) + ' 已获缓解。')
      } else {
        al0[wkill] = false
        logp.push('夜间关注后暂离：' + nn(ro, wkill))
      }
    }
    if (wt && wt.poisonOn) {
      const p = wt.poisonOn
      if (al0[p] !== false) {
        al0[p] = false
        logp.push('备用提醒后暂离：' + nn(ro, p))
      }
    }
    g.night = {
      wvote: {},
      wkill: null,
      seer: null,
      wwitch: { saveLeft: wt.saveLeft, poisonLeft: wt.poisonLeft, saveOn: null, poisonOn: null }
    }
    g.alive = al0
    g.lastNightReport = logp
    g.phase = 'day_announce'
    g.publicLog = (g.publicLog || []).concat(logp, ['天亮了。'])
    ro.game = g
    ro.game.alive = al0
    if (checkWin(ro)) {
      /* ended */
    }
    await saveFullRoom(ro)
    return { over: ro.status === 'ended' }
  }
  if (action === 'hostDawnToSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    ro.game.phase = 'speak'
    ro.game.speakIndex = 0
    ro.game.voteOpen = 0
    ro.game.currentVotes = {}
    ro.game.publicLog = (ro.game.publicLog || []).concat(['开始发言。'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostNextSpeak') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    ro.game.speakIndex = (ro.game.speakIndex | 0) + 1
    ro.game.publicLog = (ro.game.publicLog || []).concat(['下一位发言。'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostStartVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    ro.game.phase = 'vote'
    ro.game.voteOpen = 1
    ro.game.currentVotes = {}
    ro.game.publicLog = (ro.game.publicLog || []).concat(['投票离场。'])
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'vote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'vote' || !ro.game.voteOpen || ro.game.alive[o] === false) {
      throw new Error('当前不可投')
    }
    const t0 = String(event.targetOpenId)
    if (!t0) {
      throw new Error('选择投票离场对象')
    }
    const cur = (ro.game.currentVotes || {}) || {}
    ro.game.currentVotes = { ...cur, [o]: t0 }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'hostResolveVote') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.hostOpenId !== o) {
      throw new Error('仅主持')
    }
    const pr = ro.playerRoles
    const g = ro.game
    const cv = g.currentVotes || {}
    const c = {}
    Object.keys(cv).forEach((k) => {
      const y = cv[k]
      c[y] = (c[y] || 0) + 1
    })
    let high = 0
    let victim = null
    Object.keys(c).forEach((k) => {
      if (c[k] > high) {
        high = c[k]
        victim = k
      }
    })
    if (victim) {
      g.alive = g.alive || {}
      g.alive[victim] = false
      g.publicLog = (g.publicLog || []).concat(['投票离场：' + nn(ro, victim) + '。'])
      if (pr[victim] === 'hunter') {
        g.pendingHunter = victim
        g.phase = 'hunter'
      } else {
        g.voteOpen = 0
        g.currentVotes = {}
        g.phase = 'night'
        g.day = (g.day | 0) + 1
        g.publicLog = (g.publicLog || []).concat(['第' + (g.day || 0) + ' 夜。'])
        g.night = { wvote: {}, wkill: null, seer: null, wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null } }
      }
    } else {
      g.voteOpen = 0
    }
    ro.game = g
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { over: ro.status === 'ended' }
  }
  if (action === 'hunterShot') {
    const ro = await getRoomById(event.roomId)
    if (!ro || ro.status !== 'playing' || ro.game.phase !== 'hunter' || o !== ro.game.pendingHunter) {
      throw new Error('协定者本环节不可操作')
    }
    const t1 = String(event.targetOpenId || '')
    if (!t1) {
      throw new Error('请选择一位参与者')
    }
    const g = ro.game
    if (g.alive[t1] === false) {
      throw new Error('目标已暂离')
    }
    g.alive[t1] = false
    g.publicLog = (g.publicLog || []).concat(['协定者邀请 ' + nn(ro, t1) + ' 同步暂离。'])
    g.pendingHunter = null
    g.phase = 'night'
    g.day = (g.day | 0) + 1
    g.night = { wvote: {}, wkill: null, seer: null, wwitch: { saveLeft: 1, poisonLeft: 1, saveOn: null, poisonOn: null } }
    ro.game = g
    if (checkWin(ro)) {
      /* */
    }
    await saveFullRoom(ro)
    return { ok: true }
  }
  if (action === 'getView') {
    const ro = await getRoomById(event.roomId)
    if (!ro) {
      return {}
    }
    return buildPlayerView(ro, o)
  }
  if (action === 'syncState') {
    return await doSyncState(event, o)
  }
  throw new Error('未知action ' + action)
}
