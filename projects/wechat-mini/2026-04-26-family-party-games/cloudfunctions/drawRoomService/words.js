/** 与 data/draw-words.js 保持词表一致，部署时同步 */
const CATS = ['动物', '食物', '日常', '职业', '其他']
const WORDS = [
  { id: 'w1', w: '大象', c: '动物' },
  { id: 'w2', w: '企鹅', c: '动物' },
  { id: 'w3', w: '长颈鹿', c: '动物' },
  { id: 'w4', w: '蝴蝶', c: '动物' },
  { id: 'w5', w: '蜗牛', c: '动物' },
  { id: 'w6', w: '汉堡', c: '食物' },
  { id: 'w7', w: '西瓜', c: '食物' },
  { id: 'w8', w: '火锅', c: '食物' },
  { id: 'w9', w: '冰淇淋', c: '食物' },
  { id: 'w10', w: '咖啡', c: '食物' },
  { id: 'w11', w: '雨伞', c: '日常' },
  { id: 'w12', w: '手机', c: '日常' },
  { id: 'w13', w: '电脑', c: '日常' },
  { id: 'w14', w: '微笑', c: '其他' },
  { id: 'w15', w: '睡觉', c: '其他' },
  { id: 'w16', w: '跑步', c: '其他' },
  { id: 'w17', w: '飞机', c: '其他' },
  { id: 'w18', w: '汽车', c: '其他' },
  { id: 'w19', w: '自行车', c: '其他' },
  { id: 'w20', w: '老师', c: '职业' },
  { id: 'w21', w: '医生', c: '职业' },
  { id: 'w22', w: '警察', c: '职业' },
  { id: 'w23', w: '厨师', c: '职业' },
  { id: 'w24', w: '农民', c: '职业' },
  { id: 'w25', w: '书包', c: '日常' },
  { id: 'w26', w: '闹钟', c: '日常' },
  { id: 'w27', w: '彩虹', c: '其他' },
  { id: 'w28', w: '月亮', c: '其他' },
  { id: 'w29', w: '星星', c: '其他' },
  { id: 'w30', w: '火山', c: '其他' },
  { id: 'w31', w: '滑雪', c: '其他' },
  { id: 'w32', w: '游泳', c: '其他' }
]
const BY_ID = {}
WORDS.forEach((x) => { BY_ID[x.id] = x })
function pickPool (cat) {
  if (cat && cat !== 'all') {
    return WORDS.filter((x) => x.c === cat)
  }
  return WORDS.slice()
}
module.exports = { WORDS, BY_ID, pickPool, CATS }
