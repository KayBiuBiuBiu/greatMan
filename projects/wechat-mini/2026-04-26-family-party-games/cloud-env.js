module.exports = {
  envId: 'cloud1-d9g01no7m292bc511',
  aiProvider: 'hunyuan',
  aiModels: ['hunyuan-lite'],
  /** 混元 OpenAPI 基址；小程序走 wx.cloud.extend.AI，由云开发代连此地址，无需在业务里手写 HTTP */
  hunyuanApiBase: 'https://api.hunyuan.cloud.tencent.com/v1/',
  debugCloudLog: false,

  /** 开发者工具内是否启用 db.watch / gameStats（默认 false，减少工具里 timeout 噪音） */
  allowDbWatchInDevtools: false,
  allowGameStatsInDevtools: false,

  /** 副主持 Agent 标识（ping 展示；留空不影响 hostAgent 基础功能） */
  agentBotId: 'party-host-agent',
  agentEnabled: true,
  agentAutoHost: true
}
