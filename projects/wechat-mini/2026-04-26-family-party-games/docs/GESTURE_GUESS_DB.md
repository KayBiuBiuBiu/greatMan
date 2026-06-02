你比划我猜（手机版）- 开发任务说明书
本文档用于指导 AI 编程助手（Cursor / CodingPlan）完整实现「你比划我猜」微信小程序游戏。
项目：家庭聚会助手
云环境 ID：cloud1-d9g01no7m292bc511
参考已有游戏：你画我猜、谁是卧底

一、概述
1.1 游戏规则
玩家进入同一房间（6 位口令）。

每轮随机指定一名「表演者」，其他玩家为「猜词者」。

表演者看到词语后，只能通过肢体动作、表情、口型（不能出声） 传达信息。

猜词者随时提交答案。第一个答对者得分（+3），表演者得分（+2）。

每轮限时 60 秒（可配置），超时或表演者点击「跳过」则本轮无得分。

多轮结束后，按总积分排名。

1.2 区别于「你画我猜」
无画板，纯表演 + 抢答。

表演者不能说话（规则限定，但技术上不拦截语音，依靠玩家自觉；也可增加「检测声音」警告，非必需）。

二、数据设计（按你提供的方案）
2.1 集合与字段
gesture_rooms
js
{
  _id: string,
  roomCode: string,              // 6 位数字口令，唯一索引
  hostOpenId: string,
  status: 'waiting' | 'playing' | 'finished',
  totalRounds: number,           // 5,6,8,9,10,12
  roundDuration: number,         // 秒，默认 60
  wordCategory: string,          // 'all' 或分类名（与 words.js 中 c 一致）
  usedWordIds: string[],         // 已使用过的词语 id（避免重复）
  currentWordId: string,         // 当前轮词语 id
  currentWordText: string,       // 当前轮词语文字（用于判题，不返给非表演者）
  createdAt: Date,
  updatedAt: Date
}
gesture_players
js
{
  _id: string,
  roomId: string,
  openId: string,
  nickName: string,
  avatarUrl: string,
  score: number,
  joinedAt: Date
}
索引：roomId + openId 复合唯一。

gesture_gameState
js
{
  _id: string,                   // 等于 roomId
  phase: 'waiting' | 'performing' | 'revealed' | 'finished',
  currentRound: number,
  roundStartTime: number,        // 毫秒时间戳
  roundHits: [                   // 答对记录（仅本轮）
    { openId: string, nickName: string, timestamp: number }
  ],
  performerOpenId: string,       // 当前表演者
  revealedWord: string,          // 揭晓后公屏展示的词（仅在 revealed 阶段有值）
  publicPlayers: [               // 玩家排行（实时更新）
    { openId, nickName, score }
  ],
  publicLog: string[],           // 公屏消息（如“xx 猜中了！”）
  updatedAt: Date
}
安全：performerOpenId 不暴露给表演者自己？实际上表演者需要知道自己是不是表演者，所以所有玩家都能看到这个字段，但词语只有表演者通过 getView 拿到。

前端根据 phase 和 performerOpenId === myOpenId 渲染不同界面。

2.2 云函数 gestureRoomService actions
action	参数	描述
create	nickName, config	创建房间，初始化 players 和 gameState
join	roomCode, nickName, avatarUrl	加入房间，写入 players
setConfig	roomId, config	仅房主可修改（totalRounds, roundDuration, wordCategory）
startGame	roomId	生成词库（调用 generateCharacters 或从内置词库取），设置第一轮
submitGuess	roomId, answer	猜词者提交答案，校验（完全匹配或相似度），若正确则更新分数、记录 roundHits，结束本轮（或进入 revealed）
skipWord	roomId	表演者跳过当前词，无得分，进入揭示阶段
reveal	roomId	超时或跳过时调用，揭晓答案，显示在 gameState.revealedWord
nextRound	roomId	进入下一轮（自动调用或房主手动）
endGame	roomId	强制结束
getView	roomId	返回：{ room, gameState, players, myOpenId, isHost, isPerformer, performerWord }（performerWord 仅当 isPerformer 为 true 时返回）
2.3 词库来源
系统词库：使用已有 game_characters 集合，按 wordCategory 和 difficulty 查询。

AI 生成：调用 generateCharacters 云函数（已实现），生成指定数量词条。

开始游戏时，根据 totalRounds 预先生成或抽取足够数量的词，存入 usedWordIds 和 currentWordId。

三、前端页面设计
3.1 页面路径与分包
页面路径：packageGames/gesture/gesture

分包：在 app.json 的 subpackages 中添加 "packageGames/gesture"

3.2 等待页面（phase = 'waiting'）
显示房间口令、成员列表（rg-members-card），当前人数/目标人数（最小 2 人）。

房主可展开「游戏设置」面板：

总轮数选择器（5/6/8/9/10/12）

每轮时长选择器（30/60/90 秒）

词库分类（从 game_characters 动态获取，或内置选项）

AI 生成开关（若开启，则开始游戏时调用 generateCharacters）

房主可见「开始游戏」按钮（人数 ≥ 2 时可用）。

非房主等待，显示「等待房主开始游戏」。

3.3 表演阶段（phase = 'performing'）
表演者视角：

顶部倒计时（圆形进度条，或数字）。

中央大号字体显示当前词语（仅表演者可见）。

底部按钮：「跳过」（触发 skipWord）。

猜词者视角：

顶部倒计时。

中央显示“表演者正在表演…”以及提示“输入你的答案”。

下方输入框 +「提交」按钮。

公共区域：

右侧或底部实时得分榜（publicPlayers）。

公屏消息滚动（publicLog），如“小明猜中了！”。

显示当前回合数 / 总轮数。

3.4 揭示阶段（phase = 'revealed'）
展示本轮词语（revealedWord）、猜中者（如果有）、本轮得分变化。

自动停留 3 秒，然后调用 nextRound 进入下一轮（或房主手动「下一轮」按钮）。

3.5 游戏结束（status = 'finished'）
显示最终排行榜（按积分排序）。

房主显示「再来一局」按钮（重置分数、重新生成词库）。

四、AI 词库集成
4.1 复用 generateCharacters 云函数
调用方式：

js
wx.cloud.callFunction({
  name: 'generateCharacters',
  data: { category: '娱乐明星', difficulty: 'easy', count: totalRounds }
})
返回数组 [{ name, desc, hint }]，取 name 作为词条。

若失败，降级使用系统词库。

4.2 系统词库
从 game_characters 集合按 category 和 difficulty 随机抽取（difficulty 可选，默认 easy）。

五、技术实现要点
5.1 前端轮询
使用 setInterval 每 1 秒调用 getView 获取最新状态，更新 UI。

表演者词语通过 getView 返回的 performerWord 获取。

5.2 倒计时
前端根据 roundStartTime 和 roundDuration 计算剩余秒数。

倒计时归零时，若仍未猜中，自动调用 reveal（超时揭示）。

5.3 判题逻辑（云函数 submitGuess）
获取当前 currentWordText（词语面）。

忽略大小写、首尾空格，完全匹配为正确。

可选：增加简单相似度（如编辑距离≤1，但会增加复杂度，初级版本完全匹配即可）。

若正确：

记录猜中者 openId 到 roundHits。

增加猜中者分数（+3），表演者分数（+2）。

更新 publicPlayers 分数。

添加 publicLog。

调用 reveal 进入揭示阶段。

若已经有人猜中，返回 { alreadySolved: true }。

5.4 表演者跳过
调用 skipWord → 直接调用 reveal，无得分。

六、测试用例（Minium 自动化）
6.1 准备工作
创建 minium-tests/pages/gesture_page.py，继承 BasePage。

创建 minium-tests/testcases/test_gesture.py。

6.2 测试用例列表
编号	名称	步骤	断言
TC-01	创建房间	点击「你比划我猜」→ 设置参数 → 创建	进入等待页，生成 6 位口令
TC-02	加入房间	输入正确口令，昵称	成员列表出现新玩家
TC-03	人数不足开始	仅 1 人点击开始	弹窗提示“至少需要 2 人”
TC-04	正常开始游戏（系统词库）	2 人，房主开始	进入表演阶段，表演者看到词语
TC-05	猜中词语	猜词者输入正确答案提交	表演者得分+2，猜词者+3，进入揭示阶段
TC-06	超时未猜中	等待倒计时结束	自动揭示，无得分
TC-07	表演者跳过	表演者点击「跳过」	揭示阶段，无得分
TC-08	多轮计分	完成 3 轮后	最终排行榜总分正确
TC-09	AI 词库生成	开启 AI 生成，开始游戏	使用的词语来自 AI（检查词库是否非空）
TC-10	房主中途退出	房主退出房间	自动转移房主给其他玩家（需实现）
6.3 测试脚本示例（伪代码）
python
class TestGesture(BaseMiniTest):
    def test_core_flow(self):
        page = GesturePage(self)
        room_info = page.create_room(totalRounds=3, category='animal')
        self.cloud.seed_players('gesture', room_code=room_info['roomCode'], count=1)
        page.start_game()
        # 表演者视角
        page.assert_performer_word_visible()
        # 猜词者提交
        page.submit_answer('大象')
        page.wait_reveal()
        page.assert_score('表演者', 2)
        page.assert_score('猜词者', 3)
        # 等待下一轮
        page.wait_next_round()
        # 重复...
七、与现有项目的集成
7.1 首页注册
修改 data/game-data.js，添加：

js
{ title: "你比划我猜", screen: "gesture", summary: "一人表演，多人猜词", icon: "gesture.png" }
7.2 首页跳转
pages/index/index.js 的 startGame 中增加：

js
case 'gesture':
  wx.navigateTo({ url: '/packageGames/gesture/gesture?mode=create' });
  break;
7.3 6 位口令探测
joinRoomByCode 中增加 gestureRoomService.join 尝试。

7.4 样式复用
复用 styles/room-game.wxss 中的成员列表、按钮等。

八、部署与验收清单
数据库：创建 gesture_rooms、gesture_players、gesture_gameState 集合，设置索引。

云函数：部署 gestureRoomService（需安装依赖 wx-server-sdk）。

前端：上传小程序代码，设为体验版。

测试：运行 Minium 测试用例，确保全部通过。

验收：真机双人测试完整流程（创建、开始、表演、猜词、跳过、超时、多轮、排名）。

九、后续可扩展功能（非必须）
语音检测：表演者出声时弹警告（利用 wx.getRecorderManager 简单检测）。

表演者道具：选择虚拟道具（帽子、眼镜等）增加趣味。

回放/战报：生成 GIF 或摘要分享到朋友圈。

AI 辅助提示：猜词者卡顿时，AI 给出一个字提示（消耗积分）。