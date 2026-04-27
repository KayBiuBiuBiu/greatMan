/**
 * 云开发环境（可选，用于解决「本机没选云环境 / timeout」）：
 * 1. 打开微信开发者工具 → 云开发 → 在顶部或「设置」里找到「环境ID」（形如 cloud1-xx 或 字母数字串）；
 * 2. 把 id 填到下面 envId，保存后重新编译；
 * 3. 确认已「上传并部署」cloudfunctions/roomService 与（若用身份推理/新版卧底）werewolfService、
 *    undercoverRoomService、首页热门统计 gameStatsService；数据库集合见各文档及 game_clicks（统计用）。
 * 不填时仍会用 wx.cloud.DYNAMIC_CURRENT_ENV（与工具里当前选中的云环境一致）。
 */
module.exports = {
  envId: '',
  /** 为 false 时少打成功类 console，失败仍会详细输出，便于正式版清日志 */
  debugCloudLog: true
}
