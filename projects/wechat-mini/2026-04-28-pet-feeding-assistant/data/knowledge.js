/**
 * 养宠知识库：基础养护科普，非医疗建议
 */
const list = [
  { id: 'c1', cat: '猫养护', title: '成猫每日食量如何估算', summary: '可将体重与主食包装建议量对照，分 2–3 次给予，根据体态微调。' },
  { id: 'c2', cat: '猫养护', title: '猫咪饮水小习惯', summary: '多放几个水碗、保持水质新鲜，湿粮可适量补充水分。' },
  { id: 'c3', cat: '猫养护', title: '换粮如何过渡', summary: '新粮与旧粮按天数逐渐增减比例，观察排便与食欲再稳定。' },
  { id: 'c4', cat: '猫养护', title: '居家环境安全提示', summary: '收好线绳类小物，确认窗户与阳台防护，减少误食风险。' },
  { id: 'c5', cat: '猫养护', title: '日常梳理与被毛', summary: '按被毛长度选择梳子频率，换毛季可适当增加。' },
  { id: 'd1', cat: '狗养护', title: '成犬散步与休息节奏', summary: '结合体型与年龄安排运动量，避免高温时段长时户外活动。' },
  { id: 'd2', cat: '狗养护', title: '驱虫周期怎么记', summary: '按产品说明与季节记录体内外驱虫时间，用台账避免遗漏。' },
  { id: 'd3', cat: '狗养护', title: '换牙与咀嚼玩具', summary: '准备适龄啃咬玩具，观察口腔与牙龈，不适时及时线下就医。' },
  { id: 'd4', cat: '狗养护', title: '洗澡与皮肤护理', summary: '控制频率，洗后吹干，皮肤易敏感时可咨询线下兽医。' },
  { id: 'd5', cat: '狗养护', title: '冬季保暖要点', summary: '短毛犬可准备衣物，足部清洁防干裂，注意饮水不结冰。' },
  { id: 'o1', cat: '异宠养护', title: '小宠笼舍与垫料', summary: '保持干燥通风，按品种更换垫料，定期清洁食水器。' },
  { id: 'o2', cat: '异宠养护', title: '温湿度与光照', summary: '查阅品种适宜区间，用温湿度计辅助记录更稳妥。' },
  { id: 'q1', cat: '常见问题', title: '新宠物到家前准备', summary: '提前准备食水碗、安全活动区与静养环境，减少应激。' },
  { id: 'q2', cat: '常见问题', title: '如何养成记录习惯', summary: '固定睡前或用餐后 1 分钟在台账补记，配合提醒更省力。' }
]

function byKeyword (q) {
  if (!q) {
    return list
  }
  const s = String(q).trim()
  if (!s) {
    return list
  }
  return list.filter(
    (a) => a.title.indexOf(s) >= 0 || a.summary.indexOf(s) >= 0
  )
}

function byCategory (c) {
  if (!c || c === '全部') {
    return list
  }
  return list.filter((a) => a.cat === c)
}

module.exports = { list, byKeyword, byCategory, categories: ['全部', '猫养护', '狗养护', '异宠养护', '常见问题'] }
