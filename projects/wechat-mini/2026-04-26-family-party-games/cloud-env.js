module.exports = {
  /**
   * 标准版（必须用此 ID，不要用个人版）
   * - 标准版 EnvId: cloud1-d9g01no7m292bc511-d5e875d
   * - 个人版 EnvId: cloud1-d9g01no7m292bc511（开发者工具里常显示名「cloud1」）
   */
  envId: 'cloud1-d9g01no7m292bc511-d5e875d',
  /**
   * 混元升级（2025-05）：createModel("hunyuan-v3") + model "hy3-preview"
   * 勿用 hunyuan-exp / cloudbase 路径，否则赠送 Token 不计入或报 429
   */
  aiProvider: 'hunyuan-v3',
  aiModels: ['hy3-preview'],
  aiClientAttempts: [{ provider: 'hunyuan-v3', models: ['hy3-preview'] }],
  /** 混元 OpenAPI 基址；小程序走 wx.cloud.extend.AI，由云开发代连此地址，无需在业务里手写 HTTP */
  hunyuanApiBase: 'https://api.hunyuan.cloud.tencent.com/v1/',
  debugCloudLog: false,

  /** 开发者工具内是否启用 db.watch / gameStats / shareService（默认 false，减少工具里 timeout 噪音） */
  allowDbWatchInDevtools: false,
  allowGameStatsInDevtools: false,
  allowShareCloudInDevtools: false,

  /** 同房 syncState 轮询间隔（毫秒）；真机有 db.watch 时自动用更慢的兜底间隔 */
  inRoomPollIntervalMs: 0,

  /** 优先使用增强云函数（未部署时自动回退 hostAgent / 本地画布卡片） */
  useHostAgentEnhanced: true,
  useShareCardGenerator: true,

  /** 副主持 Agent 标识（ping 展示；留空不影响 hostAgent 基础功能） */
  agentBotId: 'party-host-agent',
  agentEnabled: true,
  agentAutoHost: true,

  /**
   * 可选：覆盖默认包内路径 /assets/audio/ring.mp3（一般留空即可）
   */
  drinkRingAudioUrl: ''
}
