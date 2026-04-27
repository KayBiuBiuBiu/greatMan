const kn = require('../../data/knowledge.js')

const bodies = {
  c1: '以体重、年龄与主粮说明为参考，分多次给粮更易消化。可观察体态微调食量，不替代个体情况下的就医建议。',
  c2: '流动水与多点位摆放能提高饮水量；如长期饮水量异常，线下就诊排查。',
  c3: '建议 5–7 天过渡比例，如软便可放慢节奏；记录排便可帮助判断是否适应。',
  c4: '注意易吞食异物与可攀爬高度，为宠物预留安静角落有助适应。',
  c5: '换毛期可增加梳理，减少打结与毛球；皮肤如有红肿屑屑宜线下看诊。',
  d1: '以犬只体力与年龄平衡散步时长，夏日避开正午高温路面。',
  d2: '建立驱虫台账，体内外周期不同，按所购产品说明执行，勿自行加量。',
  d3: '换牙期啃咬可分散注意力，牙龈出血多或持续拒食应线下处理。',
  d4: '洗澡频率与香波类型因犬而异，过频可能破坏皮肤油脂平衡。',
  d5: '外出回家后擦干足部，腹部保暖；饮水避免长时间冰冻过凉。',
  o1: '垫料与笼舍需勤换以防潮湿与异味，观察食欲与排便可察觉异常趋势。',
  o2: '不同物种有各自适宜温区与照度，记录环境参数更稳妥。',
  q1: '提前准备食水、厕所位置与低干扰空间，前数日减少强行互动。',
  q2: '固定 1 分钟在睡前补记，配合提醒可减少遗漏，避免事后回忆偏差。'
}

function enrich () {
  return kn.list.map((a) => ({
    ...a,
    body: bodies[a.id] || a.summary
  }))
}
const all = enrich()

Page({
  data: {
    q: '',
    categories: kn.categories,
    cIdx: 0,
    display: all,
    cur: null
  },
  onLoad () {
    this.filter()
  },
  onQ (e) {
    const q = (e.detail && e.detail.value) || ''
    this.setData({ q }, () => this.filter())
  },
  onC (e) {
    this.setData({ cIdx: parseInt(e.currentTarget.dataset.i, 10) || 0 }, () =>
      this.filter()
    )
  },
  filter () {
    const q = this.data.q
    const cat = kn.categories[this.data.cIdx] || '全部'
    let arr = all
    if (cat !== '全部') {
      arr = arr.filter((a) => a.cat === cat)
    }
    if (q) {
      arr = arr.filter(
        (a) => a.title.indexOf(q) >= 0 || a.summary.indexOf(q) >= 0
      )
    }
    this.setData({ display: arr })
  },
  onOpen (e) {
    const id = e.currentTarget.dataset.id
    const c = all.find((x) => x.id === id)
    this.setData({ cur: c })
  },
  onClose () {
    this.setData({ cur: null })
  }
})
