const gameGroups = [
  {
    key: 'a',
    title: 'A类：主持人用手机',
    description: '主持人手持手机，其他人主要通过口头、动作和投票互动。',
    games: [
      {
        title: '谁是卧底',
        status: '已实现',
        summary: '至少 3 人且需凑满设定人数；本机看词与投票。'
      },
      {
        title: '真心话大冒险',
        status: '已实现',
        summary: '4 位口令同房，每人用自己手机投票定真心话或趣味任务。'
      },
      {
        title: '海龟汤',
        status: '规则辅助',
        summary: '可扩展汤面、汤底、提示点与提问记录。'
      },
      {
        title: '优点轰炸',
        status: '规则辅助',
        summary: '可扩展参与者优点记录和优点卡片生成。'
      },
      {
        title: '大瞎话',
        status: '规则辅助',
        summary: '可复用趣味任务库，随机显示任务。'
      },
      {
        title: '猜数字',
        status: '规则辅助',
        summary: '可扩展随机数、范围更新、猜测次数和庆祝效果。'
      },
      {
        title: '十五二十',
        status: '规则辅助',
        summary: '可扩展双人计分、环节计时和互动记录。'
      },
      {
        title: '秘密身份推理（聚会版）',
        status: '已实现',
        summary: '选 6/8/10/12 人局，人齐后开始；本机私看身份，主持推流程。'
      },
      {
        title: '趣味抽签',
        status: '同场同步+云',
        summary: '至少 2 人；随机一人响铃、喝 1～10 口，同屏同步。'
      },
      {
        title: 'AI迷雾推理局',
        status: '同场同步+云',
        summary: '至少 3 人；AI 生成剧本，线下口头推理，本机看剧本与私密证据。'
      }
    ]
  },
  {
    key: 'b',
    title: 'B类：看题瞬间用手机',
    description: '手机快速传递，参与者只看几秒题目后表演、描述或作答。',
    games: [
      {
        title: '你画我猜轮流传词版',
        status: '同场同步+本地',
        summary: '首页为数字口令同场画布（至少 2 人）；本表为线下传词计分。'
      },
      {
        title: '疯狂猜歌',
        status: '规则辅助',
        summary: '同场版为组长主持本机外放+抢答；本页为家庭线下提示互动。'
      },
      {
        title: '贴头猜词',
        status: '同场同步+云',
        summary: '6 位口令同房；每人看自己头上？？？，猜对自己获胜。'
      },
      {
        title: '不要做挑战',
        status: '同场同步+云',
        summary: '6 位口令；自己禁止动作保密，诱导他人犯规，坚持到最后。'
      },
      {
        title: '倒着说',
        status: '规则辅助',
        summary: '可扩展短句库、5秒倒计时和正确次数统计。'
      },
      {
        title: '默契大考验',
        status: '规则辅助',
        summary: '可扩展问题展示、手动计票和结果分布。'
      }
    ]
  },
  {
    key: 'c',
    title: 'C类：小程序作为辅助工具',
    description: '实际互动基本不用手机，小程序提供规则、计时、随机题和计分。',
    games: [
      {
        title: '故事接龙',
        status: '已实现',
        summary: '随机故事开头、文本接龙记录、生成全文。'
      },
      {
        title: '逛三园',
        status: '已实现',
        summary: '随机主题、5秒计时、失败者惩罚次数。'
      },
      {
        title: '123木头人/红绿灯',
        status: '规则辅助',
        summary: '可扩展规则图文、随机停动计时和暂离记录。'
      },
      {
        title: '网鱼',
        status: '规则辅助',
        summary: '可扩展角色随机分配和规则图解。'
      },
      {
        title: '画一画长卷',
        status: '规则辅助',
        summary: '可扩展主题灵感卡、计时器和作品记录。'
      },
      {
        title: '成语接龙 / 飞花令',
        status: '规则辅助',
        summary: '可扩展随机起始字、去重记录和提示。'
      },
      {
        title: '蒙眼贴五官',
        status: '规则辅助',
        summary: '可扩展打印模板、难度和完成时间。'
      },
      {
        title: '躲猫猫 / 找影子',
        status: '规则辅助',
        summary: '可扩展手影教学库和随机挑战。'
      },
      {
        title: '揪尾巴',
        status: '规则辅助',
        summary: '可扩展计分板和随机口号。'
      },
      {
        title: '袋鼠跳跳跳',
        status: '规则辅助',
        summary: '可扩展秒表、分组与同场计分参考。'
      },
      {
        title: '爱心接力 / 齐心协力',
        status: '规则辅助',
        summary: '可扩展计时、计分和随机难度。'
      },
      {
        title: '我是影帝',
        status: '规则辅助',
        summary: '可扩展情绪/场景词库、提示和计分。'
      }
    ]
  }
]

const undercoverPairs = [
  ['饺子', '包子'],
  ['牛奶', '豆浆'],
  ['苹果', '梨'],
  ['口红', '唇膏'],
  ['手机', '平板'],
  ['咖啡', '奶茶'],
  ['老师', '教练'],
  ['火锅', '麻辣烫'],
  ['电影', '电视剧'],
  ['公交车', '地铁'],
  ['书包', '行李箱'],
  ['羽毛球', '网球'],
  ['太阳', '月亮'],
  ['雨伞', '雨衣'],
  ['冰箱', '空调'],
  ['面包', '蛋糕'],
  ['西瓜', '哈密瓜'],
  ['猫', '狗'],
  ['飞机', '高铁'],
  ['医生', '护士']
]

const truthQuestions = [
  '你最近一次偷偷开心是因为什么？',
  '如果今天可以实现一个小愿望，你想要什么？',
  '你小时候做过最调皮的事是什么？',
  '你最怕家里谁突然严肃起来？',
  '你觉得自己最可爱的习惯是什么？',
  '你最近一次撒娇是什么时候？',
  '如果能和家里任何人交换一天身份，你选谁？',
  '你最想学会的一项技能是什么？',
  '你曾经误会过谁？后来怎么发现的？',
  '你觉得自己最需要改掉的小毛病是什么？',
  '你最喜欢的一顿家庭晚餐是什么？',
  '如果给自己取一个外号，你会叫什么？',
  '你最想感谢家里的谁？为什么？',
  '你有没有藏过零食？藏在哪里？',
  '你最想重来的一天是哪一天？'
]

const dareQuestions = [
  '用三种动物叫声介绍自己。',
  '模仿一位家人说一句经典口头禅。',
  '原地转三圈后摆一个英雄姿势。',
  '用夸张表情唱一句生日歌。',
  '给左手边的人一个真诚夸奖。',
  '用机器人语气说一段新年祝福。',
  '表演一只刚睡醒的小猫。',
  '用身体比出一个大大的爱心。',
  '任选一人击掌并说“今天你最棒”。',
  '假装自己是天气预报员播报今天心情。',
  '做一个 10 秒慢动作电影镜头。',
  '用方言或奇怪口音说“我赢定了”。',
  '表演正在吃超酸柠檬。',
  '给大家设计一个全家口号。',
  '用一只脚站立并数到 10。'
]

const drawWords = [
  '大象',
  '火箭',
  '冰淇淋',
  '小猫钓鱼',
  '下雨天',
  '机器人',
  '海底世界',
  '滑雪',
  '孙悟空',
  '煎鸡蛋',
  '洗衣机',
  '熊猫',
  '消防员',
  '月亮',
  '踢足球',
  '过山车',
  '生日蛋糕',
  '魔术师',
  '飞船',
  '跳绳',
  '长颈鹿',
  '骑自行车',
  '打喷嚏',
  '放风筝',
  '火锅'
]

const storyStarts = [
  '在一个下雨的夜晚，我发现家里的猫会说话。',
  '早上醒来，客厅中间多了一扇发光的小门。',
  '爷爷的旧收音机突然播出了明天的新闻。',
  '我们全家坐上电梯，却到了云朵上的城市。',
  '冰箱里的一颗草莓给大家写了一封信。',
  '小区花园里出现了一只会送快递的恐龙。',
  '晚饭时，米饭粒排成了一张藏宝图。',
  '今天的月亮掉进了阳台的水桶里。',
  '一只迷路的机器人敲门说要找妈妈。',
  '全家的影子突然决定出去旅行。'
]

const gardens = [
  {
    name: '动物园',
    examples: ['老虎', '大象', '熊猫', '长颈鹿', '猴子', '斑马']
  },
  {
    name: '水果园',
    examples: ['苹果', '香蕉', '西瓜', '葡萄', '橙子', '草莓']
  },
  {
    name: '蔬菜园',
    examples: ['白菜', '萝卜', '黄瓜', '茄子', '土豆', '番茄']
  },
  {
    name: '交通工具园',
    examples: ['汽车', '火车', '飞机', '轮船', '地铁', '自行车']
  },
  {
    name: '职业园',
    examples: ['医生', '老师', '厨师', '警察', '司机', '演员']
  },
  {
    name: '颜色园',
    examples: ['红色', '蓝色', '绿色', '黄色', '紫色', '黑色']
  },
  {
    name: '运动园',
    examples: ['足球', '篮球', '游泳', '跑步', '跳绳', '滑雪']
  },
  {
    name: '家电园',
    examples: ['电视', '冰箱', '空调', '洗衣机', '电饭煲', '吹风机']
  }
]

const helperGames = {
  '海龟汤': {
    mode: 'riddle',
    primary: '换一题',
    secondary: '看汤底',
    prompts: [
      {
        title: '雨夜的门铃',
        detail: '一个雨夜，门铃响了三次。主人看了门口一眼，没有开门，却立刻报了警。',
        answer: '门口没有人，但地上有一串湿脚印通向屋内，说明有人已经进来了。',
        hint: '注意“门口”和“屋内”的关系。'
      },
      {
        title: '不会响的电话',
        detail: '电话一直没有响，老人却知道远方的儿子今晚不会回来了。',
        answer: '老人每天都会等儿子报平安电话，那天电话线路被暴雨吹断，窗外还能看到被冲坏的桥。',
        hint: '不是超能力，是环境给了线索。'
      },
      {
        title: '消失的蛋糕',
        detail: '蛋糕放在桌上，房间门窗都关着，回来时蛋糕少了一半，屋里没有别人。',
        answer: '家里的狗躲在桌布下面，门窗没开不代表没有动物。',
        hint: '“别人”不等于没有其他生物。'
      }
    ]
  },
  '优点轰炸': {
    mode: 'promptScore',
    primary: '换提示',
    secondary: '收到优点+1',
    prompts: [
      { title: '夸行动', detail: '说出 TA 最近做过的一件让你觉得贴心的小事。' },
      { title: '夸性格', detail: '说出 TA 身上一个让大家相处舒服的特点。' },
      { title: '夸能力', detail: '说出 TA 做得很棒的一项能力或习惯。' },
      { title: '夸陪伴', detail: '说出一次 TA 陪伴或帮助你的经历。' }
    ]
  },
  '大瞎话': {
    mode: 'random',
    primary: '随机指令',
    prompts: [
      { title: '搞怪任务', detail: '用播音腔夸奖右手边的人 10 秒。' },
      { title: '模仿任务', detail: '模仿一种动物走路，让大家猜。' },
      { title: '反应任务', detail: '闭眼原地转一圈，然后指出你觉得最会演的人。' },
      { title: '表情任务', detail: '连续做出开心、震惊、委屈三个表情。' }
    ]
  },
  '猜数字': {
    mode: 'number',
    prompts: [
      { title: '猜数字', detail: '系统生成 1-100 的数字，主持人输入参与者猜测，自动提示大了或小了。' }
    ]
  },
  '十五二十': {
    mode: 'score',
    prompts: [
      { title: '十五二十', detail: '两人同时出手并喊总数，猜对者记 1 分。' }
    ]
  },
  '疯狂猜歌': {
    mode: 'randomScore',
    primary: '换一首',
    secondary: '猜中+1',
    prompts: [
      { title: '小星星', detail: '由主持人哼唱前奏或节奏，其他人抢答歌名。' },
      { title: '两只老虎', detail: '只能哼 5 秒，猜中者得分。' },
      { title: '生日快乐歌', detail: '用拍手节奏提示，不要直接唱歌词。' },
      { title: '让我们荡起双桨', detail: '主持人描述年代和场景，大家猜歌名。' }
    ]
  },
  '倒着说': {
    mode: 'reverse',
    primary: '下一句',
    secondary: '答对+1',
    prompts: [
      { title: '我是好人', detail: '倒着说：人好是我' },
      { title: '吃苹果', detail: '倒着说：果苹吃' },
      { title: '天气真好', detail: '倒着说：好真气天' },
      { title: '一起回家', detail: '倒着说：家回起一' }
    ]
  },
  '默契大考验': {
    mode: 'promptScore',
    primary: '换问题',
    secondary: '一致+1',
    prompts: [
      { title: '谁最会做饭？', detail: '大家同时指向一个人，主持人记录是否一致。' },
      { title: '谁最容易赖床？', detail: '同时指人，看答案是否集中。' },
      { title: '谁最适合当队长？', detail: '说出选择理由，增加讨论。' },
      { title: '谁最会讲笑话？', detail: '票数最高者现场讲一个。' }
    ]
  },
  '123木头人/红绿灯': {
    mode: 'traffic',
    primary: '随机口令',
    secondary: '暂离+1',
    prompts: [
      { title: '绿灯', detail: '大家可以向前移动。' },
      { title: '红灯', detail: '所有人立刻定住，动的人本环节暂离。' },
      { title: '木头人', detail: '喊完回头检查，动的人本环节暂离。' }
    ]
  },
  '网鱼': {
    mode: 'ruleRandom',
    primary: '随机初始网',
    prompts: [
      { title: '2 人成网', detail: '随机选 2 人手拉手当网，其余人当鱼。抓到的鱼加入网。' },
      { title: '3 人成网', detail: '人数较多时选 3 人当网，注意控制奔跑速度。' },
      { title: '安全提醒', detail: '划定边界，不能推拉，抓到后轻拍示意即可。' }
    ]
  },
  '画一画长卷': {
    mode: 'timerRandom',
    primary: '换主题',
    secondary: '开始计时',
    prompts: [
      { title: '未来的家', detail: '每人添一笔或一个局部，最后讲故事。' },
      { title: '海底世界', detail: '每轮 30 秒，不能擦掉别人画的内容。' },
      { title: '太空旅行', detail: '每个人必须画一个新角色或道具。' }
    ]
  },
  '成语接龙 / 飞花令': {
    mode: 'wordRecord',
    primary: '换起点',
    secondary: '记录+1',
    prompts: [
      { title: '成语接龙：天', detail: '从“天”字开头或以上一个成语尾字接龙。示例：天长地久。' },
      { title: '飞花令：月', detail: '说出含“月”的诗句。示例：举头望明月。' },
      { title: '飞花令：花', detail: '说出含“花”的诗句。示例：春眠不觉晓，处处闻啼鸟可换题。' },
      { title: '成语接龙：一', detail: '示例：一心一意、一帆风顺。' }
    ]
  },
  '蒙眼贴五官': {
    mode: 'timerRandom',
    primary: '换难度',
    secondary: '开始计时',
    prompts: [
      { title: '简单', detail: '只贴眼睛和嘴巴，家长可以口头提示方向。' },
      { title: '普通', detail: '贴眼睛、鼻子、嘴巴，限时 60 秒。' },
      { title: '困难', detail: '原地转一圈后再贴，其他人只能说上下左右。' }
    ]
  },
  '躲猫猫 / 找影子': {
    mode: 'random',
    primary: '随机挑战',
    prompts: [
      { title: '兔子手影', detail: '用手影做兔子，让其他人猜。' },
      { title: '小鸟手影', detail: '做出会飞的小鸟影子。' },
      { title: '躲猫猫规则', detail: '规定可躲范围和寻找时间，找到后轻声喊名字。' }
    ]
  },
  '揪尾巴': {
    mode: 'score',
    prompts: [
      { title: '揪尾巴计分', detail: '揪到别人尾巴 +1，被揪掉也记录一次。注意不要推撞。' }
    ]
  },
  '袋鼠跳跳跳': {
    mode: 'stopwatch',
    primary: '开始/暂停',
    secondary: '记录成绩',
    prompts: [
      { title: '袋鼠跳跳跳', detail: '记录每组完成时间，时间最短者获胜。' }
    ]
  },
  '爱心接力 / 齐心协力': {
    mode: 'timerRandom',
    primary: '随机难度',
    secondary: '开始计时',
    prompts: [
      { title: '背对背运球', detail: '两人背对背夹住气球，运到终点。' },
      { title: '单脚挑战', detail: '两人只能单脚跳前进，掉球重来。' },
      { title: '不能说话', detail: '全程不能说话，只能用动作配合。' }
    ]
  },
  '我是影帝': {
    mode: 'randomScore',
    primary: '抽表演题',
    secondary: '猜中+1',
    prompts: [
      { title: '在火星上散步', detail: '表演者不能说出题目关键词。' },
      { title: '发现沙漠里的冰淇淋', detail: '要演出惊喜和纠结。' },
      { title: '偷偷吃到超酸柠檬', detail: '只用表情和动作表演。' },
      { title: '第一次坐过山车', detail: '其他人猜场景。' }
    ]
  }
}

function getTurtleSoupRiddles() {
  const g = helperGames['海龟汤']
  return (g && g.prompts) || []
}

function getTurtleSoupRiddleByIndex(index) {
  const list = getTurtleSoupRiddles()
  if (!list.length) {
    return { title: '海龟汤', detail: '暂无题目', answer: '', hint: '' }
  }
  const i = ((index | 0) % list.length + list.length) % list.length
  return list[i]
}

module.exports = {
  gameGroups,
  undercoverPairs,
  truthQuestions,
  dareQuestions,
  drawWords,
  storyStarts,
  gardens,
  helperGames,
  getTurtleSoupRiddles,
  getTurtleSoupRiddleByIndex
}
