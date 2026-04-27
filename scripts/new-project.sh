#!/usr/bin/env bash

set -euo pipefail

usage() {
  echo "Usage: $0 <project-name> <type>"
  echo "Types: wechat-mini | mobile-app | web-app | node-api | python-service"
}

if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
  usage
  exit 1
fi

PROJECT_NAME="$1"
PROJECT_TYPE="$2"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

case "$PROJECT_TYPE" in
  wechat-mini)
    TARGET_DIR="$ROOT_DIR/projects/wechat-mini/$PROJECT_NAME"
    ;;
  mobile-app)
    TARGET_DIR="$ROOT_DIR/projects/mobile-app/$PROJECT_NAME"
    ;;
  web-app)
    TARGET_DIR="$ROOT_DIR/projects/web-app/$PROJECT_NAME"
    ;;
  node-api|python-service)
    TARGET_DIR="$ROOT_DIR/projects/backend/$PROJECT_NAME"
    ;;
  *)
    echo "Error: unsupported type '$PROJECT_TYPE'"
    usage
    exit 1
    ;;
esac

if [ -d "$TARGET_DIR" ]; then
  echo "Error: project already exists at $TARGET_DIR"
  exit 1
fi

mkdir -p "$ROOT_DIR/projects/wechat-mini" "$ROOT_DIR/projects/mobile-app" "$ROOT_DIR/projects/web-app" "$ROOT_DIR/projects/backend"

mkdir -p "$TARGET_DIR"/{docs,src,tests}

cat > "$TARGET_DIR/README.md" <<EOF
# $PROJECT_NAME

Project type: $PROJECT_TYPE

## Quick Start

- Fill this README with setup and run steps.
- Add environment variables to .env.example.
- Initialize git in this project folder if needed.
EOF

cat > "$TARGET_DIR/.env.example" <<'EOF'
# Add environment variables here
EOF

cat > "$TARGET_DIR/CHANGELOG.md" <<'EOF'
# Changelog

All notable changes to this project will be documented here.
EOF

cat > "$TARGET_DIR/docs/NOTES.md" <<'EOF'
# Project Notes

Use this file for architecture notes and TODOs.
EOF

cat > "$TARGET_DIR/tests/README.md" <<'EOF'
# Tests

Add test cases for core behavior here.
EOF

cat > "$TARGET_DIR/src/README.md" <<'EOF'
# Source

Application source code lives here.
EOF

if [ "$PROJECT_TYPE" = "node-api" ] || [ "$PROJECT_TYPE" = "web-app" ]; then
  cat > "$TARGET_DIR/package.json" <<EOF
{
  "name": "$PROJECT_NAME",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "echo \"replace with your dev command\"",
    "test": "echo \"replace with your test command\""
  }
}
EOF
fi

if [ "$PROJECT_TYPE" = "wechat-mini" ]; then
  mkdir -p "$TARGET_DIR/pages/index"

  cat > "$TARGET_DIR/app.js" <<'EOF'
App({
  onLaunch() {
    // App init hook
  },
});
EOF

  cat > "$TARGET_DIR/app.json" <<'EOF'
{
  "pages": [
    "pages/index/index"
  ],
  "window": {
    "navigationBarTitleText": "吃什么",
    "navigationBarBackgroundColor": "#ffffff",
    "navigationBarTextStyle": "black",
    "backgroundTextStyle": "light"
  },
  "style": "v2",
  "sitemapLocation": "sitemap.json"
}
EOF

  cat > "$TARGET_DIR/app.wxss" <<'EOF'
page {
  background: #f7f7f7;
  min-height: 100%;
}
EOF

  cat > "$TARGET_DIR/pages/index/index.wxml" <<'EOF'
<view class="container">
  <view class="title">今天吃什么？</view>
  <button type="primary" bindtap="pickFood">帮我选一个</button>
  <view class="result">{{result}}</view>
</view>
EOF

  cat > "$TARGET_DIR/pages/index/index.js" <<'EOF'
Page({
  data: {
    foods: ["火锅", "米线", "盖饭", "面条", "饺子", "轻食"],
    result: "点击按钮开始选择",
  },
  pickFood() {
    const idx = Math.floor(Math.random() * this.data.foods.length);
    this.setData({ result: `今天吃：${this.data.foods[idx]}` });
  },
});
EOF

  cat > "$TARGET_DIR/pages/index/index.wxss" <<'EOF'
.container {
  padding: 32rpx;
}

.title {
  font-size: 40rpx;
  font-weight: 600;
  margin-bottom: 24rpx;
}

.result {
  margin-top: 24rpx;
  font-size: 32rpx;
  color: #333;
}
EOF

  cat > "$TARGET_DIR/pages/index/index.json" <<'EOF'
{
  "navigationBarTitleText": "吃什么"
}
EOF

  cat > "$TARGET_DIR/sitemap.json" <<'EOF'
{
  "desc": "project sitemap",
  "rules": [{
    "action": "allow",
    "page": "*"
  }]
}
EOF

  cat > "$TARGET_DIR/project.config.json" <<EOF
{
  "description": "$PROJECT_NAME",
  "setting": {
    "es6": true,
    "enhance": true,
    "postcss": true,
    "minified": true
  },
  "compileType": "miniprogram",
  "libVersion": "trial",
  "appid": "touristappid",
  "projectname": "$PROJECT_NAME",
  "simulatorType": "wechat",
  "condition": {}
}
EOF
fi

if [ "$PROJECT_TYPE" = "mobile-app" ]; then
  mkdir -p "$TARGET_DIR/app" "$TARGET_DIR/assets"
fi

if [ "$PROJECT_TYPE" = "python-service" ]; then
  cat > "$TARGET_DIR/pyproject.toml" <<'EOF'
[project]
name = "replace-me"
version = "0.1.0"
description = "Replace with your description"
requires-python = ">=3.11"
EOF
fi

echo "Created project at: $TARGET_DIR"
echo "Next:"
echo "1) cd \"$TARGET_DIR\""
echo "2) git init"
echo "3) start implementing"
