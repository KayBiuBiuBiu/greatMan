# Minium 测试诊断和恢复指南

## 当前状态

✅ **已完成**：11/17 用例通过（64.7%）
⚠️ **待处理**：song-guess 人数不足 + mystery-reason 2 条用例

## 🔧 快速排查步骤

### 步骤 1：验证开发环境

```bash
# 1.1 检查微信开发者工具是否运行
ps aux | grep -i "wechatwebdevtools\|WeChat" | grep -v grep

# 1.2 检查云环境 ID 配置
cd /Users/haha/greatMan/minium-tests
cat config.json | python3 -m json.tool | grep -A2 -B2 "cloud"

# 预期输出：
# "cloud_env_id": "cloud1-d9g01no7m292bc511-d5e875d",
# "test_port": 63518
```

### 步骤 2：验证小程序项目编译状态

```bash
# 在微信开发者工具中：
# 1. 左上角确认项目路径：/Users/haha/greatMan/projects/wechat-mini/2026-04-26-family-party-games
# 2. 点击「编译」，确保状态栏显示「编译完成」
# 3. 预览器中小程序能正常启动（显示首页游戏列表）
```

### 步骤 3：清理并重新运行完整测试

```bash
# 3.1 停止旧的 minitest 进程
pkill -f "minitest"

# 3.2 清理输出目录（可选，保留最新结果用于对比）
# rm -rf /Users/haha/greatMan/minium-tests/outputs/2026*

# 3.3 运行完整套件，保存到日志
cd /Users/haha/greatMan/minium-tests
python3 run_tests.py 2>&1 | tee run_$(date +%Y%m%d_%H%M%S).log

# 预期：10-15 分钟内完成，最后显示 PASS 或 FAIL 统计
```

### 步骤 4：检查结果

```bash
# 4.1 查看最新报告
open /Users/haha/greatMan/minium-tests/outputs/report.html

# 4.2 如有失败，查看详细日志
tail -200 /Users/haha/greatMan/minium-tests/outputs/loader*.log | grep -A5 "FAILED\|ERROR"

# 4.3 单独运行失败的用例
minitest -m testcases.test_all_games::test_14_song_guess_insufficient_players \
  -c config.json -g
```

## 🎯 目标用例快速修复

### 问题 1：`test_14_song_guess_insufficient_players` 阻塞

**症状**：连接超时、LoadCaseError

**快速修复**：
```bash
# 1. 检查 config.json 中的 test_port
# 确保与微信开发者工具的「设置 → 安全 → 端口」一致

# 2. 如果端口不匹配，更新 config.json
# cat config.json | sed 's/"test_port": [0-9]*/"test_port": 63518/' > config.json.tmp
# mv config.json.tmp config.json

# 3. 重启微信开发者工具并重新运行该用例
```

### 问题 2：`test_08_mystery_reason_core_flow` 和 `test_17_mystery_reason_insufficient_players` 失败

**症状**：云函数初始化失败或剧本生成异常

**快速修复**：
```bash
# 1. 检查 mysteryReasonRoomService 云函数是否已部署
# 在微信开发者工具 → 云开发 → 云函数 中查看

# 2. 查看云函数日志
# 微信开发者工具 → 云开发 → 云函数 → mysteryReasonRoomService → 日志

# 3. 如需重新部署
# 在开发者工具右键 mysteryReasonRoomService → 增量上传

# 4. 检查小程序端是否传入了 roomId（关键参数）
# 查看 minium-tests/testcases/ 中对应的测试代码
```

## 📝 测试跑完后的验证清单

运行 `python3 run_tests.py` 后，检查：

- [ ] 所有 17 条用例都有结果（通过、失败或错误）
- [ ] 通过数 ≥ 14（包括 11 个已通过 + 至少 3 个修复）
- [ ] `report.html` 中的进度条显示绿色区域 ≥ 80%
- [ ] 日志中没有 `wx.cloud.callFunction not exists` 错误（或仅在特定用例出现）
- [ ] 没有 `ConnectionError` 或 `WebSocket timeout`

## 🚀 成功标志

当以下条件全部满足时，视为改造完成：

✅ **15/17 用例通过**（88%+ 通过率）
✅ **所有核心游戏流程通过** (test_01 ~ test_07，即 7/7)
✅ **大多数人数不足场景通过** (test_11~16，即 ≥5/6)
✅ **剧本杀至少 1 条通过** (test_08 或 test_17 之一)

## 常见错误与解决方案

| 错误信息 | 原因 | 解决方案 |
|---------|------|--------|
| `ConnectionRefused:63518` | 微信开发者工具未运行或端口不对 | 重启工具，确认端口 |
| `LoadCaseError` | 用例加载失败 | 检查 testcases 文件夹结构 |
| `wx.cloud.callFunction not exists` | Cloud 初始化未完成 | 确保小程序编译完成，重新运行 |
| `room not found` | 云数据库房间创建失败 | 检查云环境权限和网络 |
| `timeout after 12s` | 操作超时 | 增加 `default_timeout` 或检查网络 |

## 💬 如需支持

1. 收集错误日志：`outputs/loader*.log`
2. 导出最新报告：`outputs/report.html`
3. 记录运行时间戳（便于查找对应日志）
4. 提供失败的具体用例名称

---

**预期下一步**：
按上述步骤排查后，应能达到 ≥14/17 通过。如仍有问题，提供日志我帮你继续诊断。
