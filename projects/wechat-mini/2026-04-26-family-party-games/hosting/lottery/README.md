# 聚会抽奖 · 静态页

适合家庭/公司聚会的大屏抽奖，纯 HTML，无后端。可部署到 **腾讯云 CloudBase 静态网站托管**。

## 功能

- 批量导入名单（每人一行或逗号分隔）
- **四档固定奖项**（每档 1 人）：
  - 一等奖 · 一顿夜宵
  - 二等奖 · 一顿晚饭
  - 三等奖 · 一瓶香槟
  - 四等奖 · 2个月将神卡
- 「下一档未开奖」按四等→一等顺序开；也可点选某一档单独抽
- 滚动动画 + 彩带庆祝
- 默认「已中奖剔除」；可勾选允许重复中奖
- 中奖记录、本地 `localStorage` 自动保存

## 本地预览

```bash
cd hosting/lottery
python3 -m http.server 8765
# 浏览器打开 http://127.0.0.1:8765
```

或直接双击 `index.html`（部分浏览器对 file:// 限制 localStorage）。

## 部署到 CloudBase 静态托管

环境 ID 与小程序一致：`cloud1-d9g01no7m292bc511-d5e875d`（见项目根 `cloudbaserc.json`）。

```bash
cd /Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
./scripts/deploy-lottery-hosting.sh
```

或手动：

```bash
npx -p @cloudbase/cli@3.4.0 tcb hosting deploy hosting/lottery \
  -e cloud1-d9g01no7m292bc511-d5e875d
```

部署后在控制台 **静态网站托管 → 默认域名** 访问；建议绑定自定义域名并开启 HTTPS。

## 与小程序关系

本页独立运行，不依赖微信登录。可在聚会现场用 iPad/电脑浏览器打开；小程序内如需跳转，可用 web-view 加载托管域名（需配置业务域名）。
