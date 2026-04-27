/**
 * 统一云函数调用；未开通云开发时走本地存储（仅开发体验，生产请部署云函数）
 */
const LOCAL = {
  pet: 'pet_local_list',
  record: 'pet_local_record',
  reminder: 'pet_local_reminder'
}

function hasCloud () {
  return !!wx.cloud
}

function readLocal (key) {
  try {
    return wx.getStorageSync(key) || []
  } catch (e) {
    return []
  }
}

function writeLocal (key, v) {
  try {
    wx.setStorageSync(key, v)
  } catch (e) {}
}

async function call (name, data) {
  if (!hasCloud()) {
    return localEmulate(name, data)
  }
  try {
    const r = await wx.cloud.callFunction({ name, data: data || {} })
    if (r.result && r.result.errMsg) {
      throw new Error(r.result.errMsg)
    }
    return r.result
  } catch (e) {
    console.warn('cloud call fallback', name, e)
    return localEmulate(name, data)
  }
}

function localEmulate (name, data) {
  if (name === 'getPetList') {
    return { list: readLocal(LOCAL.pet) }
  }
  if (name === 'addPet') {
    const list = readLocal(LOCAL.pet)
    if (data._id) {
      const i = list.findIndex((p) => p._id === data._id)
      if (i >= 0) {
        const patch = Object.assign({}, data)
        list[i] = Object.assign({}, list[i], patch, { updatedAt: Date.now() })
        writeLocal(LOCAL.pet, list)
      }
      return { ok: true }
    }
    const id = 'p_' + Date.now()
    const row = Object.assign(
      { _id: id, createdAt: Date.now(), updatedAt: Date.now(), archived: false },
      data
    )
    list.unshift(row)
    writeLocal(LOCAL.pet, list)
    return { id }
  }
  if (name === 'getRecordList') {
    let list = readLocal(LOCAL.record)
    if (data.petId) {
      list = list.filter((r) => r.petId === data.petId)
    }
    if (data.type && data.type !== 'all') {
      list = list.filter((r) => r.kind === data.type)
    }
    if (data.range && data.range !== 'all') {
      const now = Date.now()
      const days = data.range === 30 || data.range === '30' ? 30 : 7
      const t0 = now - days * 24 * 60 * 60 * 1000
      list = list.filter((r) => (r.recordTime || 0) >= t0)
    }
    list.sort((a, b) => (b.recordTime || 0) - (a.recordTime || 0))
    return { list }
  }
  if (name === 'addRecord') {
    if (data._deleteId) {
      const list = readLocal(LOCAL.record).filter((r) => r._id !== data._deleteId)
      writeLocal(LOCAL.record, list)
      return { ok: true }
    }
    if (data._id) {
      const list = readLocal(LOCAL.record)
      const i = list.findIndex((r) => r._id === data._id)
      if (i >= 0) {
        list[i] = Object.assign({}, list[i], data, { updatedAt: Date.now() })
        writeLocal(LOCAL.record, list)
      }
      return { ok: true }
    }
    const list = readLocal(LOCAL.record)
    const id = 'r_' + Date.now()
    list.unshift(
      Object.assign(
        { _id: id, createdAt: Date.now() },
        data
      )
    )
    writeLocal(LOCAL.record, list)
    return { id }
  }
  if (name === 'getReminderList') {
    return { list: readLocal(LOCAL.reminder) }
  }
  if (name === 'addReminder') {
    if (data._deleteId) {
      const list = readLocal(LOCAL.reminder).filter((m) => m._id !== data._deleteId)
      writeLocal(LOCAL.reminder, list)
      return { ok: true }
    }
    const list = readLocal(LOCAL.reminder)
    if (data._id) {
      const i = list.findIndex((m) => m._id === data._id)
      if (i >= 0) {
        list[i] = Object.assign({}, list[i], data, { updatedAt: Date.now() })
        writeLocal(LOCAL.reminder, list)
      }
      return { ok: true }
    }
    const id = 'm_' + Date.now()
    const t = data.remindTime != null ? Number(data.remindTime) : Date.now()
    const row = Object.assign(
      { _id: id, nextAt: t, createdAt: Date.now(), enabled: true },
      data
    )
    list.unshift(row)
    writeLocal(LOCAL.reminder, list)
    return { id }
  }
  if (name === 'statisticData') {
    const recs = readLocal(LOCAL.record)
    const now = Date.now()
    const days = (data && data.range) === 30 ? 30 : 7
    const start = now - days * 24 * 60 * 60 * 1000
    const inRange = recs.filter(
      (r) => (r.recordTime || 0) >= start && (!data.petId || r.petId === data.petId)
    )
    const feed = inRange.filter((r) => r.kind === 'feed').length
    const water = inRange.filter((r) => r.kind === 'water').length
    return { feedCount: feed, waterCount: water, byDay: [] }
  }
  return {}
}

module.exports = { call, hasCloud }
