#!/bin/bash
# 上传小程序代码 + 部署云函数（需先开启开发者工具「服务端口」）
# 用法：
#   export WX_CLOUD_ENV="你的云环境ID"   # 云开发控制台 → 环境 ID
#   ./scripts/upload-wechat.sh
# 或：
#   WX_CLOUD_ENV=cloud1-xxx ./scripts/upload-wechat.sh "1.0.2" "聚会组人数刷新与开始说明"

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLI="/Applications/wechatwebdevtools.app/Contents/MacOS/cli"
VERSION="${1:-1.0.$(date +%Y%m%d)}"
DESC="${2:-聚会组：成员刷新、开始失败弹窗、邀请分享、猜歌至少2人}"
ENV_ID="${WX_CLOUD_ENV:-cloud1-d9g01no7m292bc511-d5e875d}"

if [[ ! -x "$CLI" ]]; then
  echo "未找到微信开发者工具 CLI: $CLI"
  exit 1
fi

echo "==> 检查登录…"
if ! "$CLI" islogin 2>/dev/null | grep -q "logged in\|已登录\|login"; then
  echo "请先在微信开发者工具中登录，或执行: $CLI login"
  exit 1
fi

echo "==> 上传小程序代码 version=$VERSION"
"$CLI" upload --project "$ROOT" -v "$VERSION" -d "$DESC"

if [[ -z "$ENV_ID" ]]; then
  echo ""
  echo "未设置 WX_CLOUD_ENV，已跳过云函数部署。"
  echo "本次改动了 musicRoomService（猜歌至少2人），请手动部署或："
  echo "  export WX_CLOUD_ENV=你的环境ID"
  echo "  $CLI cloud functions deploy --project \"$ROOT\" --env \"\$WX_CLOUD_ENV\" -n musicRoomService -r"
  exit 0
fi

echo "==> 部署云函数 musicRoomService（env=$ENV_ID）"
"$CLI" cloud functions deploy \
  --project "$ROOT" \
  --env "$ENV_ID" \
  --names musicRoomService \
  --remote-npm-install

echo "完成。请在微信公众平台 → 版本管理 中设为体验版/提交审核。"
