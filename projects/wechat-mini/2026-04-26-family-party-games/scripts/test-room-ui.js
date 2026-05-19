/**
 * 聚会组开始校验文案单测（Node 运行，勿纳入小程序编译）
 * 命令：node scripts/test-room-ui.js
 */
const {
  explainDrinkStartFail,
  explainUndercoverStartFail,
  explainWerewolfStartFail,
  explainDrawStartFail,
  explainMusicStartFail,
  explainStartFail
} = require('../utils/roomUi')

function assert(cond, msg) {
  if (!cond) {
    throw new Error(msg || 'assert failed')
  }
}

function t(name, fn) {
  try {
    fn()
    console.log('ok', name)
  } catch (e) {
    console.error('FAIL', name, e.message)
    process.exitCode = 1
  }
}

t('drink min 2', () => {
  const b = explainDrinkStartFail('至少 2 人才能开', { playerCount: 1 })
  assert(b.title === '人数不足')
  assert(/当前 1 人/.test(b.content))
})

t('undercover not full', () => {
  const b = explainUndercoverStartFail('人未满6，暂不可开', {
    playerCount: 4,
    needPlayers: 6
  })
  assert(b.title === '人未满')
  assert(/还差 2/.test(b.content))
})

t('werewolf board', () => {
  const b = explainWerewolfStartFail('人数与板子未配', { playerCount: 5, needPlayers: 6 })
  assert(b.title === '人数与板子不符')
})

t('draw words', () => {
  const b = explainDrawStartFail('词库不足，请改分类后重试', { playerCount: 3 })
  assert(b.title === '词库不足')
})

t('music rounds', () => {
  const b = explainMusicStartFail('曲库不足15首，请少选轮数', { playerCount: 2 })
  assert(b.title === '题数过多')
})

t('kind routing', () => {
  const b = explainStartFail('draw', '至少2人才能开始', { playerCount: 1 })
  assert(b.title === '人数不足')
})

t('truth dare min 2', () => {
  const b = explainStartFail('truthDare', '请至少2位参与者进组再开始', { playerCount: 1 })
  assert(b.title === '人数不足')
  assert(/4 位口令/.test(b.content))
})

if (process.exitCode) {
  process.exit(process.exitCode)
}
console.log('all room-ui tests passed')
